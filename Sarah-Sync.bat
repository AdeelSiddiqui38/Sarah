@echo off
REM One-click sync: pushes all local Sarah changes up to GitHub.
cd /d "C:\Users\asid3\Documents\BRAIN\Sarah"
echo Syncing Sarah to GitHub...
git add -A
git commit -m "Sync %DATE% %TIME%"
git push
echo.
echo ---------------------------------------
echo Done. You can close this window.
pause >nul
