# Sarah — desktop icon + wake word setup

One-time setup, run from PowerShell. Everything runs locally and offline
(no API key, no cost, no audio leaves your PC).

## 1. Install dependencies

```powershell
pip install vosk sounddevice
```

## 2. Download the offline speech model (~40MB, one-time)

```powershell
cd "C:\Users\asid3\Documents\BRAIN\Sarah"
Invoke-WebRequest -Uri "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip" -OutFile "model.zip"
Expand-Archive -Path "model.zip" -DestinationPath "." -Force
Rename-Item "vosk-model-small-en-us-0.15" "model"
Remove-Item "model.zip"
```

## 3. Desktop icon (double-click to open Sarah, no wake word needed)

Point it at `Sarah-Launch.vbs`, not the .html — the launcher starts the local
server first if it isn't already up, then opens the avatar over
`http://127.0.0.1:8765`. Opening the .html directly as a `file://` path means
Chrome re-prompts for the microphone every single time.

```powershell
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("$env:USERPROFILE\Desktop\Sarah.lnk")
$Shortcut.TargetPath = "C:\Users\asid3\Documents\BRAIN\Sarah\Sarah-Launch.vbs"
$Shortcut.IconLocation = "C:\Users\asid3\Documents\BRAIN\Sarah\Sarah2.ico"
$Shortcut.Save()
```

## 4. Auto-start the server + wake-word listener at login

Both are needed for Sarah to be always-on: the server so the avatar page (and
its Projects panel) is reachable, the listener so "Sarah" wakes her.

```powershell
$WshShell = New-Object -ComObject WScript.Shell
$Startup = [Environment]::GetFolderPath('Startup')
$Base = "C:\Users\asid3\Documents\BRAIN\Sarah"
foreach ($p in @(@('Sarah Server.lnk','run_sarah_server.vbs'), @('Sarah Listener.lnk','run_sarah_listener.vbs'))) {
  $s = $WshShell.CreateShortcut((Join-Path $Startup $p[0]))
  $s.TargetPath = "$Base\$($p[1])"
  $s.WorkingDirectory = $Base
  $s.IconLocation = "$Base\Sarah2.ico"
  $s.Save()
}
```

If you ever rename the project again, **re-run this** — these are plain
shortcuts holding absolute paths, and a rename silently breaks them without any
error at login. (That is exactly what happened to the old `Rencho *.lnk` pair.)

## 5. Start them now (so they're active this session too, without rebooting)

```powershell
wscript.exe "C:\Users\asid3\Documents\BRAIN\Sarah\run_sarah_server.vbs"; wscript.exe "C:\Users\asid3\Documents\BRAIN\Sarah\run_sarah_listener.vbs"
```

## Using it

- Say "Sarah" anytime — after a second or two it opens the avatar UI in
  your default browser. It then listens/responds via the avatar's own
  voice UI (needs your Claude API key entered once in Settings there).
- The Desktop icon does the same thing instantly via double-click, no
  voice needed.
- Runs silently — no visible window. Check
  `BRAIN\Sarah\sarah_listener.log` if you want to confirm it's alive or
  debug misfires.
- Your Claude Projects are listed in the right-hand panel — click one, or say
  "open my *name* project" / "list my projects". Populate it with the
  **Import** button (see README).
- To stop it: Task Manager → find `pythonw.exe` → End task. To stop it
  from auto-starting: delete the `Sarah Listener.lnk` / `Sarah Server.lnk`
  shortcuts from `shell:startup`.

## Notes

- "Sarah" is an uncommon word for a small offline speech model, so it
  may occasionally mishear it or miss it. The script also matches close
  mishearings (rancho, wren cho, etc.) to make triggering more forgiving.
  If it's too trigger-happy or too quiet, tell me and I'll tune the
  matching or swap in a stricter wake-word engine.
