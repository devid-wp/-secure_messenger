from __future__ import annotations

import os
from ipaddress import ip_network
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE_PATH = PROJECT_ROOT / "secure_messenger.db"
DEFAULT_UPLOAD_DIR = PROJECT_ROOT / "uploads"
DEFAULT_MEDIA_DIR = PROJECT_ROOT / "media"
INSECURE_PRODUCTION_VALUES = {
    "",
    "change-me",
    "local-development-only",
    "local-development-only-change-me",
    "secure-messenger",
}


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
    session_ttl_seconds: int = 900
    refresh_ttl_seconds: int = 2_592_000
    # The browser restores conversations, MLS directories and envelopes in
    # parallel after a reload.  A 120/minute device-wide ceiling rejects a
    # normal multi-chat restore before any endpoint-specific abuse limit is
    # reached.  Keep the global guard high enough for that burst; sensitive
    # authentication and KeyPackage operations retain their tighter limits.
    rate_limit_requests: int = 600
    rate_limit_window_seconds: int = 60
    upload_dir: Path = DEFAULT_UPLOAD_DIR
    media_storage_backend: str = "local"
    media_dir: Path = DEFAULT_MEDIA_DIR
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_bucket: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    trusted_proxy_cidrs: tuple[str, ...] = ()

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
            session_ttl_seconds=int(os.environ.get("SESSION_TTL_SECONDS", "900")),
            refresh_ttl_seconds=int(os.environ.get("REFRESH_TTL_SECONDS", "2592000")),
            rate_limit_requests=int(os.environ.get("RATE_LIMIT_REQUESTS", "600")),
            rate_limit_window_seconds=int(
                os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60")
            ),
            upload_dir=Path(
                os.environ.get("UPLOAD_DIR", str(DEFAULT_UPLOAD_DIR))
            ).resolve(),
            media_storage_backend=os.environ.get(
                "MEDIA_STORAGE_BACKEND", "local"
            ).strip().lower(),
            media_dir=Path(
                os.environ.get("MEDIA_DIR", str(DEFAULT_MEDIA_DIR))
            ).resolve(),
            s3_endpoint_url=os.environ.get("S3_ENDPOINT_URL") or None,
            s3_region=os.environ.get("S3_REGION", "us-east-1"),
            s3_bucket=os.environ.get("S3_BUCKET") or None,
            s3_access_key_id=os.environ.get("S3_ACCESS_KEY_ID") or None,
            s3_secret_access_key=os.environ.get("S3_SECRET_ACCESS_KEY") or None,
            trusted_proxy_cidrs=tuple(
                value.strip()
                for value in os.environ.get("TRUSTED_PROXY_CIDRS", "").split(",")
                if value.strip()
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.environment not in {"development", "test", "production"}:
            raise RuntimeError("APP_ENV must be development, test, or production")
        if self.environment == "production" and not self.database_url.startswith(
            ("postgresql+psycopg://", "postgresql+psycopg_async://")
        ):
            raise RuntimeError(
                "APP_ENV=production requires DATABASE_URL with PostgreSQL/psycopg"
            )
        if self.environment == "production" and not self.redis_url:
            raise RuntimeError("APP_ENV=production requires REDIS_URL")
        if self.environment == "production":
            self._validate_production_security()
        if self.session_ttl_seconds < 300:
            raise RuntimeError("SESSION_TTL_SECONDS must be at least 300")
        if self.refresh_ttl_seconds < self.session_ttl_seconds:
            raise RuntimeError("REFRESH_TTL_SECONDS must not be shorter than access sessions")
        if self.media_storage_backend not in {"local", "s3"}:
            raise RuntimeError("MEDIA_STORAGE_BACKEND must be local or s3")
        if self.environment == "production" and self.media_storage_backend != "s3":
            raise RuntimeError("APP_ENV=production requires MEDIA_STORAGE_BACKEND=s3")
        if self.media_storage_backend == "s3" and not all(
            (
                self.s3_endpoint_url,
                self.s3_bucket,
                self.s3_access_key_id,
                self.s3_secret_access_key,
            )
        ):
            raise RuntimeError(
                "S3 media storage requires endpoint, bucket, access key, and secret"
            )

    def _validate_production_security(self) -> None:
        if not self.cors_origins:
            raise RuntimeError("APP_ENV=production requires explicit CORS_ORIGINS")
        for origin in self.cors_origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme != "https"
                or not parsed.netloc
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
                or "*" in origin
            ):
                raise RuntimeError(
                    "Production CORS_ORIGINS must contain explicit HTTPS origins only"
                )
        if not self.trusted_proxy_cidrs:
            raise RuntimeError("APP_ENV=production requires TRUSTED_PROXY_CIDRS")
        try:
            proxy_networks = tuple(ip_network(value, strict=False) for value in self.trusted_proxy_cidrs)
        except ValueError as error:
            raise RuntimeError("TRUSTED_PROXY_CIDRS must contain valid CIDR networks") from error
        if any(network.prefixlen == 0 for network in proxy_networks):
            raise RuntimeError("TRUSTED_PROXY_CIDRS must not trust the entire internet")
        production_secrets = (
            self.database_url,
            self.redis_url or "",
            self.s3_access_key_id or "",
            self.s3_secret_access_key or "",
        )
        if any(self._is_insecure_production_value(value) for value in production_secrets):
            raise RuntimeError("Production configuration contains a development credential")

    @staticmethod
    def _is_insecure_production_value(value: str) -> bool:
        normalized = value.strip().lower()
        return not normalized or any(
            marker and marker in normalized for marker in INSECURE_PRODUCTION_VALUES
        )

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
