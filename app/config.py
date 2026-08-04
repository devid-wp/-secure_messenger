"""Application configuration loaded from environment variables.

Centralized here so that no module hardcodes secrets, paths, or limits.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import List, Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# JWT secrets that are clearly placeholders / unsafe and must NEVER be used
# outside of ``debug=True`` mode.
_UNSAFE_JWT_PREFIXES = (
    "change_this",
    "change-this",
    "super-secret-key",
    "secret",
    "changeme",
)
_MIN_JWT_SECRET_LEN = 32


class Settings(BaseSettings):
    """Strongly-typed application settings.

    Values can be overridden via environment variables (or a `.env` file
    in the project root). Anything sensitive should be supplied through
    the environment, never committed to source.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- General ---
    project_name: str = "Secure Messenger"
    debug: bool = Field(default=False)

    # --- Database ---
    # Default points at a local docker-compose Postgres instance.
    database_url: str = Field(
        default="postgresql+asyncpg://messenger:messenger@localhost:5432/secure_messenger",
    )
    # Synchronous URL is used by Alembic migrations.
    database_sync_url: str = Field(
        default="postgresql+psycopg2://messenger:messenger@localhost:5432/secure_messenger",
    )

    # --- Redis (rate-limit, pub/sub, presence, token revoke list) ---
    redis_url: str = Field(default="redis://localhost:6379/0")

    # --- JWT ---
    jwt_secret: str = Field(default="change_this_secret_in_production")
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 60 * 15  # 15 min
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 14  # 14 days
    jwt_issuer: str = "secure-messenger"

    # --- Server master key (used by app.crypto to seal attachments / refresh
    # token storage). Either ``server_master_key`` (base64 of 32 random bytes)
    # or ``server_key_file`` (path to a 32-byte file) MUST be configured in
    # production. In ``debug=True`` mode an ephemeral key is accepted.
    server_key_file: str = Field(default="data/server.key")
    server_master_key: Optional[str] = None

    # --- Cookie / CORS ---
    cookie_secure: bool = Field(default=False)  # set True behind HTTPS
    cookie_samesite: str = "lax"
    cors_allow_origins: List[str] = Field(
        default_factory=lambda: [
            "http://localhost",
            "http://127.0.0.1",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )

    # --- Limits ---
    message_max_length: int = 1024
    message_queue_maxsize: int = 100
    upload_dir: str = "data/uploads"
    upload_max_bytes: int = 25 * 1024 * 1024  # 25 MB
    upload_allowed_mime: List[str] = Field(
        default_factory=lambda: [
            "image/png",
            "image/jpeg",
            "image/gif",
            "image/webp",
            "audio/ogg",
            "audio/mpeg",
            "audio/wav",
            "video/mp4",
            "application/pdf",
            "text/plain",
        ]
    )

    # --- Rate limits (per route, per user) ---
    rate_limit_register: str = "20/hour"
    rate_limit_login: str = "10/minute"
    rate_limit_ws_messages: int = 30  # messages per minute per user
    rate_limit_message: str = "10/second"

    @model_validator(mode="after")
    def _validate_secrets(self) -> "Settings":
        """Refuse to start in production with a weak/default JWT secret.

        In ``debug=True`` mode we accept anything so local development is
        friction-free. Otherwise we require a real, sufficiently long
        secret that does not match a known placeholder prefix.
        """
        if self.debug:
            return self

        secret = (self.jwt_secret or "").strip()
        lowered = secret.lower()
        if (
            not secret
            or len(secret) < _MIN_JWT_SECRET_LEN
            or any(lowered.startswith(p) for p in _UNSAFE_JWT_PREFIXES)
        ):
            raise ValueError(
                "Insecure JWT_SECRET: refusing to start. "
                f"Set JWT_SECRET to a random value of at least {_MIN_JWT_SECRET_LEN} "
                f"characters (e.g. `python -c \"import secrets; "
                f"print(secrets.token_urlsafe(48))\"`)."
            )

        if not self.server_master_key and not self.server_key_file:
            raise ValueError(
                "Server master key is not configured: set SERVER_MASTER_KEY "
                "(base64 of 32 bytes) or SERVER_KEY_FILE (path to a 32-byte key)."
            )

        return self


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor.

    Using ``lru_cache`` keeps the parsed ``Settings`` instance around for
    the lifetime of the process so we don't re-read the environment on
    every request.
    """
    return Settings()
