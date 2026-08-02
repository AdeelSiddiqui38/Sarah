# Sarah

Personal always-on, voice-first assistant ("JARVIS-style") for Adeel.

## Parts
- **sarah-avatar-ui.html** — browser avatar UI: voice in/out, in-page wake word,
  Claude/OpenAI brain, memory, and GitHub tool-calling. Served over
  `http://127.0.0.1:8765/sarah-avatar-ui.html`.
- **sarah_server.py** — local server: serves this folder + proxies OpenAI and
  GitHub API calls (browsers can't call those directly). Loopback-only.
- **sarah_listener.py** — offline Vosk wake-word listener; say "Sarah" to open
  the avatar even with no browser open.
- **run_sarah_server.vbs / run_sarah_listener.vbs** — silent background launchers.
- **Sarah.url / *.ico** — desktop shortcut + icon.

## Run
1. `pythonw sarah_server.py` (or double-click `run_sarah_server.vbs`)
2. Open `http://127.0.0.1:8765/sarah-avatar-ui.html`

## Setup / dependencies
See `SETUP.md` and `requirements.txt`. The Vosk speech model (`model/`,
`model.zip`) is not committed — re-download per SETUP.

## API keys
Keys and the GitHub token live in the browser's localStorage (Settings ⚙),
never in these files. Nothing here contains secrets.
