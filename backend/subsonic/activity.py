"""Track Subsonic API client activity for the Live view."""
from __future__ import annotations

from datetime import datetime, timedelta
from threading import Lock

# key = (username, client_name); value = {"username", "client_name",
#   "user_agent", "ip", "last_seen", "endpoint_count"}
_api_activity: dict[tuple[str, str], dict] = {}
_lock = Lock()

# Keep the dict bounded so a hostile client can't blow up memory.
_MAX_ENTRIES = 50
# Drop entries idle longer than this when reading.
_STALE_AFTER = timedelta(minutes=10)


def record_activity(
    username: str,
    client_name: str | None,
    user_agent: str | None = None,
    ip: str | None = None,
) -> None:
    """Bump last_seen + endpoint_count for (username, client_name)."""
    if not username:
        return
    client = client_name or "unknown"
    now = datetime.utcnow()
    key = (username, client)
    with _lock:
        entry = _api_activity.get(key)
        if entry is None:
            entry = {
                "username": username,
                "client_name": client,
                "user_agent": user_agent,
                "ip": ip,
                "last_seen": now,
                "first_seen": now,
                "endpoint_count": 1,
            }
            _api_activity[key] = entry
        else:
            entry["last_seen"] = now
            entry["endpoint_count"] += 1
            if user_agent:
                entry["user_agent"] = user_agent
            if ip:
                entry["ip"] = ip

        # LRU prune — if we exceeded the cap, drop the oldest.
        if len(_api_activity) > _MAX_ENTRIES:
            oldest = sorted(_api_activity.items(), key=lambda kv: kv[1]["last_seen"])
            for k, _ in oldest[: len(_api_activity) - _MAX_ENTRIES]:
                _api_activity.pop(k, None)


def get_active_clients() -> list[dict]:
    """Return live API clients, pruning stale entries."""
    cutoff = datetime.utcnow() - _STALE_AFTER
    out: list[dict] = []
    with _lock:
        stale_keys = [k for k, v in _api_activity.items() if v["last_seen"] < cutoff]
        for k in stale_keys:
            _api_activity.pop(k, None)
        for entry in _api_activity.values():
            out.append(dict(entry))
    out.sort(key=lambda e: e["last_seen"], reverse=True)
    return out
