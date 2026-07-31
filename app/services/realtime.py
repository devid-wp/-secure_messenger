import asyncio
import json

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self, redis=None) -> None:
        self._connections: dict[str, tuple[int, str, WebSocket]] = {}
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
                    if event.get("kind") == "close_device":
                        await self._close_device_local(event["device_id"])
                    else:
                        await self._broadcast_local(set(event["user_ids"]), event["payload"])

    async def connect(
        self,
        token: str,
        user_id: int,
        device_id: str,
        websocket: WebSocket,
        subprotocol: str | None = None,
    ) -> None:
        await websocket.accept(subprotocol=subprotocol)
        async with self._lock:
            self._connections[token] = (user_id, device_id, websocket)
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

    async def close_device(self, device_id: str) -> None:
        if self.redis is not None:
            await self.redis.publish(
                "realtime:events",
                json.dumps({"kind": "close_device", "device_id": device_id}),
            )
            return
        await self._close_device_local(device_id)

    async def _close_device_local(self, device_id: str) -> None:
        async with self._lock:
            recipients = [
                (token, websocket)
                for token, (_user_id, connected_device_id, websocket) in self._connections.items()
                if connected_device_id == device_id
            ]
        for token, websocket in recipients:
            try:
                await websocket.close(code=4003, reason="Device revoked")
            finally:
                await self.disconnect(token)

    async def _broadcast_local(self, user_ids: set[int], payload: dict) -> None:
        async with self._lock:
            recipients = [
                (token, websocket)
                for token, (user_id, _device_id, websocket) in self._connections.items()
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
