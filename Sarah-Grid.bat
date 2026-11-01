@echo off
REM Starts Sarah Core on this PC (only reachable from this computer) and opens the control room.
cd /d "%~dp0"
python -c "import keyring" 2>nul || python -m pip install --user --quiet keyring
powershell -NoProfile -Command "if (-not (Test-NetConnection 127.0.0.1 -Port 8770 -InformationLevel Quiet -WarningAction SilentlyContinue)) { Start-Process pythonw -ArgumentList 'sarah_core.py' -WindowStyle Hidden; Start-Sleep -Seconds 3 }"
start "" "http://127.0.0.1:8770/"
