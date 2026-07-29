@echo off
setlocal
cd /d "%~dp0"

set "DATABASE_URL=sqlite+aiosqlite:///./test_messenger.db"
set "SEED_TEST_ACCOUNT=1"
set "TEST_LOGINS=testuser,test1,test2,test3,test4,test5"
set "TEST_PASSWORD=TestMessenger!2026"

echo Starting Secure Messenger with an isolated test database...
echo Test logins: %TEST_LOGINS%
echo Test password: %TEST_PASSWORD%
echo.

call "%~dp0start.bat"
exit /b %errorlevel%
