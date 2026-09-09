@echo off
cd /d "%~dp0"
REM Legacy helper — silent_start uses pythonw with no window.
REM Prefer SILENT_START.vbs. This bat starts CORS serve_board.py with pythonw.
echo Starting CORS board server at http://localhost:8765/ (no console)...
where py >nul 2>&1 && (
  for /f "delims=" %%i in ('py -3 -c "import sys; print(sys.executable)"') do set PYEXE=%%i
)
if defined PYEXE (
  set PYW=%PYEXE:python.exe=pythonw.exe%
  if exist "%PYW%" (
    start "" "%PYW%" "%~dp0scanner\serve_board.py"
    exit /b 0
  )
  start "" /min "%PYEXE%" "%~dp0scanner\serve_board.py"
  exit /b 0
)
where pythonw >nul 2>&1 && (
  start "" pythonw "%~dp0scanner\serve_board.py"
  exit /b 0
)
where python >nul 2>&1 && (
  start "" /min python "%~dp0scanner\serve_board.py"
  exit /b 0
)
echo ERROR: Neither "py -3" nor "python" found on PATH.
pause
exit /b 1
