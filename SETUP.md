# Rencho — desktop icon + wake word setup

One-time setup, run from PowerShell. Everything runs locally and offline
(no API key, no cost, no audio leaves your PC).

## 1. Install dependencies

```powershell
pip install vosk sounddevice
```

## 2. Download the offline speech model (~40MB, one-time)

```powershell
cd "C:\Users\asid3\Documents\BRAIN\Rencho"
Invoke-WebRequest -Uri "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip" -OutFile "model.zip"
Expand-Archive -Path "model.zip" -DestinationPath "." -Force
Rename-Item "vosk-model-small-en-us-0.15" "model"
Remove-Item "model.zip"
```

## 3. Desktop icon (double-click to open Rencho, no wake word needed)

```powershell
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("$env:USERPROFILE\Desktop\Rencho.lnk")
$Shortcut.TargetPath = "C:\Users\asid3\Documents\BRAIN\jarvis-avatar-ui.html"
$Shortcut.Save()
```

## 4. Auto-start the wake-word listener at login

```powershell
$WshShell = New-Object -ComObject WScript.Shell
$Startup = [Environment]::GetFolderPath('Startup')
$Shortcut = $WshShell.CreateShortcut("$Startup\Rencho Listener.lnk")
$Shortcut.TargetPath = "C:\Users\asid3\Documents\BRAIN\Rencho\run_rencho_listener.vbs"
$Shortcut.Save()
```

## 5. Start it now (so it's active this session too, without rebooting)

```powershell
wscript.exe "C:\Users\asid3\Documents\BRAIN\Rencho\run_rencho_listener.vbs"
```

## Using it

- Say "Rencho" anytime — after a second or two it opens the avatar UI in
  your default browser. It then listens/responds via the avatar's own
  voice UI (needs your Claude API key entered once in Settings there).
- The Desktop icon does the same thing instantly via double-click, no
  voice needed.
- Runs silently — no visible window. Check
  `BRAIN\Rencho\rencho_listener.log` if you want to confirm it's alive or
  debug misfires.
- To stop it: Task Manager → find `pythonw.exe` → End task. To stop it
  from auto-starting: delete the `Rencho Listener.lnk` shortcut from
  `shell:startup`.

## Notes

- "Rencho" is an uncommon word for a small offline speech model, so it
  may occasionally mishear it or miss it. The script also matches close
  mishearings (rancho, wren cho, etc.) to make triggering more forgiving.
  If it's too trigger-happy or too quiet, tell me and I'll tune the
  matching or swap in a stricter wake-word engine.
