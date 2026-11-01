# Sarah — Project State (read this first)

This file is the persistent memory for the Sarah project. A new Claude/Cowork
session has no memory of past conversations — if you're picking this project
back up, read this file fully before doing anything else. Keep it updated as
things change; treat it as the single source of truth for "what's already
built" so work doesn't get redone or contradicted.

## What Sarah is

Adeel's personal, always-on JARVIS-style executive assistant and companion.
Three parts, loosely connected:

1. **The avatar** — `BRAIN\Sarah\sarah-avatar-ui.html` (moved into the
   Sarah folder so the repo and the live-served file are the same; served at
   http://127.0.0.1:8765/), a standalone browser page
   with voice in/out AND a typed composer (with image/doc attach), a glowing
   cyan halo-core visual with 10 labeled specialist-agent nodes orbiting it
   (APEX-inspired look), and a direct chat connection to Claude or ChatGPT
   (user's own API key).
2. **The background services** — `BRAIN\Sarah\`, a local Python server +
   wake-word listener that make the avatar reachable by voice/icon without
   opening Claude, and proxy the OpenAI call server-side.
3. **OpenJarvis** — `BRAIN\OpenJarvis\`, a separately-installed open-source
   agent framework (native Windows install) with its own persona files for
   the 8 specialist agents that need real tool access (inbox, calendar,
   research, etc.), run via the `jarvis` CLI.

Brand name is **"Sarah"** (renamed from an earlier "BRAIN" placeholder name
— the folder is still physically called BRAIN, that's just the directory,
not the assistant's name).

## The avatar — BRAIN\sarah-avatar-ui.html

Single self-contained HTML file, Canvas2D rendering (no Three.js). Current
capabilities:

- **Visual**: central glowing cyan halo/ring core (not the earlier "JARVIS
  HUD dashboard" look), with labeled nodes on connector lines orbiting it.
  State machine: idle/listening/thinking/speaking/acting/warning, driving
  color and pulse.
  - **2026-08-07: the orbit nodes are now the real Claude Projects.** They
    used to be 10 hard-coded decorative labels (Strategist, Researcher, Chief
    of Staff, Finance, Editor, Memory, Sales, Marketing, Design, Culture) from
    the APEX reference. `const AGENTS` is GONE — don't reintroduce it. Nodes
    are built by `rebuildOrbit()` from `getProjects()`, the same list behind
    the panel and the voice commands.
- **Voice**: Web Speech API — `SpeechRecognition` for STT, `speechSynthesis`
  for TTS. Tap-mic-to-talk, plus:
  - **In-page wake word**: continuously listens for "Sarah" while idle
    (fuzzy-matched against mishearings: sarah/ren cho/wren cho/ren show/
    rancho/renshaw) and auto-starts listening when heard, with a spoken
    "Yes?" ack.
  - **Conversational follow-up**: after Sarah replies, it reopens the mic
    briefly for a follow-up instead of requiring "Sarah" again each turn;
    falls back to wake-word mode after a silence timeout.
- **AI provider**: Settings (gear icon) lets you pick **Claude (Anthropic)**
  or **ChatGPT (OpenAI)**, each with its own saved key. Claude calls
  `api.anthropic.com` directly from the browser (uses Anthropic's
  browser-access header). **OpenAI cannot be called directly from a
  browser (no CORS support)** — it's proxied through the local Sarah
  server instead (`POST /proxy/openai`, see below). OpenAI model is
  configurable in Settings (default `gpt-4o-mini`) since OpenAI projects
  can restrict which models a key may use.
- **Personality**: `DEFAULT_SYSTEM_PROMPT` frames Sarah as a warm,
  mood-aware companion, not just a task-taker — checks in on how Adeel's
  doing, references memory naturally, keeps replies short since they're
  read aloud (1–3 sentences unless asked for more).
- **Persistent memory**:
  - Last ~30 messages of conversation persist in `localStorage`
    (`sarah_config_v1` key) and replay into the transcript on reload —
    continuity across sessions instead of starting blank.
  - `config.memoryNotes` — a free-text running list of durable facts,
    editable in Settings under "What Sarah Remembers," injected into
    every system prompt. Say **"remember that ___"** anytime (handled
    locally, no AI call) and it's appended permanently.
  - "Clear memory & history" button in Settings wipes both.
- **Real actions (not just advice)**: the AI is instructed (via
  `ACTION_CAPABILITY_PROMPT` in `buildSystemPrompt()`) that it can act, not
  just explain. It ends its reply with a hidden directive line like
  `ACTION: open youtube` / `ACTION: search <query>` / `ACTION: play <query>`
  when the user's asking for that; `extractAndRunAction()` parses and
  executes it (opens a real browser tab via `window.open`) and strips the
  directive before the reply is shown/spoken. There's also a fast local
  regex path (`tryHandleAction`) for the most common obvious phrasings that
  skips the AI call entirely (zero cost/latency).
  - **Known gotcha**: Chrome blocks `window.open()` calls that originate
    from async callbacks (voice recognition isn't a "direct click"), so
    the very first action may get silently blocked. Fix is one-time: click
    the blocked-popup icon in the address bar → "Always allow pop-ups and
    redirects from http://127.0.0.1:8765" → never blocked again. Same
    pattern as the mic-permission fix below.

## Team of subagents (2026-08-07, third pass)

Adeel asked to integrate a GitHub repo (TencentCloud/TencentDB-Agent-Memory,
`feat/server_team` branch) for "team agent structure" + token optimization.
**Evaluated it, didn't adopt it — deliberately, not by oversight.** It's a
standalone memory-hub microservice suite: Node.js, Docker, its own database,
vector search, a proxy, a web UI on :8125, its own LLM API key. It's built for
an org sharing memory across multiple people's agents; token optimization
isn't even claimed directly, just "retrieve less by retrieving right." Wrong
shape for a single-user always-on assistant, and a lot of new attack surface
to stand up on a machine that already holds real credentials.

What Adeel actually described — "the appropriate agent works, others rest
silent" — is a **native, already-installed** feature: `claude-agent-sdk`
subagents (`AgentDefinition` + `agents=` on `ClaudeAgentOptions`). No new
service, no new dependency. Implemented as `TEAM` in sarah_agent.py:

- **`researcher`** — Read/Grep/Glob/WebSearch/WebFetch, model `sonnet`. Lookups,
  documentation, exploring unfamiliar code. No write/execute tools at all.
- **`coder`** — Read/Edit/Write/Bash/Glob/Grep, model `opus`. File and code
  work in the two workspaces.
- **`connector`** — Read/Grep/Glob + `mcpServers=CONNECTOR_SERVERS`, model
  `opus`, `disallowedTools=[Bash, Write, Edit, NotebookEdit, MultiEdit]`
  explicitly removed. Gmail/Calendar/Drive/Notion/Xero/Canva work.
  - **Bug I introduced and caught before shipping**: first draft left `tools`
    unset on this one, which per the SDK docs means "inherit everything" —
    so it also had Bash/Write/Edit despite existing purely to read and
    report. Fixed with `disallowedTools`. Caught by re-reading my own design
    reasoning against what I'd actually written, not by an external review —
    worth remembering that pattern.
- **Delegation visibility**: `_decide()` special-cases `tool in ("Agent",
  "Task")` — SDK renamed the tool at Code v2.1.63, current installed
  claude-agent-sdk (0.2.132) emits "Agent"; "Task" kept for back-compat, both
  tested. Delegation is always free (never confirms — nothing to protect by
  gating the handoff itself), but gets a real summary (`"→ coder agent: ..."`)
  instead of the usual silent `""`, so the team is visible in the transcript:
  who picked up the task, and by omission, who didn't.
- **`CONNECTOR_SERVERS`**: the account-managed MCP connectors (Gmail,
  Calendar, Drive, Notion, Xero, Canva) are NOT in any local config file —
  fetched from claude.ai at session auth. Their registered names carry a
  literal `"claude.ai "` prefix and spaces (confirmed via
  `claude mcp get "claude.ai Gmail"`), not the bare service name. Get this
  wrong and `mcpServers` silently references nothing.

### The test that actually mattered: does delegation bypass the permission gate?

`can_use_tool` is one callback registered once per session — same code path
regardless of whether the main thread or a subagent issues the tool call, per
the SDK docs (subagent messages carry `parent_tool_use_id` but flow through
the same session). **Verified live, not just inferred from docs**, because
this is the one place a design mistake would be a real security regression:

1. First attempt — told the coder subagent to write outside the workspace —
   the subagent talked itself out of trying (no `ASK` line logged, no tool
   call fired). That's the model being well-aligned to its prompt's
   confirmation reminder, not proof of the code-level gate.
2. Loaded the prompt with meta-instructions to force it ("just call the tool,
   don't reason about the outcome") — it refused *harder*, correctly reasoning
   that a relayed instruction isn't a verifiable confirmation from Adeel. Also
   not what I was testing for, but a good sign about the model.
3. Plain, unloaded request ("create this file") — the subagent attempted
   `Write` naturally as part of doing the task. **This time**: real `ASK
   Write` line in the log, real modal in the browser tied to a real pending
   permission id, declined it, file was never created.

**Lesson for future-Claude**: if you need to prove a security boundary holds
under a new code path, don't ask the model to try to trigger it — a
well-aligned model will often reason its way out of an attempt before the
code path is ever exercised, which looks like success but proves nothing.
Ask for the underlying task plainly and let the tool call happen naturally.

## Unattended check-ins (2026-08-09) — connectors with their own initiative

Adeel asked for the connectors to "act automatically and have their own
brain, jump in when needed" rather than only responding when spoken to.
Clarified first (this was ambiguous enough to matter): he meant unattended
background checks, not just faster in-conversation delegation — and for
anything that would normally require his confirmation (send, book, pay), it
should be **queued, never auto-sent**, across all six live connectors plus
Slack/Linear/Figma once those are authorized.

Built as an internal asyncio loop in `sarah_agent.py`, not a new service or
Windows Task Scheduler entry — the agent process is already always-on
(autostart, see below), so a timer inside it is the whole mechanism:

- `unattended_loop()` fires `Sarah.unattended_check()` every
  `UNATTENDED_INTERVAL_HOURS` (default 4), only inside `UNATTENDED_WINDOW`
  (7am–10pm local) so nothing runs (and costs tokens) overnight for no
  reason. Skips if she's already mid-turn with Adeel (`self.busy`).
- It's just `handle_utterance(UNATTENDED_PROMPT)` — the exact same code path
  as a real turn, not a parallel one — so it gets the same context
  injection, same session, same delegation to the `connector` specialist.
  `UNATTENDED_PROMPT` tells her plainly this is her own timer firing, not
  Adeel, and to only read + draft, never act.
- **Why drafting to a file beats trying to queue the actual tool call**: an
  approved-later replay would mean holding a pending permission decision
  across process restarts and somehow re-invoking the exact same tool call
  afterward — real complexity for something the SDK isn't shaped for. Simpler
  and just as safe: unattended mode never attempts the mutating call at all.
  She writes what she'd do to `sarah_pending.md` in prose; when Adeel
  approves it later, she does the real thing live, the normal way, with a
  normal confirmation in front of it.
- **This does not add a second permission system.** Even if the model ever
  ignored the prompt and tried to act anyway, `can_use_tool` still fails
  closed with no browser attached (existing behavior, unchanged) — the
  "don't try" instruction saves a wasted turn, it isn't the actual boundary.
- `sarah_pending.md` mirrors `sarah_memory.md`'s shape (`pending_items()`
  reads its "- " lines, same pattern as `memory_facts()`). On a fresh browser
  attach, if the file has entries, she sends one proactive line ("N things
  might need your OK") before Adeel says anything — the one place this
  feature is visible without asking for it.
- **Connector scope**: all six already-live connectors (Gmail, Calendar,
  Drive, Notion, Xero, Canva) plus Slack/Linear/Figma once those exist.
  Confirmed via `claude mcp list` on this machine (2026-08-08) that Slack/
  Linear/Figma are **not yet connected** — they need Adeel to authorize each
  one himself at claude.ai → Settings → Connectors (interactive OAuth, can't
  be done from an unattended process or this session). `CONNECTOR_SERVERS`
  has a comment with the exact next step once he does; nothing else in the
  unattended-check code needs to change when they're added.
- Not yet verified live end-to-end (needs the interval to actually elapse
  with something real waiting in an inbox) — built and reviewed, not watched
  run.

## THE BRAIN MOVED (2026-08-07) — read this before touching the avatar

Sarah's brain is **no longer the browser page**. It is `sarah_agent.py`, a local
process running the **Claude Agent SDK** (`claude-agent-sdk`, installed; needs
the `claude` CLI on PATH, which it spawns). The avatar page is now a client.

**Why**: a browser page can't spawn a process, hold an OAuth refresh token, read
a repo off disk, or run git — so every capability needed a hand-written proxy in
`sarah_server.py` (~40 lines each: `_proxy_openai`, `_proxy_github`). That does
not scale to "everything connected at the back end". Don't add a third proxy;
add a tool or an MCP server to the agent instead.

- **Transport**: WebSocket `ws://127.0.0.1:8766`. Browser→agent: `user`,
  `permission_result`, `interrupt`. Agent→browser: `hello`, `status`, `text`,
  `tool`, `permission`, `done`, `error`.
- **Workspaces** (`WORKSPACES` in sarah_agent.py): `BRAIN\Sarah` and
  `C:\Users\asid3\Documents\APEX\APEX_Website\APEX`. Passed as `cwd` +
  `add_dirs`. Adding a project = adding a path here.
- **Permission policy** — Adeel chose "free within named folders": reads always
  allowed; writes free inside workspaces, confirmed outside; Bash confirmed if
  it matches `DESTRUCTIVE` or mentions a path outside the workspaces; unknown
  tools (incl. future MCP) confirmed. **Fails closed** — no browser attached
  means denied. 17 policy cases are unit-tested, including `..` traversal out of
  a workspace (`in_workspace` resolves before comparing).
  - **Known limit, stated deliberately**: `paths_in_command()` is a crude regex
    over a shell string. Variables/substitutions can hide a path. That's why the
    destructive-pattern list is separate and location-independent.
- **The old in-page brain is still there and still works** — `sendToBrain()`
  routes to the agent only when the socket is up, else falls back to direct
  Claude/OpenAI. Don't delete it; it's what keeps the avatar alive when the
  agent is down. Attachments still take the fallback path (the agent reads files
  by path, image paste isn't wired to it yet).
- **Autostart**: `Sarah Agent.lnk` in `shell:startup`, alongside Server and
  Listener. Three `pythonw.exe` now — filter on CommandLine, never
  `taskkill /IM pythonw.exe`.
- Logs to `sarah_agent.log`. Model is `claude-opus-5`.
- **Memory bridge (2026-08-07, second pass)** — the browser used to hold memory
  in localStorage where the agent could never see it, so "remember that..." went
  nowhere useful and she felt like two assistants. Now `sarah_memory.md` in the
  Sarah folder is the single source of truth: loaded into the system prompt at
  startup, re-sent mid-turn via `_with_context()` when it changes (the system
  prompt is fixed once the client connects, so this is the only way an in-session
  update reaches her without a restart). The page's old notes merge in once on
  connect (`merge_browser_memory`, dedupes, so it's a no-op after the first
  run), and the page's Settings box now *mirrors* the file via the `memory`
  event. `tryHandleAction`'s local "remember that" branch deliberately returns
  null when the agent is up — handling it locally is what split memory in two.
- **Sessions survive restarts** — `session_id` from ResultMessage is saved to
  `.sarah_session` and passed as `resume`. A stale id falls back to a fresh
  session instead of failing startup. Delete the file to force a blank thread.
- **Connectors were already there.** MCP servers configured via `claude mcp add`
  are inherited by the SDK **regardless of `setting_sources`** — no wiring
  needed. Verified live: Gmail, Google Calendar, Google Drive, Notion, Xero,
  Canva. `strict_mcp_config=True` would cut them off; don't set it.
  - MCP permission split (`MCP_READ` / `MCP_NEVER_AUTO` in `_decide`): reads
    free, anything that sends/creates/deletes/shares/books/pays always confirms
    and never gets standing approval. Ambiguous names (`get_or_create_page`)
    confirm — the acting-verb check runs first on purpose.
- **Two bugs found and fixed while testing this pass**, both worth remembering:
  1. *Attach/detach fight loop.* The agent kept one `self.ws` and closed the
     previous client on connect; with two tabs open, each attach killed the
     other, whose auto-reconnect killed the first — once per second, forever.
     Now `self.clients` is a set and messages broadcast. Multiple faces are
     supported deliberately.
  2. *Stacked sockets → everything spoken twice.* A queued reconnect timer plus
     a live reconnect left two WebSockets open in one page. `connectAgent()` now
     bails if a socket is OPEN/CONNECTING and `scheduleAgentRetry()` keeps at
     most one timer in flight.
- **Verified working 2026-08-07**: read a real APEX file and answered correctly
  ("posts to send-booking.php"); a Desktop write correctly prompted, was
  declined, and the file was never created.

## BRAIN\Sarah\ — background services

- **`sarah_server.py`** — local Python HTTP server on
  `http://127.0.0.1:8765`, serves the `BRAIN\Sarah` folder (BASE_DIR was
  changed from BRAIN root to the Sarah folder) so the avatar has a stable
  origin, and proxies both OpenAI chat calls (`POST /proxy/openai`) and GitHub
  REST calls (`POST /proxy/github`) server-side (bypasses their lack of CORS).
  Forces Cache-Control: no-store on every response. Started
  via `run_sarah_server.vbs` (silent, no console window).
  - **Root serves the avatar (2026-08-07)**: `send_head()` rewrites `/` and
    `/index.html` → `/sarah-avatar-ui.html`, so the address bar reads just
    `127.0.0.1:8765` and the tab reads **SARAH**. Deliberately a rewrite, not
    a 302 — a redirect would put the long filename back in the address bar,
    defeating the point. There's no `index.html` in the folder, so without
    this `/` would serve a directory listing. All launchers (`Sarah.url`,
    `Sarah-Launch.vbs`, `Sarah.command`, `sarah_listener.py`) now point at the
    bare root; the long `/sarah-avatar-ui.html` URL still works.
  - **Why a local server exists at all**: Chrome does NOT reliably
    remember microphone permission for `file://` pages — it re-prompts
    every time. Serving over `http://127.0.0.1` fixed that permanently
    (one-time mic permission grant, then it sticks).
- **`sarah_listener.py`** — offline, free wake-word listener using
  **Vosk** (small English model in `Sarah\model\`, downloaded once,
  ~40MB) + `sounddevice`. Listens system-wide (even with no browser open)
  for "Sarah" (with the same fuzzy mishearing list as the in-page wake
  word) and opens `http://127.0.0.1:8765/` in the
  default browser when heard. Started via `run_sarah_listener.vbs`.
  Logs to `sarah_listener.log`.
- **Desktop icon (updated 2026-08-07)**: `Desktop\SARAH.lnk`, a `.lnk`
  targeting **`Sarah-Launch.vbs`** — NOT `Sarah.url` and NOT the .html.
  Going through the launcher matters: it starts the server if it isn't
  already up, then opens the avatar, so a cold double-click works instead
  of showing a connection-refused page. Icon is `Sarah2.ico` (`Sarah.ico`
  is a byte-identical copy; the duplicate exists only to bust Windows'
  icon cache). `Sarah.url` is still in the repo and still works.
- **Autostart**: server + listener shortcuts in `shell:startup`, launched
  silently at login. Both run as `pythonw.exe` (no console window) —
  **careful**: `taskkill /F /IM pythonw.exe` kills BOTH indiscriminately
  since they share a process name; to restart just one, filter on
  CommandLine (`Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'"`
  then match `*sarah_server.py*`).
  - **2026-08-07: these were silently dead.** The rebrand left the Startup
    folder holding `Rencho Listener.lnk` / `Rencho Server.lnk` pointing at
    `run_rencho_listener.vbs` and a `BRAIN\Rencho\` folder that no longer
    existed, so nothing had auto-started since. Windows gives NO error for a
    broken startup shortcut — it just doesn't run. Replaced with
    `Sarah Server.lnk` / `Sarah Listener.lnk`. **If the project is ever
    renamed or moved again, re-run SETUP.md §4** — .lnk files store absolute
    paths and will break the same way. Same trap bit `Desktop\Rencho-GITHUB.lnk`.
- **Icon art**: `quiet_frequency_icon.png` + `quiet-frequency-philosophy.md`
  — an original minimalist icon (rounded head/shoulders silhouette,
  glowing cyan "ear" point with radiating sound-wave arcs on a dark
  field), built with the `canvas-design` skill after the user wanted a
  "3D model style" icon but no image-generation tool was available in
  this environment — went with an illustrated/vector-style alternative
  instead, which the user approved.
- **Setup docs**: `SETUP.md` has the full one-time PowerShell command list
  (pip installs, Vosk model download, shortcut creation, autostart). Some
  scratch preview files (`_preview1-6.png`, `_sanity_check.png`) were left
  behind during icon iteration — harmless clutter, not yet cleaned up
  (user hasn't confirmed deletion; files in the connected BRAIN folder
  need `allow_cowork_file_delete` approval to remove).

## BRAIN\OpenJarvis\ — agent framework

- Installed natively on Windows via the official installer
  (`deploy/windows/install.ps1`), with `$env:OPENJARVIS_HOME` pointed at
  `BRAIN\OpenJarvis` so all runtime state (config, memory index, personas)
  lives inside BRAIN, not scattered in `~/.openjarvis`.
- **`SOUL.md`** (root persona) — identifies as Sarah, lists all 10
  specialists and how to invoke them (`jarvis ask --persona <name> "..."`).
- **`personas\<name>\SOUL.md`** — one file per specialist, written for:
  strategist, researcher (paired with the built-in `deep_research` agent),
  chief-of-staff (paired with `morning_digest`, needs `jarvis connect
  gdrive` for real inbox/calendar data), finance (scaffolded, no live data
  source yet, hard rule: never execute trades/transfers), editor, sales
  (scaffolded, no CRM yet), marketing, culture. Each has explicit
  BOUNDARIES sections (never send/publish without approval, etc.) — this
  pattern should be followed for any new persona added later.
- **Memory** and **Design** are deliberately *not* OpenJarvis personas:
  - **Memory** = OpenJarvis's own RAG memory-index feature over
    `BRAIN\OpenJarvis\memory-source\adeel-preferences.md` (re-run
    `jarvis memory index` after editing that file).
  - **Design** = routed through *this Cowork session's* Canva connector
    (already authorized, confirmed working — two brand kits including
    "Remedy Pills Pharmacy"), NOT wired into OpenJarvis directly, because
    Canva's MCP requires a redirect-URI allowlist approval that a small
    self-hosted OpenJarvis instance won't clear (major platforms like
    Claude/ChatGPT are pre-approved; OpenJarvis isn't).
- **Not yet confirmed run by the user**: `jarvis init`, `jarvis memory
  index`, testing any of the 8 personas, or activating `deep_research` /
  `morning_digest` end-to-end. Guidance was given; no confirmation
  received back yet as of this writing.

## Business/personal context (folded into memory-source + system prompts)

- Adeel runs a pharmacy ("Remedy Pills Pharmacy" — confirmed via a live
  Canva brand-kit lookup this session).
- Tracks a trading watchlist (relevant to the Finance persona).
- Maintains a website (relevant to Marketing/Design personas).
- Windows PC — never assume macOS/Linux-only tooling works without
  confirming native Windows support first.
- Timezone: America/New_York.

## Standing rules established this project (apply everywhere, not just GitHub)

- **Draft/confirm before acting**, always, for anything with real-world
  effect — sending messages, posting, publishing, financial actions,
  and (newly) code changes. This was explicitly re-affirmed when Adeel
  asked for "full access, do all on my command" for GitHub: the answer
  was to keep a lightweight voice confirmation step before any actual
  write, not blanket unsupervised execution. Apply this same posture to
  any future integration, regardless of what "full access" is requested.
- **Never** enter passwords/API keys/payment details on Adeel's behalf.
- **Never** send email/messages or make purchases without explicit
  per-action confirmation (approvals don't generalize to future actions).
- Prefer local-first, zero-cost tooling where practical; flag anything
  that costs money before setting it up (e.g., OpenAI API usage is
  pay-as-you-go, flagged explicitly when ChatGPT was wired in).
- Communication style Adeel has asked for repeatedly: concise, direct,
  ask 2–3 short clarifying questions before starting multi-step work,
  don't over-research before asking.

## Current state — what's built and live (updated 2026-07-25)

### GitHub control (DONE — this was the big open thread)
- Sarah has real read/write GitHub access via **native LLM tool-calling**
  (Anthropic `tools`/`tool_use`, OpenAI `tools`/`tool_calls`) — a `github_api`
  tool the model calls directly. This replaced an earlier free-text
  `ACTION: github {...}` marker that proved unreliable (the model kept
  forgetting to emit the line). open/search/play still use the ACTION-marker
  path; only GitHub moved to tool-calling.
- Server side: `POST /proxy/github` in `sarah_server.py` — generic
  method+path+body forwarder to api.github.com, adds the PAT server-side
  (mirrors the OpenAI proxy). The PAT lives only in the browser's localStorage
  (Settings → "GitHub Personal Access Token"), never in a file.
- Safety honored: GET runs immediately; POST/PUT/PATCH/DELETE stage a
  `pendingGithubAction` and require a spoken/typed "yes" before firing.

### Sarah avatar — recent changes
- **Composer** ("Talk to Sarah" panel, replaced Demo State Controls): type
  instructions (Enter to send), plus **paste/attach images and documents**.
  Images downscale→base64 to the vision model; PDFs (pdf.js CDN) and text files
  are read and passed as text. Attachments never persisted. Typed input runs the
  same pipeline as voice (actions, GitHub tool, confirm-before-write). Vision
  needs a vision model (Claude default fine; OpenAI use gpt-4o/gpt-4o-mini).
- Header renamed to "SARAH"; right-side demo panels (Active Tasks/Status/
  Session Memory) hidden (display:none, elements kept so JS refs don't break).
- **Claude Projects (2026-08-07)** — the constellation is the projects UI; the
  **whole right rail is `display:none`** (Adeel asked for it hidden once the
  orbit replaced it). All four panels there are kept in the DOM, NOT deleted,
  because live code still writes into them: `renderProjects()` → `#projectList`,
  `createTask()` → `#taskList`, `updateConnectionStat()` → `#connectionStat`.
  Deleting any of them breaks JS. Un-hiding is a one-word change on `.rail-right`
  (but Status/Session Memory have their own `display:none` — their numbers are
  still hard-coded mock values).
  - **Add / Import / All-projects buttons live in Settings ⚙**, moved out of the
    hidden panel so they stay reachable. They must have exactly one instance —
    don't re-add copies to the panel or `getElementById` will bind only the first.
  - `renderProjects()` **re-syncs `projectsInput.value` from config on every
    call.** Non-obvious but load-bearing: Add/Import now run from inside the open
    Settings modal, and Save does `config.claudeProjects = projectsInput.value`,
    so a stale textarea would silently wipe a just-completed import.
  - **There is no Anthropic API that lists claude.ai Projects.** They're behind
    the claude.ai web session; the avatar page (origin 127.0.0.1:8765) can't
    read that cross-origin, and proxying it would mean storing the user's
    claude.ai session cookie — rejected. Don't go looking for that endpoint again.
  - List lives in `config.claudeProjects` as `Name | URL` lines (hand-editable
    in Settings ⚙). `parseProjects` / `projectsToText` / `getProjects` /
    `setProjects` / `renderProjects` / `findProject`.
  - **Import** button copies a one-liner that scrapes `a[href*="/project/"]` in a
    logged-in claude.ai tab and dedupes by URL; user pastes the result back into
    a prompt(). It merges by URL, so re-importing is safe. Not self-syncing.
  - Voice, all handled locally in `tryHandleAction` with no AI call: "open my X
    project", "open project X", "open X on claude", "open my claude projects",
    "list my projects". Placed BEFORE the generic `open <word>` site handler so a
    project named e.g. "Drive" beats the ACTION_SITES bookmark; the generic
    handler also tries `findProject` before falling back to guessing `X.com`.
  - `findProject` matches exact → startsWith → substring → all-words, so speech
    mishearings ("sara assistant" → "Sarah Assistant") still land.
  - Project *names* are injected into `buildSystemPrompt` so the brain knows what
    he's referring to; opening is local, the model does nothing for it.
  - **Entries may have no URL.** `parseProjects` accepts "Name | URL", a bare
    URL, or a bare Name. A name-only entry still gets an orbit node, a panel
    row and a voice command — it just opens `claude.ai/projects` and says it
    isn't linked (`speakOpenProject`). `config.claudeProjects` is seeded from
    `DEFAULT_PROJECTS` (Adeel's 10 real project names, taken from a screenshot)
    **only when the key is absent** — an empty string means he deleted them all
    and must not be re-seeded on reload.
  - Import merges **by normalized name** (`normName`) into existing unlinked
    entries so links attach in place and keep their orbit position, and only
    appends when there's no name match. Re-importing is idempotent.
  - **Orbit click hit-testing**: `draw()` records `orbitHits` in SCREEN space
    every frame (`cx + nx * hudZoom`), and `orbitHitAt()` tests against those.
    Do NOT recompute the geometry in the click handler — the nodes rotate
    (`constellationDrift`), wobble, and zoom (`hudZoom`), so a second
    computation drifts out of sync with what's actually painted. Boxes are
    scanned in reverse so the label painted on top wins an overlap.
  - Labels truncate at `ORBIT_MAX_LABEL` (22 chars) or they overflow into the
    side rails; the full name goes in `canvas.title` on hover. Past 10 projects
    the nodes alternate between two radii (`node.ring`) to limit collisions.
  - **Testing gotcha**: in the Claude Code browser pane `innerWidth` is 0 and
    the page never composites, so `requestAnimationFrame` never fires and
    `orbitHits` stays empty. To test, `Object.defineProperty(window,
    'innerWidth', {value:1280})`, call `resizeAll()`, then call
    `animate(performance.now())` once by hand to force a frame.

### GitHub sync of the Sarah project itself
- `BRAIN\Sarah` is a git repo pushed to **github.com/AdeelSiddiqui38/Rancho**
  (private). Kept in sync with **`Sarah-Sync.bat`** (double-click → add/commit/
  push). Git runs natively on the PC (Git Bash/PowerShell); the sandbox CANNOT
  run git on the FUSE mount (lock files can't be unlinked). `.gitignore` excludes
  the Vosk model, logs, icon scratch PNGs. After Claude edits Sarah files, user
  runs Sarah-Sync.bat and reloads the page.

## APEX Physiotherapy website — Sarah-controlled (NEW, in progress)

Goal: Sarah controls the APEX Physiotherapy & Wellness Clinic website — repo
AND live site.

- **Business**: Apex Physio & Wellness Clinic, Unit 150, 246 Nolanridge Crescent
  NW, Calgary, Alberta. Phone/email TBD. Independent from 1physioandmobility.ca
  (same staff). Logo drafted in Canva.
- **Repo**: github.com/AdeelSiddiqui38/ApexPhysio (now **PUBLIC**). Local clone at
  `C:\Users\asid3\Documents\APEX\APEX_Website\APEX` (already git-linked, on main).
  Added `.gitignore` (ignores .gstack/) and **`APEX-Sync.bat`** (one-click push) —
  these two are new & not yet pushed.
- **Site type**: static HTML/CSS/JS. The **deployable site is the `apexphysio/`
  SUBFOLDER** (index.html, booking.js, interactions.js, motion-bg.js,
  gsap-lottie.js, site.css, send-booking.php, assets/, marketing/). Repo ROOT has
  older concept files (website-concept.html etc.) + 23 pages of content in a .docx.
- **Domain**: `apex-physio.ca`, at WHC (Web Hosting Canada), **not active yet**.
  (www.whc.ca is the HOST, not the clinic site — easy point of confusion.)
- **Deployment DECISION**: static + **auto-deploy via Netlify** (NOT GitHub Pages —
  the booking form posts to `send-booking.php`, and Pages can't run PHP). Netlify
  auto-deploys from the repo (keeps Sarah in control via GitHub) and has built-in
  form handling to replace the PHP. Publish directory = `apexphysio`.
- **Original plan (superseded)**: PROJECT_STATUS.md documented WordPress+Elementor
  on WHC — rejected because it isn't practically Sarah-controllable.
- **PAUSED HERE — next steps** when resuming:
  1. Convert the booking form in `apexphysio/index.html` from the PHP handler to
     **Netlify Forms** (add `data-netlify="true"`, drop the `.php` action; retire
     send-booking.php). *Awaiting user's go-ahead to edit.*
  2. User creates a free **Netlify** account, connects it to the ApexPhysio repo,
     publish dir `apexphysio`. *(Asked whether they already have an account —
     unanswered.)*
  3. Point `apex-physio.ca` DNS at Netlify (records to be provided; needs the
     user's WHC/domain login).

## Known gotchas / traps for future-Claude

- **Bash sandbox vs. the BRAIN mount**: bash's view of files under the
  BRAIN mount has repeatedly lagged behind the true state (stale reads,
  wrong line/byte counts). The Read/Edit/Write tools are authoritative;
  don't trust `cat`/`wc`/`grep` over the BRAIN mount for verification —
  always cross-check with Read if something looks off after a bash edit.
- **`git clone` / `rm -rf` directly on the BRAIN FUSE mount fails** with
  "Operation not permitted" on `.git` internals. Clone into a native
  Linux path (e.g. `/tmp/...`) for any read-only inspection instead.
- **Files in the connected BRAIN folder can't be deleted via bash** (same
  "Operation not permitted" issue) — deletions need the
  `allow_cowork_file_delete` tool (asks the user first) or the user doing
  it themselves in Explorer.
- **A regex `.*` with `re.S` (DOTALL) in a find/replace patch will eat the
  rest of a file to EOF** if you're not careful with the match boundary —
  this silently truncated `render_icon.py` twice during icon work and
  wasted real time debugging "why didn't my edit do anything" before the
  root cause was found. Prefer full-file rewrites over clever regex
  patches for anything past a few lines.
- **Windows icon cache is very sticky** — overwriting an `.ico` file in
  place often doesn't refresh the visible icon even after `ie4uinit.exe
  -show`; renaming the file (and updating the `.url`'s `IconFile`) plus an
  Explorer restart is the reliable fix.
- **Computer-use cannot type into Windows Terminal/PowerShell** (UIPI
  restriction) — every OpenJarvis/PowerShell step in this project has had
  to be handed to Adeel as copy-paste commands rather than run directly.
- **This session's outputs/scratch path and the BRAIN path use different
  mount schemes** (Windows paths for Read/Write/Edit tools vs.
  `/sessions/.../mnt/...` for bash) — mixing them up causes "outside
  connected folders" errors. Copy scratch files into the BRAIN mount via
  bash `cp`, then `Read` them via the Windows-style path, to preview
  anything built in the sandbox before it's considered final.

## Sarah Core + Sarah Grid (added 2026-11-01, built from the Mac session)

A second, self-contained stack alongside the avatar/agent above. It does not
replace `sarah_server.py` (8765) or `sarah_agent.py` (8766); it runs on its
own port **8770**.

- **Architecture decided with Adeel:** Sarah is the core; around her a
  **safety shield** (login, vault, approval gate, audit log); around that
  **project slots**. RULE: one project per slot, and **Adeel names every
  project and defines what belongs in it**. Not every request becomes a
  project; unrelated requests are one-offs. Agents per project (Finance,
  Coordinator, Administration, Marketing, Social media, HR) start off and run
  in **draft-only mode** (they prepare, Adeel approves; nothing executes).
- **Look:** TRON-style control room (`sarah-grid.html`), chosen over the
  solar-system and photo/cartoon face experiments.
- **`sarah_core.py`** (stdlib + optional `keyring`): passphrase login
  (scrypt), sessions, lockout, same-origin guard, vault (Keychain /
  Credential Manager or `data/vault.json`), SQLite `data/sarah.db` with
  projects, drafts and audit log, Claude brain (`claude-haiku-5-5`) with
  `create_draft` and `project_status` tools, local keyword fallback, and a
  read-only CRA checklist from `<project>/Finance/Bank Statements/<year>/`.
  Remedy Pills is seeded in slot 1.
- **Launchers:** `Sarah Grid.command` (Mac), `Sarah-Grid.bat` (Windows), then
  open http://127.0.0.1:8770.
- **24/7 home decided: Adeel's TrueNAS SCALE 25.10** (hostname `truenas`,
  10.0.0.110), reached only through **Tailscale**. See `deploy/TRUENAS.md`
  and `deploy/truenas-compose.yaml`. Next step for Adeel: Tailscale MagicDNS
  + HTTPS + auth key, create the `sarah` dataset, install the YAML app.
- Tested in a sandbox only; not yet run on real hardware or with a real key.
- The Mac's local clone is behind GitHub. On the Mac, run
  `git fetch && git reset --hard origin/main` once before working there.

- 2026-11-01: Brain providers. Sarah supports OpenAI (Responses API, `gpt-6.1-terra`, reasoning off, store=false; override `SARAH_OPENAI_MODEL`) and Claude (`claude-haiku-5-5`). Settings: pick provider, paste key into vault, switch with Use OpenAI / Use Claude. Dedicated OpenAI project key funds Sarah from the $8.47 credit.
