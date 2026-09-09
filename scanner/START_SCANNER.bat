@echo off
cd /d "%~dp0"
echo Starting load board scanner (Ctrl+C to stop)...
where py >nul 2>&1 && (
  py -3 scan.py
  goto :done
)
where python >nul 2>&1 && (
  python scan.py
  goto :done
)
echo ERROR: Neither "py -3" nor "python" found on PATH.
pause
exit /b 1
:done
if errorlevel 1 pause
