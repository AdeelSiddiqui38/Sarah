# Sarah

Personal always-on, voice-first assistant ("JARVIS-style") for Adeel.

## Parts
- **sarah_agent.py** — **the brain.** Runs the Claude Agent SDK: real file
  access, bash, git, web, and MCP connectors. Talks to the avatar over
  `ws://127.0.0.1:8766`. This is what makes Sarah able to *do* things.
- **sarah-avatar-ui.html** — the face: voice in/out, in-page wake word, the
  project constellation, transcript, and approval prompts. Served over
  `http://127.0.0.1:8765/`. Keeps a direct Claude/OpenAI brain as a fallback
  for when the agent isn't running.
- **sarah_server.py** — local server: serves this folder + proxies OpenAI and
  GitHub API calls for the fallback brain. Loopback-only.
- **sarah_listener.py** — offline Vosk wake-word listener; say "Sarah" to open
  the avatar even with no browser open.
- **run_sarah_agent.vbs / run_sarah_server.vbs / run_sarah_listener.vbs** —
  silent background launchers. All three autostart at login.

## Memory

`sarah_memory.md` is the single source of truth, owned by the agent. Say
"remember that ..." and she appends to it; it loads into her system prompt at
startup and is re-sent mid-session when it changes, so a restart doesn't forget.
The avatar's Settings ⚙ box mirrors the file rather than holding its own copy —
that split was why she used to behave like two different assistants.

Conversations also survive a restart: the session id is kept in `.sarah_session`
and resumed. Delete that file to start her on a blank thread.

## Team of specialists

Sarah can delegate to three subagents — `researcher`, `coder`, `connector` —
using the Claude Agent SDK's native subagent support (`agents=` on
`ClaudeAgentOptions`, defined in `TEAM` in sarah_agent.py). Claude decides
whether a task warrants delegating based on each one's `description`; anyone
not delegated to costs nothing and does nothing. When she does delegate, you
see it — a "→ coder agent: ..." line in the transcript — so which specialist
picked up the work (and that the other two stayed silent) is visible rather
than happening invisibly inside the model.

Each specialist is scoped to what it actually needs: `researcher` gets read
and web tools only, `coder` gets file/bash/git, `connector` gets your MCP
connectors plus reads, with `Bash`/`Write`/`Edit` explicitly removed. Model
choice is per-agent — `researcher` runs on Sonnet since lookups are usually
less demanding, `coder` and `connector` stay on Opus since their mistakes cost
more.

**This does not create a second permission system.** `can_use_tool` is
registered once on the whole session, so it gates a subagent's tool calls
exactly like it gates Sarah's own — verified live by having the coder
specialist attempt a write to the Desktop, watching the real confirmation
prompt fire, declining it, and confirming the file was never created.
Delegation cannot be used to route around what you've approved.

## Connectors

Sarah inherits every MCP connector configured through the `claude` CLI — no
per-connector code. Currently live: **Gmail, Google Calendar, Google Drive,
Notion, Xero, Canva**. Check with `claude mcp list`; add more via claude.ai →
Settings → Connectors (that's how the six live ones were added — OAuth needs
an interactive session, `claude mcp add` alone won't do it for these). Once
one shows as connected, confirm its exact registered name with
`claude mcp get "claude.ai <Name>"` — see the gotcha in
SARAH_PROJECT_STATE.md — and add it to `CONNECTOR_SERVERS` in
`sarah_agent.py`. Restart the agent to pick up changes. **Slack, Linear, and
Figma are not connected yet** — same process, still pending.

## Unattended check-ins

Sarah doesn't only act when spoken to. Every few hours (`UNATTENDED_INTERVAL_HOURS`
in `sarah_agent.py`, only during `UNATTENDED_WINDOW` local hours) she runs a
check-in on her own: delegates to the `connector` specialist to skim Gmail,
Calendar, Drive, Notion, Xero, and Canva for anything time-sensitive, and
drafts a line in **`sarah_pending.md`** for anything that looks like it needs
a decision from Adeel — she never sends/creates/books/pays during one of
these, only reads and drafts. Next time a browser attaches, she says how many
things are waiting; ask "what's pending" and she reads the file and walks you
through it. Approve one and she carries it out for real, live, the same way
any other action would confirm.

This reuses the existing permission system rather than adding a new one:
`can_use_tool` still fails closed with no browser attached, so even if the
model ever tried to act during a check-in anyway, it would be denied exactly
like any other unattended attempt — the "never act while unattended"
instruction in `UNATTENDED_PROMPT` is belt-and-suspenders, not what actually
enforces it.

## Permissions

Sarah edits freely inside her **named folders** — `BRAIN\Sarah` and the APEX
repo — and asks before anything else. Two things always prompt regardless of
location: paths outside those folders, and destructive or outward-facing shell
commands (`rm -rf`, force push, hard reset, deploy, pipe-to-shell, shutdown).
Reads are never gated. An unrecognised tool prompts the first time.

**Connectors follow the same idea, split by looking vs acting.** Reading your
inbox, calendar, Drive or Notion is free — an assistant that needs permission to
look at your own calendar is useless. Anything that sends, replies, creates,
deletes, shares, publishes, books or pays **always** confirms and never earns
standing approval, however many times you've approved it before. Anything whose
name doesn't clearly say which it is also confirms.

The rules live in `_decide()` in `sarah_agent.py`; to add a workspace, add it to
`WORKSPACES`. Prompts appear in the avatar and are answered by voice or click.
With no browser attached the answer is **no** — it fails closed.

Note the honest limit: shell commands are only heuristically inspected. A
command that hides a path behind a variable or substitution can slip the
location check, which is why the destructive-pattern list is separate and
absolute.
- **Sarah.url / *.ico** — desktop shortcut + icon.

## Run
1. `pythonw sarah_server.py` (or double-click `run_sarah_server.vbs`)
2. Open `http://127.0.0.1:8765/`

## Setup / dependencies
See `SETUP.md` and `requirements.txt`. The Vosk speech model (`model/`,
`model.zip`) is not committed — re-download per SETUP.

## Claude Projects

Your claude.ai Projects are the nodes orbiting the core (they used to be
decorative labels: Strategist, Researcher, Culture…). Hover to highlight and see
the full name, click to open.

Managed in **Settings ⚙ → Claude Projects**: the list itself is editable text,
with Add / Import / All-projects buttons. Voice works too — "open my *name*
project", "open project *name*", "list my projects".

The right-rail panel that used to mirror this list is hidden, since the
constellation replaced it. It's still in the DOM — flip `display:none` on
`.rail-right` to bring it (and Active Tasks) back.

**Amber vs cyan**: amber means Sarah knows the project's name but has no
claude.ai link for it yet, so clicking or asking for it opens your projects list
instead of jumping straight in. **Import** attaches the real links and they turn
cyan. Matching is by name, so imported links land on the existing entries rather
than duplicating them.

Anthropic publishes no API that enumerates claude.ai Projects — they live behind
the claude.ai web session, which this page (origin `127.0.0.1:8765`) cannot read
cross-origin. So the list is stored locally in `config.claudeProjects` as
`Name | URL` lines, editable in Settings ⚙. **Import** copies a one-line snippet
to run in the console of a logged-in claude.ai tab; it reads the project links
off the page and gives you the lines to paste back. Adding a project on
claude.ai means re-importing — the list does not self-sync.

## API keys
Keys and the GitHub token live in the browser's localStorage (Settings ⚙),
never in these files. Nothing here contains secrets.
