@echo off
setlocal
cd /d "%~dp0"

echo Checking and starting Secure Messenger Desktop...
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-desktop.ps1"
set "exitCode=%errorlevel%"

if not "%exitCode%"=="0" (
    echo.
    echo Desktop startup failed with error code %exitCode%.
    pause
)

exit /b %exitCode%
