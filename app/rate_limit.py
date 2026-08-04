"""Rate limiting utilities.

We rely on ``slowapi`` for the actual enforcement but wrap it so the
configuration (key function, storage, handler) is consistent and easy
to test.
"""
from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.responses import JSONResponse

from .config import get_settings


def _key_func(request: Request) -> str:
    """Identify the caller for rate limiting.

    For authenticated requests we use the bearer token (or, when present,
    the JWT subject). Unauthenticated traffic falls back to the client IP
    address.
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth.split(" ", 1)[1].strip()
        if token:
            return f"tok:{token[:32]}"

    # Try refresh cookie as a secondary signal.
    refresh = request.cookies.get("refresh_token")
    if refresh:
        return f"ref:{refresh[:32]}"

    return get_remote_address(request)


def _get_limiter_storage() -> str:
    import redis
    settings = get_settings()
    if settings.redis_url and settings.redis_url.startswith("redis://"):
        try:
            r = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1.0, socket_timeout=1.0)
            r.ping()
            r.close()
            return settings.redis_url
        except Exception:
            pass
    return "memory://"


settings = get_settings()
limiter = Limiter(
    key_func=_key_func,
    storage_uri=_get_limiter_storage(),
    strategy="fixed-window",
)


async def rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    """Return a structured 429 response."""
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests – please slow down."},
    )
