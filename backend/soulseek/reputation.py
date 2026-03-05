"""Redis-backed peer reputation tracking for download reliability."""
from __future__ import annotations

import logging
import time

log = logging.getLogger(__name__)

# In-memory fallback when Redis is unavailable
_memory_store: dict[str, dict] = {}

FAILURE_THRESHOLD = 3  # Failures before blocking
BLOCK_DURATION = 24 * 3600  # 24 hours


class PeerReputation:
    """Tracks peer reliability for download scoring."""

    def __init__(self, redis_client=None):
        self._redis = redis_client

    async def record_success(self, username: str) -> None:
        key = f"slsk:rep:{username}"
        if self._redis:
            try:
                await self._redis.hincrby(key, "success", 1)
                await self._redis.hdel(key, "failures")
                await self._redis.expire(key, 7 * 86400)  # 7 day TTL
                return
            except Exception:
                pass
        # Fallback to memory
        _memory_store.setdefault(username, {})
        _memory_store[username]["success"] = _memory_store[username].get("success", 0) + 1
        _memory_store[username].pop("failures", None)
        _memory_store[username].pop("blocked_until", None)

    async def record_failure(self, username: str) -> None:
        key = f"slsk:rep:{username}"
        if self._redis:
            try:
                failures = await self._redis.hincrby(key, "failures", 1)
                if failures >= FAILURE_THRESHOLD:
                    await self._redis.hset(key, "blocked_until", str(int(time.time()) + BLOCK_DURATION))
                await self._redis.expire(key, 7 * 86400)
                return
            except Exception:
                pass
        # Fallback
        _memory_store.setdefault(username, {})
        failures = _memory_store[username].get("failures", 0) + 1
        _memory_store[username]["failures"] = failures
        if failures >= FAILURE_THRESHOLD:
            _memory_store[username]["blocked_until"] = time.time() + BLOCK_DURATION

    async def is_blocked(self, username: str) -> bool:
        key = f"slsk:rep:{username}"
        if self._redis:
            try:
                blocked_until = await self._redis.hget(key, "blocked_until")
                if blocked_until:
                    return time.time() < float(blocked_until)
                return False
            except Exception:
                pass
        # Fallback
        data = _memory_store.get(username, {})
        blocked_until = data.get("blocked_until", 0)
        return time.time() < blocked_until

    async def get_score_adjustment(self, username: str) -> int:
        """Return a score adjustment for quality scoring (positive = good, negative = bad)."""
        if await self.is_blocked(username):
            return -100

        if self._redis:
            try:
                key = f"slsk:rep:{username}"
                success = int(await self._redis.hget(key, "success") or 0)
                failures = int(await self._redis.hget(key, "failures") or 0)
                return min(success * 2, 10) - failures * 5
            except Exception:
                pass

        data = _memory_store.get(username, {})
        success = data.get("success", 0)
        failures = data.get("failures", 0)
        return min(success * 2, 10) - failures * 5
