"""Native Soulseek client for Zonik — replaces slskd dependency."""
from __future__ import annotations

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

    client = SoulseekClient(
        listen_port=cfg.listen_port,
    )
    await client.connect_and_login(cfg.username, cfg.password)
    _client = client
    log.info("[soulseek] Native client started and logged in")
    return client


async def stop_client() -> None:
    """Stop the native Soulseek client."""
    global _client
    if _client:
        _client.destroy()
        _client = None
        log.info("[soulseek] Native client stopped")
