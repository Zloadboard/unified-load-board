@echo off
cd /d "%~dp0"
echo Starting CDP scanner (minimized). Leave scanner Chrome open on port 9222.
where py >nul 2>&1 && (
  start "ULB Scanner" /min cmd /c "py -3 cdp_attach.py"
  exit /b 0
)
where python >nul 2>&1 && (
  start "ULB Scanner" /min cmd /c "python cdp_attach.py"
  exit /b 0
)
echo ERROR: python not found
pause
exit /b 1
