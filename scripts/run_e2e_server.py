from __future__ import annotations

import os
import shutil
from pathlib import Path

from alembic import command
from alembic.config import Config


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".e2e-runtime"
DATABASE = RUNTIME / "messenger.db"


def main() -> None:
    if RUNTIME.exists():
        shutil.rmtree(RUNTIME)
    RUNTIME.mkdir(parents=True)
    os.environ.update({
        "APP_ENV": "test",
        "DATABASE_URL": f"sqlite+aiosqlite:///{DATABASE.as_posix()}",
        "DATABASE_SYNC_URL": f"sqlite:///{DATABASE.as_posix()}",
        "MEDIA_DIR": str(RUNTIME / "media"),
        "UPLOAD_DIR": str(RUNTIME / "uploads"),
        "CORS_ORIGINS": "http://127.0.0.1:5173",
        # The browser security scenario intentionally performs many reload,
        # polling, device and envelope requests. Rate-limit behavior is covered
        # separately by backend tests; it must not truncate this E2E workflow.
        "RATE_LIMIT_REQUESTS": "10000",
    })
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(config, "head")

    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
