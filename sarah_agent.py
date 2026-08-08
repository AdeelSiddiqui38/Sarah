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
    AgentDefinition,
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

# Sarah's memory, as a plain file she can read and append to herself.
# It lives here rather than in the browser's localStorage because the browser
# is no longer the brain: anything only the page knows is invisible to the
# agent. This file is the single source of truth; the page's old memoryNotes
# are merged in once on connect and then follow this.
MEMORY_FILE = BASE_DIR / "sarah_memory.md"
# Last conversation id, so a restarted agent picks up where it left off
# instead of forgetting the thread mid-task.
SESSION_FILE = BASE_DIR / ".sarah_session"

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

Your memory is the file {memory}. When he tells you to remember something, \
append it there as a single "- " line, in your own words, and confirm briefly. \
Read the file if you need older context than this conversation holds. Keep it \
tidy — update a line rather than adding a near-duplicate, and drop anything \
that turns out to be wrong.

You run locally on this machine and are already authenticated. You do **not** \
use an OpenAI or Anthropic API key — the provider and key boxes in the avatar's \
Settings are only a fallback for when this agent is offline. Never ask Adeel \
for an API key and never say you need one; if he asks about keys, tell him \
plainly that you don't use one while the agent is running.

You may edit freely inside those two folders. Anything outside them, anything \
destructive, and anything that sends, posts, or books on his behalf will pause \
for his confirmation — that is expected, not an error. Do not try to work \
around it, and never assume a confirmation was granted.

You have a small team of specialists you can delegate to — a researcher, a \
coder, and a connector specialist (see their own descriptions). Delegate when \
a task is squarely one of theirs, especially anything that would mean reading \
several files or messages that don't need to clutter this conversation. \
Handle short, simple requests yourself rather than delegating out of habit.
""".format(apex=APEX_DIR, sarah=SARAH_DIR, memory=MEMORY_FILE)

# claude.ai's account-managed connectors carry this literal prefix and spaces
# in their registered name (confirmed via `claude mcp get "claude.ai Gmail"`);
# they are not in any local config file, fetched at session auth instead. Kept
# as a constant so a renamed/added connector is a one-line change.
CONNECTOR_SERVERS = [
    "claude.ai Gmail", "claude.ai Google Calendar", "claude.ai Google Drive",
    "claude.ai Notion", "claude.ai Xero", "claude.ai Canva",
]

# The team. Kept to three, each covering a genuinely distinct part of what
# Sarah actually does — not padded out to look more "team"-like. The real
# payoff isn't the count, it's that an agent nobody delegates to costs nothing
# and says nothing: Claude picks by description, and everything else stays
# silent by default.
#
# Every specialist gets the same reminder about confirmation. can_use_tool is
# registered once on the session (see start()), and it fires for a tool call
# regardless of whether the main thread or a subagent issued it — verified
# live (README/SARAH_PROJECT_STATE.md, 2026-08-07) by having the coder agent
# attempt a write outside the workspace and confirming the same prompt fired
# and a decline blocked it. The reminder in each prompt is belt-and-suspenders
# for the model's behavior, not what actually enforces the boundary.
_CONFIRM_REMINDER = (
    "The same confirmation rules apply to you as to Sarah herself, and there is "
    "no way around them — anything outside the two named folders, anything "
    "destructive, and anything that acts on the outside world through a "
    "connector will pause for Adeel's yes exactly as it would if he'd asked "
    "Sarah directly. Don't try to route around that, and don't assume a "
    "confirmation was granted."
)

TEAM = {
    "researcher": AgentDefinition(
        description=(
            "Looks things up without changing anything: web search, reading "
            "documentation, exploring an unfamiliar part of a codebase, "
            "answering 'what does X say' or 'find out about Y'. Use for "
            "information-gathering, not for anything that should write a "
            "file or run a command."
        ),
        prompt=(
            "You are Sarah's research specialist. Find the answer, check it "
            "against a real source, and report back in a sentence or two — "
            "not a transcript of your search. You have no write or execute "
            "tools; if the task turns out to need a change, say so and stop "
            "rather than trying to make it happen anyway."
        ),
        tools=["Read", "Grep", "Glob", "WebSearch", "WebFetch"],
        model="sonnet",
    ),
    "coder": AgentDefinition(
        description=(
            "Makes file and code changes: editing, multi-file work, running "
            "builds or tests, git. Use for anything that writes to disk or "
            "runs a shell command, especially work that would touch several "
            "files and shouldn't fill up the main conversation with every "
            "intermediate read."
        ),
        prompt=(
            f"You are Sarah's coding specialist, working inside {SARAH_DIR} "
            f"and {APEX_DIR}. Make the change, verify it — run it, check the "
            f"diff — and report what you actually did in a sentence or two. "
            f"{_CONFIRM_REMINDER}"
        ),
        tools=["Read", "Edit", "Write", "Bash", "Glob", "Grep"],
        model="opus",
    ),
    "connector": AgentDefinition(
        description=(
            "Works with Gmail, Google Calendar, Google Drive, Notion, Xero, "
            "or Canva — checking the inbox, looking at the calendar, "
            "searching Drive or Notion, pulling invoices. Use when a task "
            "means reading several messages, events, or pages whose full "
            "content doesn't need to reach the main conversation, not for a "
            "single quick lookup."
        ),
        prompt=(
            "You are Sarah's connector specialist. Read what's asked and "
            f"report back a short summary — not raw message bodies or full "
            f"event dumps. {_CONFIRM_REMINDER}"
        ),
        # Left off `tools` entirely at first, which meant this agent also
        # inherited Bash/Write/Edit despite existing to read connectors and
        # report back — the opposite of the least-privilege point of scoping
        # it. disallowedTools trims those explicitly since `tools` doesn't
        # document accepting an `mcp__*` wildcard to grant the connector
        # servers back if listed there instead.
        disallowedTools=["Bash", "Write", "Edit", "NotebookEdit", "MultiEdit"],
        mcpServers=CONNECTOR_SERVERS,
        model="opus",
    ),
}

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

# --- MCP connectors (Gmail, Calendar, Drive, Notion, ... configured via
# `claude mcp add`; the SDK inherits those from the CLI). Tool names arrive as
# mcp__<server>__<action>.
#
# The split that matters: *looking* is free, because an assistant that needs
# permission to read your own calendar is useless. *Acting on the outside
# world* always confirms — sending mail, creating events, posting, booking,
# paying. Those are irreversible and visible to other people, so they never get
# standing approval no matter how many times they've been approved before.
MCP_READ = re.compile(
    r"(?i)(^|_)(list|get|search|read|find|fetch|view|query|show|describe|check|count|download)(_|$)"
)
MCP_NEVER_AUTO = re.compile(
    r"(?i)(^|_)(send|post|reply|forward|create|add|update|edit|delete|remove|archive|"
    r"move|share|invite|book|order|buy|pay|checkout|publish|upload|write|schedule|cancel)(_|$)"
)


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def read_memory() -> str:
    try:
        return MEMORY_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def memory_facts() -> str:
    """Just the remembered facts — the "- " lines.

    The file also carries a title and a paragraph explaining how it works. That
    prose is for a human opening the file, not for the avatar's Settings box or
    for merging back. Mirroring the whole file put documentation in the UI where
    facts should be, and would have re-appended those sentences as bullets on
    every reconnect.
    """
    return "\n".join(
        ln.rstrip() for ln in read_memory().splitlines() if ln.lstrip().startswith("- ")
    ).strip()


def merge_browser_memory(notes: str) -> int:
    """Fold the avatar's old localStorage notes into the memory file.

    Runs on every connect, but only appends lines that aren't already there —
    so it migrates the existing notes once and is a no-op afterwards.
    """
    # Only real facts travel. Headings and prose are skipped so the file's own
    # explanatory header can never round-trip back in as bullets.
    incoming = [
        ln.strip().lstrip("-").strip()
        for ln in (notes or "").splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    incoming = [ln for ln in incoming if ln]
    if not incoming:
        return 0
    existing = read_memory()
    have = {ln.strip().lstrip("-").strip().lower() for ln in existing.splitlines()}
    new = [ln for ln in incoming if ln.lower() not in have]
    if not new:
        return 0
    header = "" if existing else "# What Sarah remembers about Adeel\n"
    with open(MEMORY_FILE, "a", encoding="utf-8") as f:
        if not existing:
            f.write(header + "\n")
        for ln in new:
            f.write(f"- {ln}\n")
    return len(new)


def load_session_id() -> str | None:
    try:
        sid = SESSION_FILE.read_text(encoding="utf-8").strip()
        return sid or None
    except OSError:
        return None


def save_session_id(sid: str) -> None:
    try:
        SESSION_FILE.write_text(sid, encoding="utf-8")
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
        # Every attached face. This is a set rather than a single socket
        # because kicking the previous client turned two open tabs into an
        # infinite fight: each attach closed the other, whose auto-reconnect
        # immediately closed the first. Broadcasting to all of them is both
        # simpler and better — Sarah can be open on two screens.
        self.clients: set = set()
        self.pending: dict[str, asyncio.Future] = {}
        self.client: ClaudeSDKClient | None = None
        self.busy = False
        self.memory_sent = ""          # memory already in the system prompt
        self.projects: list[str] = []  # names only; the page owns the URLs
        self.projects_sent = False

    # ---------- browser plumbing ----------

    async def send(self, payload: dict) -> None:
        if not self.clients:
            return
        raw = json.dumps(payload)
        for ws in list(self.clients):
            try:
                await ws.send(raw)
            except websockets.exceptions.ConnectionClosed:
                self.clients.discard(ws)

    async def ask_user(self, tool: str, summary: str, detail: str) -> bool:
        """Push a confirmation to the browser and wait for the answer.

        Fails closed: with no browser attached there is nobody to approve, so
        the action is denied rather than silently allowed.
        """
        if not self.clients:
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
        if tool in ("Agent", "Task"):
            # Delegation itself is never gated — the actions the specialist
            # takes still go through this same method (can_use_tool is one
            # session-level callback, not one per subagent), so there is
            # nothing to protect by confirming the handoff. Giving it a
            # summary instead of the usual silent "" is what makes the team
            # visible: you see who picked up the task, and everyone Claude
            # didn't delegate to is silent by simply never appearing here.
            which = data.get("subagent_type") or "a specialist"
            desc = (data.get("description") or "").strip()
            return True, f"→ {which} agent" + (f": {desc}" if desc else ""), ""

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

        if tool.startswith("mcp__"):
            parts = tool.split("__", 2)
            service = parts[1] if len(parts) > 2 else "a connector"
            action = parts[2] if len(parts) > 2 else tool
            pretty = f"{action.replace('_', ' ')} ({service})"
            # Order matters: check the acting verbs first, so a name like
            # "get_or_create_page" confirms rather than passing as a read.
            if MCP_NEVER_AUTO.search(action):
                return False, pretty, "it acts on the outside world through your account"
            if MCP_READ.search(action):
                return True, pretty, ""
            return False, pretty, "I can't tell whether this only reads or also changes something"

        # Anything else unrecognised. Confirm — better to ask about something
        # harmless than to auto-run a tool nobody has vouched for.
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
        memory = memory_facts()
        persona = SARAH_PERSONA
        if memory:
            persona += f"\n\nWhat you already know about Adeel:\n{memory}\n"

        resume_id = load_session_id()
        options = ClaudeAgentOptions(
            model=MODEL,
            cwd=str(SARAH_DIR),
            add_dirs=[str(p) for p in WORKSPACES if p != SARAH_DIR],
            system_prompt={"type": "preset", "preset": "claude_code", "append": persona},
            permission_mode="default",
            can_use_tool=self.can_use_tool,
            resume=resume_id,
            agents=TEAM,
        )
        self.client = ClaudeSDKClient(options=options)
        try:
            await self.client.connect()
        except Exception:                                # noqa: BLE001
            # A stale session id (cleared history, different machine) shouldn't
            # brick startup — drop it and come up fresh.
            if not resume_id:
                raise
            log("Could not resume the previous session; starting a fresh one.")
            SESSION_FILE.unlink(missing_ok=True)
            options.resume = None
            self.client = ClaudeSDKClient(options=options)
            await self.client.connect()

        self.memory_sent = memory
        log(
            f"Agent connected. model={MODEL} "
            f"workspaces={[str(w) for w in WORKSPACES]} "
            f"memory={'yes' if memory else 'empty'} "
            f"resumed={'yes' if resume_id else 'no'}"
        )

    def _with_context(self, text: str) -> str:
        """Prepend memory/projects only when they've changed since last sent.

        The system prompt is fixed once the client connects, so anything Sarah
        learns mid-session (a new "remember that ...", a re-imported project
        list) would otherwise not reach her until a restart. Sending it only on
        change keeps the prompt cache intact for the common case.
        """
        blocks = []
        current = memory_facts()
        if current and current != self.memory_sent:
            blocks.append(f"Updated memory about Adeel:\n{current}")
            self.memory_sent = current
        if self.projects and not self.projects_sent:
            blocks.append("His Claude Projects: " + ", ".join(self.projects))
            self.projects_sent = True
        if not blocks:
            return text
        return "<context>\n" + "\n\n".join(blocks) + "\n</context>\n\n" + text

    async def handle_utterance(self, text: str) -> None:
        if self.busy:
            await self.send({"type": "error", "message": "Still working on the last one."})
            return
        self.busy = True
        await self.send({"type": "status", "state": "thinking"})
        try:
            await self.client.query(self._with_context(text))
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
                    if message.session_id:
                        save_session_id(message.session_id)
                    # She may have appended to memory during the turn; mirror
                    # it back so Settings ⚙ isn't showing a stale list.
                    current = memory_facts()
                    if current != self.memory_sent:
                        self.memory_sent = current
                        await self.send({"type": "memory", "text": current})
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
        self.clients.add(ws)
        log(f"Browser attached ({len(self.clients)} connected).")
        # Greet only the new arrival; the others are already up to date.
        await ws.send(json.dumps({"type": "status", "state": "idle"}))
        await ws.send(json.dumps({
            "type": "hello",
            "model": MODEL,
            "workspaces": [str(w) for w in WORKSPACES],
        }))
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
                elif kind == "context":
                    # The page's legacy memory + its project list. Memory is
                    # merged into the file once; projects are name-only (the
                    # page keeps the URLs and does the opening itself).
                    added = merge_browser_memory(msg.get("memoryNotes") or "")
                    if added:
                        log(f"Merged {added} note(s) from the avatar into {MEMORY_FILE.name}")
                    names = [n for n in (msg.get("projects") or []) if n]
                    if names != self.projects:
                        self.projects = names
                        self.projects_sent = False
                    await self.send({"type": "memory", "text": memory_facts()})
                elif kind == "interrupt":
                    if self.client:
                        await self.client.interrupt()
                        log("Interrupted.")
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.clients.discard(ws)
            log(f"Browser detached ({len(self.clients)} left).")


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
