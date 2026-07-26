import asyncio
import json

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self, redis=None) -> None:
        self._connections: dict[str, tuple[int, WebSocket]] = {}
        self._lock = asyncio.Lock()
        self.redis = redis
        self._subscriber_task: asyncio.Task | None = None

    async def start(self) -> None:
        if self.redis is not None:
            self._subscriber_task = asyncio.create_task(self._subscribe())

    async def close(self) -> None:
        if self._subscriber_task:
            self._subscriber_task.cancel()
            try:
                await self._subscriber_task
            except asyncio.CancelledError:
                pass

    async def _subscribe(self) -> None:
        async with self.redis.pubsub() as pubsub:
            await pubsub.subscribe("realtime:events")
            async for item in pubsub.listen():
                if item["type"] == "message":
                    event = json.loads(item["data"])
                    await self._broadcast_local(set(event["user_ids"]), event["payload"])

    async def connect(
        self,
        token: str,
        user_id: int,
        websocket: WebSocket,
        subprotocol: str | None = None,
    ) -> None:
        await websocket.accept(subprotocol=subprotocol)
        async with self._lock:
            self._connections[token] = (user_id, websocket)
        if self.redis is not None:
            await self.redis.incr(f"presence:{user_id}")

    async def disconnect(self, token: str) -> None:
        async with self._lock:
            connection = self._connections.pop(token, None)
        if connection and self.redis is not None:
            count = await self.redis.decr(f"presence:{connection[0]}")
            if count <= 0:
                await self.redis.delete(f"presence:{connection[0]}")

    async def broadcast(self, user_ids: set[int], payload: dict) -> None:
        if self.redis is not None:
            await self.redis.publish(
                "realtime:events",
                json.dumps({"user_ids": list(user_ids), "payload": payload}),
            )
            return
        await self._broadcast_local(user_ids, payload)

    async def _broadcast_local(self, user_ids: set[int], payload: dict) -> None:
        async with self._lock:
            recipients = [
                (token, websocket)
                for token, (user_id, websocket) in self._connections.items()
                if user_id in user_ids
            ]
        stale_tokens: list[str] = []
        for token, websocket in recipients:
            try:
                await websocket.send_json(payload)
            except Exception:
                stale_tokens.append(token)
        if stale_tokens:
            async with self._lock:
                for token in stale_tokens:
                    self._connections.pop(token, None)
