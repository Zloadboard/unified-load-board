@echo off
cd /d "%~dp0"
echo Starting table + scanner minimized. Keep scanner Chrome (CDP 9222) signed in.
call "%~dp0START_TABLE.bat"
timeout /t 2 /nobreak >nul
call "%~dp0scanner\START_SCANNER_CDP.bat"
echo Done. Both run minimized — do not close those taskbar Python windows or live updates stop.
