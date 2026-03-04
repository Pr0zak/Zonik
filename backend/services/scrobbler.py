"""Scrobble forwarding to Last.fm."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from backend.config import get_settings

log = logging.getLogger(__name__)

SYNC_FILE = Path("data/lastfm_sync.json")


def _load_sync_config() -> dict:
    if SYNC_FILE.exists():
        return json.loads(SYNC_FILE.read_text())
    return {}


def _save_sync_config(config: dict):
    SYNC_FILE.parent.mkdir(parents=True, exist_ok=True)
    SYNC_FILE.write_text(json.dumps(config, indent=2))


async def forward_scrobble(artist: str, track: str, album: str = ""):
    """Forward a scrobble to Last.fm if a session key is configured."""
    config = _load_sync_config()
    session_key = config.get("session_key")
    if not session_key:
        return

    from backend.services.lastfm import scrobble_track
    await scrobble_track(artist, track, int(time.time()), session_key, album)


async def sync_loved_tracks(session_key: str):
    """Sync starred tracks to Last.fm as loved tracks."""
    from backend.database import async_session
    from backend.models.favorite import Favorite
    from backend.models.track import Track
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from backend.services.lastfm import love_track

    async with async_session() as db:
        result = await db.execute(
            select(Favorite).options(
                selectinload(Favorite.track).selectinload(Track.artist)
            ).where(Favorite.track_id.isnot(None))
        )
        favorites = result.scalars().all()

        for fav in favorites:
            if fav.track and fav.track.artist:
                await love_track(fav.track.artist.name, fav.track.title, session_key)
