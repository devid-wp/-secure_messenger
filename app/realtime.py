"""Redis-backed pub/sub for WebSocket fanout across uvicorn workers.

Each uvicorn process subscribes to ``events`` and re-broadcasts received
packets to the local WebSocket clients that care about a given chat.
The same module also tracks presence (``online:<login>`` -> set of
worker ids) so ``/users`` and chat metadata can show live status.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Set

from fastapi import WebSocket
from redis.asyncio import Redis

from .config import get_settings

logger = logging.getLogger(__name__)

EVENTS_CHANNEL = "events"
PRESENCE_TTL = 60  # seconds — clients refresh every 30s


class Hub:
    """Per-process registry of local WebSocket connections + Redis fanout.

    When Redis is unavailable (dev mode without a broker), the hub
    transparently degrades to an in-process bus so a single-worker
    deployment still works. Multi-worker setups require Redis.

    .. note::
        **Production limitation:** when ``_use_local_fallback`` is True,
        all presence + WebSocket fanout stays in this Python process's
        memory. Running more than one uvicorn worker (or scaling to
        multiple pods) will *split* users across processes — a client
        connected to worker A will not see presence / messages from
        clients connected to worker B. Always run a real Redis broker
        (``REDIS_URL``) in production and disable this fallback.
    """

    def __init__(self) -> None:
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}"
        # chat_id -> set of websockets in this process.
        self._rooms: Dict[int, Set[WebSocket]] = {}
        # login -> websocket (one client per user per worker).
        self._clients: Dict[str, WebSocket] = {}
        self._redis: Redis | None = None
        self._pubsub_task: asyncio.Task | None = None
        self._stopped = asyncio.Event()
        # Local in-memory presence + fanout. Replaces Redis when the
        # broker is unreachable so single-process dev still works.
        self._local_online: set[str] = set()
        self._use_local_fallback: bool = False

    # --- connection lifecycle -----------------------------------------

    def attach(self, *, login: str, chat_ids: list[int], ws: WebSocket) -> None:
        self._clients[login] = ws
        for cid in chat_ids:
            self._rooms.setdefault(cid, set()).add(ws)

    def detach(self, ws: WebSocket) -> None:
        for cid, conns in list(self._rooms.items()):
            conns.discard(ws)
            if not conns:
                self._rooms.pop(cid, None)
        for login, sock in list(self._clients.items()):
            if sock is ws:
                self._clients.pop(login, None)

    async def _redis_client(self) -> Redis:
        if self._redis is None:
            settings = get_settings()
            self._redis = Redis.from_url(settings.redis_url, decode_responses=True)
        return self._redis

    async def _ensure_redis(self) -> Redis | None:
        """Return a working Redis client, or None if the broker is down."""
        try:
            return await self._redis_client()
        except Exception as exc:  # pragma: no cover - infra
            logger.warning("Redis unavailable, using in-process fanout: %s", exc)
            self._use_local_fallback = True
            return None

    # --- fanout -------------------------------------------------------

    async def publish(self, chat_id: int, payload: dict) -> None:
        """Send a packet to *all* workers, including this one.

        When Redis is unavailable we fall back to a local in-process
        broadcast; this is fine for a single-worker dev server.
        """
        r = await self._ensure_redis()
        if r is None:
            await self.broadcast_local(chat_id, payload)
            return
        msg = json.dumps({"chat_id": chat_id, "payload": payload})
        try:
            await r.publish(EVENTS_CHANNEL, msg)
        except Exception as exc:  # pragma: no cover - infra
            logger.warning("publish failed (%s); falling back to local", exc)
            self._use_local_fallback = True
            await self.broadcast_local(chat_id, payload)

    async def broadcast_local(self, chat_id: int, payload: dict) -> None:
        """Deliver a packet to local room members (called by the listener)."""
        conns = list(self._rooms.get(chat_id, ()))
        if not conns:
            return
        text = json.dumps(payload)
        for ws in conns:
            try:
                await ws.send_text(text)
            except Exception:  # pragma: no cover - sockets can die
                logger.debug("dropping dead local socket")

    # --- presence -----------------------------------------------------

    async def mark_online(self, login: str) -> None:
        r = await self._ensure_redis()
        if r is None:
            self._local_online.add(login)
            return
        try:
            await r.sadd(f"online:{login}", self.worker_id)
            await r.expire(f"online:{login}", PRESENCE_TTL)
        except Exception:
            self._use_local_fallback = True
            self._local_online.add(login)

    async def mark_offline(self, login: str) -> None:
        r = await self._ensure_redis()
        if r is None:
            self._local_online.discard(login)
            return
        try:
            await r.srem(f"online:{login}", self.worker_id)
        except Exception:
            self._use_local_fallback = True
            self._local_online.discard(login)

    async def is_online(self, login: str) -> bool:
        if self._use_local_fallback:
            return login in self._local_online
        r = await self._ensure_redis()
        if r is None:
            return login in self._local_online
        try:
            return bool(await r.exists(f"online:{login}"))
        except Exception:
            self._use_local_fallback = True
            return login in self._local_online

    # --- listener -----------------------------------------------------

    async def start(self) -> None:
        """Begin listening for cross-worker events.

        We first try to open the Redis pub/sub subscription. If Redis
        is unreachable, the hub flips into in-process mode and skips
        the listener — the rest of the API keeps working for a
        single-worker deployment.
        """
        r = await self._ensure_redis()
        if r is None:
            self._use_local_fallback = True
            logger.info("Hub running in in-process mode (no Redis)")
            return
        try:
            pubsub = r.pubsub()
            await pubsub.subscribe(EVENTS_CHANNEL)
            self._pubsub_task = asyncio.create_task(self._listen(pubsub))
        except Exception as exc:  # pragma: no cover - infra
            logger.warning("Redis subscribe failed (%s); using in-process hub", exc)
            self._use_local_fallback = True

    async def _listen(self, pubsub) -> None:
        try:
            async for message in pubsub.listen():
                if self._stopped.is_set():
                    break
                if message is None or message.get("type") != "message":
                    continue
                try:
                    data = json.loads(message["data"])
                    chat_id = int(data["chat_id"])
                    payload = data["payload"]
                except (ValueError, KeyError, TypeError):
                    continue
                await self.broadcast_local(chat_id, payload)
        except asyncio.CancelledError:  # pragma: no cover - shutdown
            pass
        finally:
            try:
                await pubsub.unsubscribe(EVENTS_CHANNEL)
                await pubsub.close()
            except Exception:
                pass

    async def stop(self) -> None:
        self._stopped.set()
        if self._pubsub_task is not None:
            self._pubsub_task.cancel()
            try:
                await self._pubsub_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                pass
            self._redis = None


hub = Hub()


@asynccontextmanager
async def lifespan_hub() -> AsyncIterator[None]:
    await hub.start()
    try:
        yield
    finally:
        await hub.stop()
