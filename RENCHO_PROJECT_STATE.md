# Rencho — Project State (read this first)

This file is the persistent memory for the Rencho project. A new Claude/Cowork
session has no memory of past conversations — if you're picking this project
back up, read this file fully before doing anything else. Keep it updated as
things change; treat it as the single source of truth for "what's already
built" so work doesn't get redone or contradicted.

## What Rencho is

Adeel's personal, always-on JARVIS-style executive assistant and companion.
Three parts, loosely connected:

1. **The avatar** — `BRAIN\jarvis-avatar-ui.html`, a standalone browser page
   with voice in/out, a glowing cyan halo-core visual with 10 labeled
   specialist-agent nodes orbiting it (APEX-inspired look), and a direct
   chat connection to Claude or ChatGPT (user's own API key).
2. **The background services** — `BRAIN\Rencho\`, a local Python server +
   wake-word listener that make the avatar reachable by voice/icon without
   opening Claude, and proxy the OpenAI call server-side.
3. **OpenJarvis** — `BRAIN\OpenJarvis\`, a separately-installed open-source
   agent framework (native Windows install) with its own persona files for
   the 8 specialist agents that need real tool access (inbox, calendar,
   research, etc.), run via the `jarvis` CLI.

Brand name is **"Rencho"** (renamed from an earlier "BRAIN" placeholder name
— the folder is still physically called BRAIN, that's just the directory,
not the assistant's name).

## The avatar — BRAIN\jarvis-avatar-ui.html

Single self-contained HTML file, Canvas2D rendering (no Three.js). Current
capabilities:

- **Visual**: central glowing cyan halo/ring core (not the earlier "JARVIS
  HUD dashboard" look), 10 agent nodes on connector lines around it —
  Strategist, Researcher, Chief of Staff, Finance, Editor, Memory, Sales,
  Marketing, Design, Culture (labels copied verbatim from the "APEX"
  reference Adeel showed). State machine: idle/listening/thinking/
  speaking/acting/warning, driving color and pulse.
- **Voice**: Web Speech API — `SpeechRecognition` for STT, `speechSynthesis`
  for TTS. Tap-mic-to-talk, plus:
  - **In-page wake word**: continuously listens for "Rencho" while idle
    (fuzzy-matched against mishearings: rencho/ren cho/wren cho/ren show/
    rancho/renshaw) and auto-starts listening when heard, with a spoken
    "Yes?" ack.
  - **Conversational follow-up**: after Rencho replies, it reopens the mic
    briefly for a follow-up instead of requiring "Rencho" again each turn;
    falls back to wake-word mode after a silence timeout.
- **AI provider**: Settings (gear icon) lets you pick **Claude (Anthropic)**
  or **ChatGPT (OpenAI)**, each with its own saved key. Claude calls
  `api.anthropic.com` directly from the browser (uses Anthropic's
  browser-access header). **OpenAI cannot be called directly from a
  browser (no CORS support)** — it's proxied through the local Rencho
  server instead (`POST /proxy/openai`, see below). OpenAI model is
  configurable in Settings (default `gpt-4o-mini`) since OpenAI projects
  can restrict which models a key may use.
- **Personality**: `DEFAULT_SYSTEM_PROMPT` frames Rencho as a warm,
  mood-aware companion, not just a task-taker — checks in on how Adeel's
  doing, references memory naturally, keeps replies short since they're
  read aloud (1–3 sentences unless asked for more).
- **Persistent memory**:
  - Last ~30 messages of conversation persist in `localStorage`
    (`brain_config_v1` key) and replay into the transcript on reload —
    continuity across sessions instead of starting blank.
  - `config.memoryNotes` — a free-text running list of durable facts,
    editable in Settings under "What Rencho Remembers," injected into
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

## BRAIN\Rencho\ — background services

- **`rencho_server.py`** — local Python HTTP server on
  `http://127.0.0.1:8765`, serves the whole BRAIN folder (so the avatar has
  a stable origin) and proxies OpenAI chat calls server-side at
  `POST /proxy/openai` (bypasses OpenAI's lack of CORS support). Started
  via `run_rencho_server.vbs` (silent, no console window).
  - **Why a local server exists at all**: Chrome does NOT reliably
    remember microphone permission for `file://` pages — it re-prompts
    every time. Serving over `http://127.0.0.1` fixed that permanently
    (one-time mic permission grant, then it sticks).
- **`rencho_listener.py`** — offline, free wake-word listener using
  **Vosk** (small English model in `Rencho\model\`, downloaded once,
  ~40MB) + `sounddevice`. Listens system-wide (even with no browser open)
  for "Rencho" (with the same fuzzy mishearing list as the in-page wake
  word) and opens `http://127.0.0.1:8765/jarvis-avatar-ui.html` in the
  default browser when heard. Started via `run_rencho_listener.vbs`.
  Logs to `rencho_listener.log`.
- **Desktop icon**: `Rencho.url` (an Internet Shortcut, not a `.lnk`,
  because it needs to open a URL) pointing at the avatar's localhost URL,
  copied to the real Windows Desktop. Custom icon at `Rencho.ico` /
  `Rencho2.ico` (had to rename to bust Windows' aggressive icon-cache;
  `Rencho2.ico` is the one actually referenced by the shortcut now).
- **Autostart**: both the server and the listener have shortcuts in the
  Windows Startup folder (`shell:startup`) so they launch silently at
  login. Both currently running as `pythonw.exe` (no console window) —
  **careful**: `taskkill /F /IM pythonw.exe` kills BOTH indiscriminately
  since they share a process name; if you ever need to restart one, you
  likely need to restart both.
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
- **`SOUL.md`** (root persona) — identifies as Rencho, lists all 10
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

## In progress / not yet built

- **GitHub integration** — most recent open thread. Decisions made so far:
  - Repo scope: **all repos**.
  - Action scope: **everything, including pushing/editing code** (highest
    stakes option Adeel picked).
  - Connection method: Adeel first said "Cowork's GitHub connector," but
    that only works for *me*, in this chat — it can't be reached by the
    standalone avatar. For **voice/Rencho-reachable** GitHub specifically,
    the plan is a **GitHub personal access token wired into
    `rencho_server.py`** (same proxy pattern already used for OpenAI),
    not the Cowork connector, since the connector doesn't extend outside
    this chat session.
  - Safety line already agreed with the user: real write actions (create/
    edit/push) get a quick voice confirmation before executing — this was
    stated as non-negotiable, not just a suggestion.
  - **Nothing has been built yet for this** — no token setup, no
    `/proxy/github`-style endpoint, no persona/action wiring. Next step
    when resuming: have Adeel generate a GitHub PAT (scoped to repo
    read/write), add a `/proxy/github` endpoint to `rencho_server.py`
    mirroring the OpenAI proxy's structure, extend `ACTION_CAPABILITY_PROMPT`
    / `extractAndRunAction()` in the avatar to cover GitHub verbs, and
    build in the confirm-before-write step (e.g., a pending-action
    variable that requires a spoken "yes" before the destructive call
    actually fires).

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
