@echo off
setlocal
cd /d "%~dp0"

echo Starting Secure Messenger without Docker...
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-local.ps1"
set "exitCode=%errorlevel%"

if not "%exitCode%"=="0" (
    echo.
    echo Startup failed with error code %exitCode%.
    pause
)

exit /b %exitCode%
