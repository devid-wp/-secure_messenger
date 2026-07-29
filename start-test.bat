@echo off
setlocal
cd /d "%~dp0"

set "DATABASE_URL=sqlite+aiosqlite:///./test_messenger.db"
set "SEED_TEST_ACCOUNT=1"
set "TEST_LOGIN=testuser"
set "TEST_PASSWORD=TestMessenger!2026"

echo Starting Secure Messenger with an isolated test database...
echo Test login: %TEST_LOGIN%
echo Test password: %TEST_PASSWORD%
echo.

call "%~dp0start.bat"
exit /b %errorlevel%
