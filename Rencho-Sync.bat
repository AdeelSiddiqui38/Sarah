@echo off
REM One-click sync: pushes all local Rencho changes up to GitHub.
cd /d "C:\Users\asid3\Documents\BRAIN\Rencho"
echo Syncing Rencho to GitHub...
git add -A
git commit -m "Sync %DATE% %TIME%"
git push
echo.
echo ---------------------------------------
echo Done. You can close this window.
pause >nul
