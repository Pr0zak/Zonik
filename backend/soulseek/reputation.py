"""Redis-backed peer reputation tracking for download reliability.

No permanent blocking — peers with failures just get lower scores so they
rank below healthier sources.  They can still be selected if nothing better
is available (the peer may simply have been offline temporarily).
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger(__name__)

# In-memory fallback when Redis is unavailable
_memory_store: dict[str, dict] = {}

RECENT_FAILURE_WINDOW = 30 * 60  # 30 min — recent failures weigh more


class PeerReputation:
    """Tracks peer reliability for download scoring."""

    def __init__(self, redis_client=None):
        self._redis = redis_client

    async def record_success(self, username: str) -> None:
        key = f"slsk:rep:{username}"
        if self._redis:
            try:
                await self._redis.hincrby(key, "success", 1)
                # Halve failure count on success (gradual recovery)
                failures = int(await self._redis.hget(key, "failures") or 0)
                if failures > 0:
                    await self._redis.hset(key, "failures", str(max(0, failures // 2)))
                await self._redis.expire(key, 7 * 86400)
                return
            except Exception:
                pass
        _memory_store.setdefault(username, {})
        _memory_store[username]["success"] = _memory_store[username].get("success", 0) + 1
        failures = _memory_store[username].get("failures", 0)
        if failures > 0:
            _memory_store[username]["failures"] = max(0, failures // 2)

    async def record_failure(self, username: str) -> None:
        key = f"slsk:rep:{username}"
        now = time.time()
        if self._redis:
            try:
                await self._redis.hincrby(key, "failures", 1)
                await self._redis.hset(key, "last_failure", str(int(now)))
                await self._redis.expire(key, 7 * 86400)
                return
            except Exception:
                pass
        _memory_store.setdefault(username, {})
        _memory_store[username]["failures"] = _memory_store[username].get("failures", 0) + 1
        _memory_store[username]["last_failure"] = now

    async def has_recent_failure(self, username: str) -> bool:
        """Check if the peer failed recently (within the cooldown window)."""
        now = time.time()
        if self._redis:
            try:
                key = f"slsk:rep:{username}"
                last = await self._redis.hget(key, "last_failure")
                if last:
                    return now - float(last) < RECENT_FAILURE_WINDOW
                return False
            except Exception:
                pass
        data = _memory_store.get(username, {})
        last = data.get("last_failure", 0)
        return now - last < RECENT_FAILURE_WINDOW

    async def reset_all(self) -> int:
        """Clear all reputation data. Returns number of entries cleared."""
        count = len(_memory_store)
        _memory_store.clear()
        if self._redis:
            try:
                keys = []
                async for key in self._redis.scan_iter("slsk:rep:*"):
                    keys.append(key)
                if keys:
                    await self._redis.delete(*keys)
                    count = max(count, len(keys))
            except Exception:
                pass
        return count

    async def get_score_adjustment(self, username: str) -> int:
        """Return a score adjustment for quality scoring (positive = good, negative = bad)."""
        if self._redis:
            try:
                key = f"slsk:rep:{username}"
                success = int(await self._redis.hget(key, "success") or 0)
                failures = int(await self._redis.hget(key, "failures") or 0)
            except Exception:
                success, failures = 0, 0
        else:
            data = _memory_store.get(username, {})
            success = data.get("success", 0)
            failures = data.get("failures", 0)

        score = min(success * 2, 10) - failures * 3
        # Extra penalty if they failed very recently
        if await self.has_recent_failure(username):
            score -= 5
        return score
