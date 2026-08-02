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
   http://127.0.0.1:8765/sarah-avatar-ui.html), a standalone browser page
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
  HUD dashboard" look), 10 agent nodes on connector lines around it —
  Strategist, Researcher, Chief of Staff, Finance, Editor, Memory, Sales,
  Marketing, Design, Culture (labels copied verbatim from the "APEX"
  reference Adeel showed). State machine: idle/listening/thinking/
  speaking/acting/warning, driving color and pulse.
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

## BRAIN\Sarah\ — background services

- **`sarah_server.py`** — local Python HTTP server on
  `http://127.0.0.1:8765`, serves the `BRAIN\Sarah` folder (BASE_DIR was
  changed from BRAIN root to the Sarah folder) so the avatar has a stable
  origin, and proxies both OpenAI chat calls (`POST /proxy/openai`) and GitHub
  REST calls (`POST /proxy/github`) server-side (bypasses their lack of CORS).
  Forces Cache-Control: no-store on every response. Started
  via `run_sarah_server.vbs` (silent, no console window).
  - **Why a local server exists at all**: Chrome does NOT reliably
    remember microphone permission for `file://` pages — it re-prompts
    every time. Serving over `http://127.0.0.1` fixed that permanently
    (one-time mic permission grant, then it sticks).
- **`sarah_listener.py`** — offline, free wake-word listener using
  **Vosk** (small English model in `Sarah\model\`, downloaded once,
  ~40MB) + `sounddevice`. Listens system-wide (even with no browser open)
  for "Sarah" (with the same fuzzy mishearing list as the in-page wake
  word) and opens `http://127.0.0.1:8765/sarah-avatar-ui.html` in the
  default browser when heard. Started via `run_sarah_listener.vbs`.
  Logs to `sarah_listener.log`.
- **Desktop icon**: `Sarah.url` (an Internet Shortcut, not a `.lnk`,
  because it needs to open a URL) pointing at the avatar's localhost URL,
  copied to the real Windows Desktop. Custom icon at `Sarah.ico` /
  `Sarah2.ico` (had to rename to bust Windows' aggressive icon-cache;
  `Sarah2.ico` is the one actually referenced by the shortcut now).
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
