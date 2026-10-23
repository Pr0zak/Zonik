"""Failed-login lockout, per (client IP, lowercased username), in memory.

After login_max_failures failures inside lockout_minutes, further attempts for that pair are
refused until the oldest counted failure ages out. A successful login clears the pair. In
memory on purpose: a restart forgetting the counters is harmless, and it keeps the login path
free of writes.
"""
from __future__ import annotations

import math
import time

from backend.config import get_settings

_failures: dict[tuple[str, str], list[float]] = {}


def _key(ip: str | None, username: str) -> tuple[str, str]:
    return (ip or "?", (username or "").strip().lower())


def _window() -> float:
    return max(1, get_settings().auth.lockout_minutes) * 60.0


def _recent(key: tuple[str, str], now: float) -> list[float]:
    times = [t for t in _failures.get(key, []) if now - t < _window()]
    if times:
        _failures[key] = times
    else:
        _failures.pop(key, None)
    return times


def locked_minutes(ip: str | None, username: str) -> int:
    """Minutes until this (ip, username) may try again; 0 when not locked."""
    now = time.time()
    times = _recent(_key(ip, username), now)
    if len(times) < max(1, get_settings().auth.login_max_failures):
        return 0
    return max(1, math.ceil((times[0] + _window() - now) / 60.0))


def record_failure(ip: str | None, username: str) -> None:
    now = time.time()
    if len(_failures) > 10000:  # many distinct IPs/usernames: drop what has aged out
        for k in list(_failures):
            _recent(k, now)
    key = _key(ip, username)
    _failures.setdefault(key, []).append(now)


def clear(ip: str | None, username: str) -> None:
    _failures.pop(_key(ip, username), None)


def reset_all() -> None:
    """Tests only."""
    _failures.clear()
