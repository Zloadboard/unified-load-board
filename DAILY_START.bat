@echo off
cd /d "%~dp0"
title Unified Load Board - DAILY_START (LEGACY)
echo.
echo ========================================
echo   LEGACY - prefer silent auto-start
echo ========================================
echo.
echo Use SILENT_START.vbs / Task Scheduler instead of this bat.
echo Starts ONE Chrome (board + broker tabs) on the primary monitor.
echo.
echo 1) Starting scanner Chrome (visible, one window)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scanner\daily_start_chrome.ps1"
if errorlevel 1 (
  echo ERROR: Could not start Chrome.
  pause
  exit /b 1
)

echo.
echo 2) Waiting 8s for Chrome...
timeout /t 8 /nobreak >nul

echo 3) Starting CORS board server (serve_board.py) minimized...
call "%~dp0START_TABLE.bat"

echo.
echo 4) Waiting 3s...
timeout /t 3 /nobreak >nul

echo 5) Starting scanner (pythonw / no console)...
call "%~dp0scanner\START_SCANNER_CDP.bat"

echo.
echo Board: http://localhost:8765/
echo Sign in via per-broker buttons on the board, then Hide Chrome.
echo Prefer: SILENT_START.vbs
echo.
start "" "http://localhost:8765/"
pause
