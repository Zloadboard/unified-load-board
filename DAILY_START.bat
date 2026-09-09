@echo off
cd /d "%~dp0"
title Unified Load Board - DAILY_START (LEGACY)
echo.
echo ========================================
echo   LEGACY - prefer silent auto-start
echo ========================================
echo.
echo Use SILENT_START.vbs / Task Scheduler instead of this bat.
echo This script still works if you need a manual kick.
echo.
echo 1) Starting scanner Chrome...
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

echo 5) Starting scanner minimized...
call "%~dp0scanner\START_SCANNER_CDP.bat"

echo.
echo Board: http://localhost:8765/
echo Prefer: SILENT_START.vbs (no pause / no extra browser).
echo.
start "" "http://localhost:8765/"
pause
