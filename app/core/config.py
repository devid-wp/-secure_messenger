from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE_PATH = PROJECT_ROOT / "secure_messenger.db"


def _default_database_url() -> str:
    return f"sqlite+aiosqlite:///{DEFAULT_SQLITE_PATH.as_posix()}"


@dataclass(frozen=True)
class Settings:
    environment: str = "development"
    database_url: str = _default_database_url()
    cors_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://localhost:3000",
    )
    sql_echo: bool = False
    redis_url: str | None = None
    session_ttl_seconds: int = 2_592_000
    rate_limit_requests: int = 120
    rate_limit_window_seconds: int = 60

    @classmethod
    def from_env(cls) -> "Settings":
        environment = os.environ.get("APP_ENV", "development").strip().lower()
        database_url = os.environ.get("DATABASE_URL", _default_database_url()).strip()
        origins = tuple(
            origin.strip()
            for origin in os.environ.get(
                "CORS_ORIGINS",
                "http://localhost:5173,http://localhost:3000",
            ).split(",")
            if origin.strip()
        )
        sql_echo = os.environ.get("SQL_ECHO", "").lower() in {"1", "true", "yes"}
        settings = cls(
            environment=environment,
            database_url=database_url,
            cors_origins=origins,
            sql_echo=sql_echo,
            redis_url=os.environ.get("REDIS_URL") or None,
            session_ttl_seconds=int(os.environ.get("SESSION_TTL_SECONDS", "2592000")),
            rate_limit_requests=int(os.environ.get("RATE_LIMIT_REQUESTS", "120")),
            rate_limit_window_seconds=int(
                os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60")
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.environment == "production" and not self.database_url.startswith(
            ("postgresql+psycopg://", "postgresql+psycopg_async://")
        ):
            raise RuntimeError(
                "APP_ENV=production requires DATABASE_URL with PostgreSQL/psycopg"
            )
        if self.environment == "production" and not self.redis_url:
            raise RuntimeError("APP_ENV=production requires REDIS_URL")
        if self.session_ttl_seconds < 300:
            raise RuntimeError("SESSION_TTL_SECONDS must be at least 300")

    @property
    def sync_database_url(self) -> str:
        if self.database_url.startswith("sqlite+aiosqlite://"):
            return self.database_url.replace("sqlite+aiosqlite://", "sqlite://", 1)
        if self.database_url.startswith("postgresql+psycopg_async://"):
            return self.database_url.replace(
                "postgresql+psycopg_async://",
                "postgresql+psycopg://",
                1,
            )
        return self.database_url
