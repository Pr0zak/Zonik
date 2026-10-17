"""Native Soulseek client for Zonik — replaces slskd dependency."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

log = logging.getLogger(__name__)

_client: Optional["SoulseekClient"] = None


def get_client() -> Optional["SoulseekClient"]:
    """Get the singleton native Soulseek client (None if not started)."""
    return _client


async def start_client() -> "SoulseekClient":
    """Start the native Soulseek client using config from zonik.toml."""
    global _client
    from backend.config import get_settings
    from backend.soulseek.client import SoulseekClient

    settings = get_settings()
    cfg = settings.soulseek

    if not cfg.username or not cfg.password:
        log.warning("[soulseek] Native client not started: no username/password configured")
        return None

    async with _start_lock:
        if _client is not None:
            return _client
        client = SoulseekClient(
            listen_port=cfg.listen_port,
        )
        try:
            await client.connect_and_login(cfg.username, cfg.password)
        except Exception as e:
            # The server sometimes throttles logins (connection accepted, login never
            # answered). Keep trying in the background with a growing delay instead of
            # leaving Soulseek off until the 16-minute watchdog notices.
            log.warning(f"[soulseek] Login failed at start ({e!r}); retrying in the background")
            _schedule_start_retry()
            raise
        _client = client
        log.info("[soulseek] Native client started and logged in")
        return client


_start_lock = asyncio.Lock()
_retry_task: "asyncio.Task | None" = None


def _schedule_start_retry() -> None:
    global _retry_task
    if _retry_task and not _retry_task.done():
        return
    _retry_task = asyncio.create_task(_start_retry_loop())


async def _start_retry_loop() -> None:
    from backend.soulseek.server_conn import ServerConnection
    attempt = 3  # start at the throttled schedule: 60 s, 2, 4, 8, 15 min
    while _client is None:
        delay = ServerConnection.reconnect_delay(attempt)
        log.info(f"[soulseek] Retrying login in {delay}s")
        await asyncio.sleep(delay)
        if _client is not None:
            return
        try:
            await start_client()
        except Exception:
            attempt += 1
        else:
            return


async def stop_client() -> None:
    """Stop the native Soulseek client."""
    global _client
    if _client:
        _client.destroy()
        _client = None
        log.info("[soulseek] Native client stopped")
