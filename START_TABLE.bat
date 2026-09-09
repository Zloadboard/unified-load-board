@echo off
cd /d "%~dp0"
REM Legacy helper — silent_start uses pythonw with no window.
REM Prefer SILENT_START.vbs. This bat starts CORS serve_board.py minimized.
echo Starting CORS board server at http://localhost:8765/ (minimized)...
where py >nul 2>&1 && (
  start "ULB Board" /min cmd /c "py -3 scanner\serve_board.py"
  exit /b 0
)
where python >nul 2>&1 && (
  start "ULB Board" /min cmd /c "python scanner\serve_board.py"
  exit /b 0
)
echo ERROR: Neither "py -3" nor "python" found on PATH.
pause
exit /b 1
