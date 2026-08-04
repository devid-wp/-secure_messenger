@echo off
setlocal
cd /d "%~dp0"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-docker.ps1" %*
set "exitCode=%errorlevel%"

if not "%exitCode%"=="0" (
    echo.
    echo Secure Messenger startup failed with error code %exitCode%.
    pause
)

exit /b %exitCode%
