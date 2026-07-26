from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import time
from dataclasses import dataclass


def _token_key(token: str) -> str:
    return f"session:{hashlib.sha256(token.encode()).hexdigest()}"


@dataclass(frozen=True)
class SessionData:
    user_id: int
    device_id: str


class InMemorySessionStore:
    def __init__(self, ttl_seconds: int = 2_592_000) -> None:
        self.ttl_seconds = ttl_seconds
        self._tokens: dict[str, tuple[SessionData, float]] = {}
        self._device_keys: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()

    async def issue(self, user_id: int, device_id: str) -> str:
        token = secrets.token_urlsafe(32)
        key = _token_key(token)
        async with self._lock:
            self._tokens[key] = (
                SessionData(user_id=user_id, device_id=device_id),
                time.monotonic() + self.ttl_seconds,
            )
            self._device_keys.setdefault(device_id, set()).add(key)
        return token

    async def resolve(self, token: str) -> SessionData | None:
        key = _token_key(token)
        async with self._lock:
            value = self._tokens.get(key)
            if value is None:
                return None
            data, expires_at = value
            if expires_at <= time.monotonic():
                self._tokens.pop(key, None)
                self._device_keys.get(data.device_id, set()).discard(key)
                return None
            return data

    async def revoke(self, token: str) -> None:
        key = _token_key(token)
        async with self._lock:
            value = self._tokens.pop(key, None)
            if value:
                self._device_keys.get(value[0].device_id, set()).discard(key)

    async def revoke_device(self, device_id: str) -> None:
        async with self._lock:
            for key in self._device_keys.pop(device_id, set()):
                self._tokens.pop(key, None)

    async def close(self) -> None:
        return None


class RedisSessionStore:
    def __init__(self, redis, ttl_seconds: int) -> None:
        self.redis = redis
        self.ttl_seconds = ttl_seconds

    async def issue(self, user_id: int, device_id: str) -> str:
        token = secrets.token_urlsafe(32)
        key = _token_key(token)
        device_key = f"device-sessions:{device_id}"
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.set(
                key,
                json.dumps({"user_id": user_id, "device_id": device_id}),
                ex=self.ttl_seconds,
            )
            pipe.sadd(device_key, key)
            pipe.expire(device_key, self.ttl_seconds)
            await pipe.execute()
        return token

    async def resolve(self, token: str) -> SessionData | None:
        value = await self.redis.get(_token_key(token))
        if value is None:
            return None
        payload = json.loads(value)
        return SessionData(
            user_id=int(payload["user_id"]),
            device_id=str(payload["device_id"]),
        )

    async def revoke(self, token: str) -> None:
        key = _token_key(token)
        value = await self.redis.get(key)
        if value:
            payload = json.loads(value)
            await self.redis.srem(f"device-sessions:{payload['device_id']}", key)
        await self.redis.delete(key)

    async def revoke_device(self, device_id: str) -> None:
        device_key = f"device-sessions:{device_id}"
        keys = await self.redis.smembers(device_key)
        if keys:
            await self.redis.delete(*keys)
        await self.redis.delete(device_key)

    async def close(self) -> None:
        await self.redis.aclose()
