@echo off
cd /d "%~dp0"
echo Starting login helper (headed Edge)...
where py >nul 2>&1 && (
  py -3 login.py
  goto :done
)
where python >nul 2>&1 && (
  python login.py
  goto :done
)
echo ERROR: Neither "py -3" nor "python" found on PATH.
pause
exit /b 1
:done
if errorlevel 1 pause
