@echo off
cd /d "%~dp0"
REM Prefer pythonw (no console). Legacy fallback: minimized cmd.
echo Starting CDP scanner (no console). Scanner Chrome must be on port 9222.
where py >nul 2>&1 && (
  for /f "delims=" %%i in ('py -3 -c "import sys; print(sys.executable)"') do set PYEXE=%%i
)
if defined PYEXE (
  set PYW=%PYEXE:python.exe=pythonw.exe%
  if exist "%PYW%" (
    start "" "%PYW%" "%~dp0cdp_attach.py"
    exit /b 0
  )
  start "" /min "%PYEXE%" "%~dp0cdp_attach.py"
  exit /b 0
)
where pythonw >nul 2>&1 && (
  start "" pythonw "%~dp0cdp_attach.py"
  exit /b 0
)
where python >nul 2>&1 && (
  start "" /min python "%~dp0cdp_attach.py"
  exit /b 0
)
echo ERROR: python not found
pause
exit /b 1
