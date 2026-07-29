@echo off
setlocal
cd /d "%~dp0"

where docker >nul 2>nul
if errorlevel 1 (
    echo Docker is not installed or is not available in PATH.
    echo Install Docker Desktop, restart Windows, and run start.bat again.
    pause
    exit /b 1
)

docker info >nul 2>nul
if errorlevel 1 (
    echo Docker Desktop is not running.
    echo Start Docker Desktop and run start.bat again.
    pause
    exit /b 1
)

echo Building and starting Secure Messenger...
echo The application will be available at http://localhost:8080
echo Press Ctrl+C to stop it.
echo.

docker compose up --build
set "exitCode=%errorlevel%"

if not "%exitCode%"=="0" (
    echo.
    echo Secure Messenger stopped with error code %exitCode%.
    pause
)

exit /b %exitCode%
