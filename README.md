# Rencho

Personal always-on, voice-first assistant ("JARVIS-style") for Adeel.

## Parts
- **jarvis-avatar-ui.html** — browser avatar UI: voice in/out, in-page wake word,
  Claude/OpenAI brain, memory, and GitHub tool-calling. Served over
  `http://127.0.0.1:8765/jarvis-avatar-ui.html`.
- **rencho_server.py** — local server: serves this folder + proxies OpenAI and
  GitHub API calls (browsers can't call those directly). Loopback-only.
- **rencho_listener.py** — offline Vosk wake-word listener; say "Rencho" to open
  the avatar even with no browser open.
- **run_rencho_server.vbs / run_rencho_listener.vbs** — silent background launchers.
- **Rencho.url / *.ico** — desktop shortcut + icon.

## Run
1. `pythonw rencho_server.py` (or double-click `run_rencho_server.vbs`)
2. Open `http://127.0.0.1:8765/jarvis-avatar-ui.html`

## Setup / dependencies
See `SETUP.md` and `requirements.txt`. The Vosk speech model (`model/`,
`model.zip`) is not committed — re-download per SETUP.

## API keys
Keys and the GitHub token live in the browser's localStorage (Settings ⚙),
never in these files. Nothing here contains secrets.
