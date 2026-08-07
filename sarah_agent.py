"""
Sarah agent backend — the brain.

Until now Sarah's brain lived in sarah-avatar-ui.html: the browser page called
api.anthropic.com directly, one request per utterance. That design capped what
she could ever do, because a browser page cannot spawn a process, hold an OAuth
refresh token, read a repo off disk, or run git. Every capability had to be
hand-proxied through sarah_server.py (see _proxy_openai / _proxy_github there) —
about forty lines of bespoke plumbing per connector, which does not scale to
"everything connected at the back end".

So the brain moved here. This process runs the Claude Agent SDK, which ships the
agent loop plus Read/Write/Edit/Bash/Glob/Grep/WebSearch/WebFetch and MCP
support already wired. The avatar page is now a client: it sends utterances over
a WebSocket and renders what comes back. sarah_server.py keeps its old job of
serving the page (and its existing proxies still work for the legacy in-page
brain, so nothing breaks mid-migration).

    browser  ──ws://127.0.0.1:8766──>  sarah_agent.py  ──> Claude Agent SDK
                                                        └─> files, bash, git, MCP

Permissions (chosen by Adeel, 2026-08-07): free rein inside the named
workspaces below, confirmation for anything outside them and for anything
destructive. Confirmation prompts are pushed to the browser and answered by
voice or click — see _decide() for the exact rules and their limits.

Run:  pythonw sarah_agent.py     (or run_sarah_agent.vbs)
"""

import asyncio
import json
import re
import shlex
import sys
import time
from pathlib import Path

import websockets
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
)

PORT = 8766
BASE_DIR = Path(__file__).resolve().parent
LOG_FILE = BASE_DIR / "sarah_agent.log"

# The named folders Sarah may work in without asking. Everything else — the rest
# of the disk, and every destructive command wherever it runs — needs a yes.
SARAH_DIR = BASE_DIR
APEX_DIR = Path(r"C:\Users\asid3\Documents\APEX\APEX_Website\APEX")
WORKSPACES = [p for p in (SARAH_DIR, APEX_DIR) if p.exists()]

MODEL = "claude-opus-5"

SARAH_PERSONA = """\
You are Sarah, Adeel's personal assistant. You are speaking to him — most of \
your replies are read aloud, so keep them short and conversational (1-3 \
sentences) unless he asks for detail. No markdown headers or bullet lists in \
spoken replies; write the way you would talk.

You have real tools. Use them rather than describing what you would do or \
promising to check later. When he asks about a file, read it. When he asks for \
a change, make it. When you have acted, say what you actually did.

His main project right now is the APEX Physiotherapy & Wellness Clinic website \
at {apex}. It is a static site; the deployable folder is the apexphysio/ \
subfolder. Your own source lives at {sarah}.

If he asks for design options, produce genuinely distinct directions rather \
than variations on one idea, and describe them briefly enough to hear.

You may edit freely inside those two folders. Anything outside them, and \
anything destructive, will pause for his confirmation — that is expected, not \
an error. Do not try to work around it.
""".format(apex=APEX_DIR, sarah=SARAH_DIR)

# Tools that only observe. Always allowed — reading is not a side effect.
READ_ONLY_TOOLS = {
    "Read", "Glob", "Grep", "WebSearch", "WebFetch", "NotebookRead",
    "TodoWrite", "Task", "BashOutput",
}
# Tools that change files. Allowed inside WORKSPACES, confirmed outside.
WRITE_TOOLS = {"Write", "Edit", "NotebookEdit", "MultiEdit"}

# Shell commands that are hard to undo or reach outside this machine. These
# always confirm, even inside a workspace — the allowlist is about *location*,
# and these are dangerous regardless of where they run.
DESTRUCTIVE = re.compile(
    r"""(?xi)
    \brm\s+(-\w*\s+)*-\w*[rf]           # rm -rf / rm -fr
  | \brmdir\b | \bdel\s+/[sq]           # windows recursive delete
  | \bformat\b | \bmkfs\b
  | \bgit\s+push\b.*(--force|-f\b)      # force push
  | \bgit\s+reset\b.*--hard
  | \bgit\s+clean\b.*-\w*[fd]
  | \bshutdown\b | \breboot\b | \bTaskkill\b
  | \b(curl|wget|iwr|Invoke-WebRequest)\b.*\|\s*(sh|bash|iex)   # pipe-to-shell
  | \bnpm\s+publish\b | \bgh\s+release\b | \bnetlify\s+deploy\b # outward-facing
  | \bDROP\s+(TABLE|DATABASE)\b
    """
)


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def in_workspace(raw_path: str) -> bool:
    """True if raw_path resolves inside one of the named folders.

    resolve() first so that '..' segments and symlinks can't be used to step
    out of a workspace via a path that only looks contained.
    """
    if not raw_path:
        return False
    try:
        p = Path(raw_path)
        if not p.is_absolute():
            p = SARAH_DIR / p
        p = p.resolve()
    except (OSError, ValueError):
        return False
    return any(p == w or w in p.parents for w in WORKSPACES)


def paths_in_command(command: str) -> list[str]:
    """Absolute-looking paths mentioned in a shell command.

    Deliberately crude. A shell command is not statically analyzable in
    general — substitutions, variables and quoting can all hide a path — so
    this is a filter that catches the obvious cases, not a security boundary.
    The real boundary is that anything it can't vouch for gets confirmed.
    """
    try:
        parts = shlex.split(command, posix=False)
    except ValueError:
        parts = command.split()
    out = []
    for part in parts:
        part = part.strip('"\'')
        if re.match(r"^[A-Za-z]:[\\/]", part) or part.startswith(("/", "\\\\")):
            out.append(part)
    return out


class Sarah:
    def __init__(self):
        self.ws = None                 # the connected browser, if any
        self.pending: dict[str, asyncio.Future] = {}
        self.client: ClaudeSDKClient | None = None
        self.busy = False

    # ---------- browser plumbing ----------

    async def send(self, payload: dict) -> None:
        if self.ws is None:
            return
        try:
            await self.ws.send(json.dumps(payload))
        except websockets.exceptions.ConnectionClosed:
            self.ws = None

    async def ask_user(self, tool: str, summary: str, detail: str) -> bool:
        """Push a confirmation to the browser and wait for the answer.

        Fails closed: with no browser attached there is nobody to approve, so
        the action is denied rather than silently allowed.
        """
        if self.ws is None:
            log(f"DENY (no UI attached) {tool}: {summary}")
            return False
        req_id = f"perm_{int(time.time() * 1000)}_{len(self.pending)}"
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self.pending[req_id] = fut
        await self.send({
            "type": "permission", "id": req_id,
            "tool": tool, "summary": summary, "detail": detail[:400],
        })
        try:
            return await asyncio.wait_for(fut, timeout=180)
        except asyncio.TimeoutError:
            log(f"DENY (timed out) {tool}: {summary}")
            return False
        finally:
            self.pending.pop(req_id, None)

    # ---------- permission policy ----------

    def _decide(self, tool: str, data: dict) -> tuple[bool, str, str]:
        """(allowed_outright, summary, reason) — reason explains a confirm."""
        if tool in READ_ONLY_TOOLS:
            return True, "", ""

        if tool in WRITE_TOOLS:
            path = data.get("file_path") or data.get("notebook_path") or ""
            name = Path(path).name or path
            if in_workspace(path):
                return True, f"{tool} {name}", ""
            return False, f"{tool} {name}", f"{path} is outside your named folders"

        if tool == "Bash":
            cmd = (data.get("command") or "").strip()
            short = cmd if len(cmd) <= 90 else cmd[:87] + "..."
            if DESTRUCTIVE.search(cmd):
                return False, short, "this command is destructive or outward-facing"
            stray = [p for p in paths_in_command(cmd) if not in_workspace(p)]
            if stray:
                return False, short, f"it touches {stray[0]}, outside your named folders"
            return True, short, ""

        # Unknown tool (an MCP connector, say). Confirm the first time —
        # better to ask about something harmless than to auto-run something new.
        return False, tool, "this is a tool I haven't been given standing approval for"

    async def can_use_tool(self, tool_name, input_data, context):
        allowed, summary, reason = self._decide(tool_name, input_data or {})
        if allowed:
            if summary:
                await self.send({"type": "tool", "name": tool_name, "summary": summary})
            return PermissionResultAllow(updated_input=input_data)

        log(f"ASK {tool_name}: {summary} ({reason})")
        ok = await self.ask_user(tool_name, summary, reason)
        if ok:
            log(f"  approved: {tool_name} {summary}")
            return PermissionResultAllow(updated_input=input_data)
        return PermissionResultDeny(
            message=f"Adeel declined: {reason}. Do not retry this; ask him what to do instead.",
        )

    # ---------- the agent loop ----------

    async def start(self) -> None:
        options = ClaudeAgentOptions(
            model=MODEL,
            cwd=str(SARAH_DIR),
            add_dirs=[str(p) for p in WORKSPACES if p != SARAH_DIR],
            system_prompt={"type": "preset", "preset": "claude_code", "append": SARAH_PERSONA},
            permission_mode="default",
            can_use_tool=self.can_use_tool,
        )
        self.client = ClaudeSDKClient(options=options)
        await self.client.connect()
        log(f"Agent connected. model={MODEL} workspaces={[str(w) for w in WORKSPACES]}")

    async def handle_utterance(self, text: str) -> None:
        if self.busy:
            await self.send({"type": "error", "message": "Still working on the last one."})
            return
        self.busy = True
        await self.send({"type": "status", "state": "thinking"})
        try:
            await self.client.query(text)
            async for message in self.client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock) and block.text.strip():
                            await self.send({"type": "text", "text": block.text})
                        elif isinstance(block, ThinkingBlock):
                            await self.send({"type": "status", "state": "thinking"})
                        elif isinstance(block, ToolUseBlock):
                            await self.send({"type": "status", "state": "acting"})
                elif isinstance(message, ResultMessage):
                    await self.send({
                        "type": "done",
                        "reason": message.terminal_reason,
                        "cost_usd": message.total_cost_usd,
                    })
        except Exception as e:                      # noqa: BLE001 - surface everything
            log(f"ERROR during turn: {e!r}")
            await self.send({"type": "error", "message": str(e)})
        finally:
            self.busy = False
            await self.send({"type": "status", "state": "idle"})

    # ---------- websocket server ----------

    async def serve(self, ws) -> None:
        if self.ws is not None:
            # One face at a time; a stale tab shouldn't shadow the live one.
            try:
                await self.ws.close()
            except Exception:                        # noqa: BLE001
                pass
        self.ws = ws
        log("Browser attached.")
        await self.send({"type": "status", "state": "idle"})
        await self.send({
            "type": "hello",
            "model": MODEL,
            "workspaces": [str(w) for w in WORKSPACES],
        })
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                kind = msg.get("type")
                if kind == "user":
                    text = (msg.get("text") or "").strip()
                    if text:
                        log(f"> {text}")
                        asyncio.create_task(self.handle_utterance(text))
                elif kind == "permission_result":
                    fut = self.pending.get(msg.get("id"))
                    if fut and not fut.done():
                        fut.set_result(bool(msg.get("allow")))
                elif kind == "interrupt":
                    if self.client:
                        await self.client.interrupt()
                        log("Interrupted.")
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            if self.ws is ws:
                self.ws = None
            log("Browser detached.")


async def main() -> None:
    missing = [str(p) for p in (SARAH_DIR, APEX_DIR) if not p.exists()]
    if missing:
        log(f"WARNING: workspace not found, skipping: {missing}")

    sarah = Sarah()
    try:
        await sarah.start()
    except Exception as e:                           # noqa: BLE001
        log(f"FATAL: could not start agent: {e!r}")
        log("Is the `claude` CLI installed and authenticated? Try `claude` in a terminal.")
        sys.exit(1)

    async with websockets.serve(sarah.serve, "127.0.0.1", PORT):
        log(f"Sarah agent listening on ws://127.0.0.1:{PORT}")
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
