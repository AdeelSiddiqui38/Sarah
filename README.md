# Sarah

Personal always-on, voice-first assistant ("JARVIS-style") for Adeel.

## Parts
- **sarah-avatar-ui.html** — browser avatar UI: voice in/out, in-page wake word,
  Claude/OpenAI brain, memory, GitHub tool-calling, and the Claude Projects
  panel. Served over `http://127.0.0.1:8765/`.
- **sarah_server.py** — local server: serves this folder + proxies OpenAI and
  GitHub API calls (browsers can't call those directly). Loopback-only.
- **sarah_listener.py** — offline Vosk wake-word listener; say "Sarah" to open
  the avatar even with no browser open.
- **run_sarah_server.vbs / run_sarah_listener.vbs** — silent background launchers.
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
