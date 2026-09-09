@echo off
cd /d "%~dp0"
echo. > LOGIN_DONE.txt
echo OK — told the login helper you are done.
timeout /t 3 >nul
