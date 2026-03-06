"""Scrobble forwarding and favorites sync to Last.fm."""
from __future__ import annotations

import logging
import time

from backend.config import get_settings

log = logging.getLogger(__name__)


async def forward_scrobble(artist: str, track: str, album: str = ""):
    """Forward a scrobble to Last.fm if a session key is configured."""
    settings = get_settings()
    session_key = settings.lastfm.session_key
    if not session_key:
        return

    from backend.services.lastfm import scrobble_track
    await scrobble_track(artist, track, int(time.time()), session_key, album)


async def sync_loved_tracks(session_key: str, username: str = "") -> dict:
    """Sync Zonik favorites → Last.fm loved tracks (incremental)."""
    from backend.database import async_session
    from backend.models.favorite import Favorite
    from backend.models.track import Track
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from backend.services.lastfm import love_track, get_loved_tracks

    # Get already-loved tracks on Last.fm to avoid redundant API calls
    already_loved: set[tuple[str, str]] = set()
    if username:
        try:
            already_loved = await get_loved_tracks(username)
            log.info(f"Last.fm has {len(already_loved)} loved tracks")
        except Exception as e:
            log.warning(f"Could not fetch Last.fm loved tracks: {e}")

    async with async_session() as db:
        result = await db.execute(
            select(Favorite).options(
                selectinload(Favorite.track).selectinload(Track.artist)
            ).where(Favorite.track_id.isnot(None))
        )
        favorites = result.scalars().all()

    synced = 0
    skipped = 0
    errors = 0
    for fav in favorites:
        if not fav.track or not fav.track.artist:
            continue
        artist_name = fav.track.artist.name
        title = fav.track.title
        if (artist_name.lower(), title.lower()) in already_loved:
            skipped += 1
            continue
        try:
            resp = await love_track(artist_name, title, session_key)
            if resp.get("error"):
                errors += 1
                log.warning(f"Failed to love {artist_name} - {title}: {resp.get('message', '')}")
            else:
                synced += 1
        except Exception as e:
            errors += 1
            log.warning(f"Error loving {artist_name} - {title}: {e}")

    return {"synced": synced, "skipped": skipped, "errors": errors, "total": len(favorites)}
