@echo off
setlocal
cd /d "%~dp0"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-docker.ps1" %*
set "exitCode=%errorlevel%"

if "%exitCode%"=="10" (
    echo.
    echo Windows repair completed successfully.
    echo Restart Windows, then open start-docker.bat again.
    pause
    exit /b 0
)

if not "%exitCode%"=="0" (
    echo.
    echo Secure Messenger startup failed with error code %exitCode%.
    pause
)

exit /b %exitCode%
