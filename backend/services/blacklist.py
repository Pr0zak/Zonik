"""The download blacklist: one lookup every download path shares.

`is_blacklisted` is the check /api/download/search and /trigger have always made;
`enqueue_download` (and through it every automatic download: scheduler, bulk,
playlist, retries) and `auto_download.submit_tracked` now make it too, so a track
the user stopped or blacklisted is never fetched behind their back.

`enqueue_download` signals a blacklisted track by raising BlacklistedTrack, never
by returning None: None means "the library already has it", which the tracked
path records as a success (and that would delete the track's backoff row).
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.blacklist import DownloadBlacklist
from backend.services.soulseek import normalize_text


class BlacklistedTrack(Exception):
    """A download was refused because the artist or track is blacklisted."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


async def is_blacklisted(db: AsyncSession, artist: str, track: str) -> str | None:
    """Check if artist/track is blacklisted. Returns reason or None."""
    artist_norm = normalize_text(artist)
    # SQL-filtered: only fetch entries matching this artist (not full table scan)
    result = await db.execute(
        select(DownloadBlacklist).where(
            func.lower(DownloadBlacklist.artist) == artist_norm.lower()
        )
    )
    for entry in result.scalars().all():
        if entry.track is None:
            return entry.reason or "Artist blacklisted"
        if normalize_text(entry.track) == normalize_text(track):
            return entry.reason or "Track blacklisted"
    return None
