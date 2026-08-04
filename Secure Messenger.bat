@echo off
setlocal
cd /d "%~dp0"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\open-web-app.ps1"
set "exitCode=%errorlevel%"

if not "%exitCode%"=="0" (
    echo.
    echo Secure Messenger could not be opened.
    pause
)

exit /b %exitCode%
