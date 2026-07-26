from __future__ import annotations

import asyncio
import time

from fastapi import HTTPException


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int, redis=None) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.redis = redis
        self._counts: dict[str, tuple[int, float]] = {}
        self._lock = asyncio.Lock()

    async def check(self, key: str, limit: int | None = None) -> None:
        maximum = limit or self.limit
        if self.redis is not None:
            redis_key = f"rate:{key}:{int(time.time() // self.window_seconds)}"
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.incr(redis_key)
                pipe.expire(redis_key, self.window_seconds + 1)
                count, _ = await pipe.execute()
        else:
            now = time.monotonic()
            async with self._lock:
                count, expires = self._counts.get(key, (0, now + self.window_seconds))
                if expires <= now:
                    count, expires = 0, now + self.window_seconds
                count += 1
                self._counts[key] = (count, expires)
        if count > maximum:
            raise HTTPException(
                status_code=429,
                detail="Too many requests",
                headers={"Retry-After": str(self.window_seconds)},
            )
