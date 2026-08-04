"""In-memory store for pending 2FA setup secrets.

When a user starts TOTP setup we generate a random base32 secret and
return a QR code. The secret MUST NOT be persisted to the database
until the user has proven control of it (by submitting a valid code
on ``/2fa/enable``). Otherwise an attacker who briefly takes over the
account could plant a secret and wait for the user to enable 2FA,
letting the attacker log in on their own device.

The store is a process-local dict with a per-entry TTL (10 minutes,
matching what Discord and GitHub use). A background sweeper drops
expired entries every 30 seconds. Single-process deployment only —
multi-worker setups would need Redis, but that's out of scope for the
2FA flow because the secret is never user-visible until validated.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_TTL_SECONDS = 600  # 10 minutes
_SWEEP_INTERVAL = 30


class Pending2FAStore:
    def __init__(self, ttl_seconds: int = _TTL_SECONDS) -> None:
        self._entries: Dict[int, dict] = {}
        self._lock = asyncio.Lock()
        self._ttl = ttl_seconds
        self._sweeper: Optional[asyncio.Task] = None

    async def put(self, user_id: int, secret: str) -> None:
        async with self._lock:
            self._entries[user_id] = {
                "secret": secret,
                "created_at": time.time(),
            }
        self._ensure_sweeper()

    async def take(self, user_id: int) -> Optional[str]:
        """Return the pending secret for ``user_id`` and remove it.

        Returns ``None`` if there is no pending secret (or it has
        expired). One-shot — the caller is expected to commit to the
        database or discard.
        """
        async with self._lock:
            entry = self._entries.pop(user_id, None)
        if entry is None:
            return None
        if time.time() - entry["created_at"] > self._ttl:
            return None
        return entry["secret"]

    async def peek(self, user_id: int) -> Optional[str]:
        async with self._lock:
            entry = self._entries.get(user_id)
        if entry is None:
            return None
        if time.time() - entry["created_at"] > self._ttl:
            return None
        return entry["secret"]

    async def _sweep(self) -> None:
        try:
            while True:
                await asyncio.sleep(_SWEEP_INTERVAL)
                cutoff = time.time() - self._ttl
                async with self._lock:
                    stale = [uid for uid, e in self._entries.items() if e["created_at"] < cutoff]
                    for uid in stale:
                        self._entries.pop(uid, None)
                    if stale:
                        logger.debug("Swept %d expired 2FA pending entries", len(stale))
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("2FA pending sweeper stopped: %s", exc)
        finally:
            self._sweeper = None

    def _ensure_sweeper(self) -> None:
        if self._sweeper is None or self._sweeper.done():
            try:
                self._sweeper = asyncio.create_task(self._sweep())
            except RuntimeError:
                # No running loop yet — skip; next put() will retry.
                pass


store = Pending2FAStore()
