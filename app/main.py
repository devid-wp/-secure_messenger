from contextlib import asynccontextmanager

import uvicorn
from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from redis.asyncio import Redis

from .core.config import Settings
from .db import create_database_engine, create_session_factory
from .routers import auth, chats, e2ee, media, realtime, users
from .services.realtime import ConnectionManager
from .services.rate_limit import RateLimiter
from .services.session_store import InMemorySessionStore, RedisSessionStore
from .services.object_storage import create_object_storage


API_V1_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings.from_env()
    engine = create_database_engine(app_settings)
    session_factory = create_session_factory(engine)
    redis = (
        Redis.from_url(app_settings.redis_url, decode_responses=True)
        if app_settings.redis_url
        else None
    )
    session_store = (
        RedisSessionStore(redis, app_settings.session_ttl_seconds)
        if redis is not None
        else InMemorySessionStore(app_settings.session_ttl_seconds)
    )
    connection_manager = ConnectionManager(redis)
    object_storage = create_object_storage(app_settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await connection_manager.start()
        try:
            yield
        finally:
            await connection_manager.close()
            await session_store.close()
            await engine.dispose()

    application = FastAPI(
        title="Secure Messenger API",
        version="1.0.0",
        lifespan=lifespan,
    )
    application.state.settings = app_settings
    application.state.engine = engine
    application.state.session_factory = session_factory
    application.state.session_store = session_store
    application.state.connection_manager = connection_manager
    application.state.object_storage = object_storage
    application.state.rate_limiter = RateLimiter(
        app_settings.rate_limit_requests,
        app_settings.rate_limit_window_seconds,
        redis,
    )
    app_settings.upload_dir.mkdir(parents=True, exist_ok=True)
    application.mount(
        "/uploads",
        StaticFiles(directory=app_settings.upload_dir),
        name="uploads",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(app_settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.middleware("http")
    async def browser_security_headers(request: Request, call_next):
        """Apply defense-in-depth headers to API responses too.

        The frontend ingress owns the stricter document CSP and HTTPS redirect;
        these headers keep direct API/error responses non-embeddable and quiet.
        """
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        )
        if app_settings.environment == "production":
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains; preload"
            )
        return response

    api_v1 = APIRouter(prefix=API_V1_PREFIX)
    api_v1.include_router(auth.router)
    api_v1.include_router(users.router)
    api_v1.include_router(chats.router)
    api_v1.include_router(e2ee.router)
    api_v1.include_router(media.router)
    api_v1.include_router(realtime.router)
    application.include_router(api_v1)

    @application.get("/")
    async def root():
        return {
            "status": "ok",
            "service": "Secure Messenger API",
            "api": API_V1_PREFIX,
        }

    return application


app = create_app()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
