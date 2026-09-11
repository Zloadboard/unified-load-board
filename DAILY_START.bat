@echo off
cd /d "%~dp0"
title Unified Load Board - DAILY_START (extension mode)
echo.
echo ========================================
echo   Extension mode (no CDP by default)
echo ========================================
echo.
echo Prefer SILENT_START.vbs / Task Scheduler.
echo This bat starts serve_board only, then opens the board.
echo.
echo 1) Starting CORS board server (serve_board.py)...
call "%~dp0START_TABLE.bat"

echo.
echo 2) Board: http://localhost:8765/
echo    Extension zip: http://localhost:8765/extension/ulb-extension.zip
echo    Install: see EXTENSION.md
echo.
start "" "http://localhost:8765/"
pause
