from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.auth import register_user, verify_password
from app.core.config import Settings
from app.db import create_database_engine, create_session_factory
from app.models import User


async def seed_test_accounts() -> None:
    if os.getenv("SEED_TEST_ACCOUNT") != "1":
        raise SystemExit("Refusing to seed without SEED_TEST_ACCOUNT=1")

    logins = [
        login.strip()
        for login in os.getenv(
            "TEST_LOGINS",
            "testuser,test1,test2,test3,test4,test5",
        ).split(",")
        if login.strip()
    ]
    password = os.getenv("TEST_PASSWORD", "TestMessenger!2026")
    settings = Settings.from_env()
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)

    try:
        async with session_factory() as session:
            for login in logins:
                user = await session.scalar(
                    select(User).where(User.login == login)
                )
                if user is None:
                    credentials = register_user(login, password)
                    user = User(
                        login=credentials["login"],
                        password_hash=credentials["hash"].encode("utf-8"),
                        password_salt=b"",
                    )
                    session.add(user)
                    action = "created"
                else:
                    password_matches, _ = verify_password(
                        password,
                        user.password_hash,
                        user.password_salt,
                    )
                    if not password_matches:
                        credentials = register_user(login, password)
                        user.password_hash = credentials["hash"].encode("utf-8")
                        user.password_salt = b""
                        action = "password reset"
                    else:
                        action = "already ready"
                print(f"Test account {action}: {login}")
            await session.commit()
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(seed_test_accounts())
