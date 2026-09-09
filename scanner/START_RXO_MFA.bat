@echo off
cd /d "%~dp0"
echo Opening RXO for MFA / login...
where py >nul 2>&1 && (py -3 rxo_mfa_login.py & goto :done)
where python >nul 2>&1 && (python rxo_mfa_login.py & goto :done)
echo ERROR: python not found
pause
exit /b 1
:done
if errorlevel 1 pause
