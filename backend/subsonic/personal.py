"""The caller's own view of the songs, albums and artists in a Subsonic response.

Serialized songs carry the caller's playCount / userRating / played / starred, never the
library-wide totals on `tracks` (multi-user P2). Each response loads it once for all the
items it returns (stats_for plus one favorites query per kind), so there is no per-song query.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.favorite import Favorite
from backend.services.user_data import caller_id, stats_for


@dataclass
class Personal:
    user_id: str | None = None
    stats: dict = field(default_factory=dict)  # track_id -> UserTrackStats
    starred_tracks: dict[str, datetime] = field(default_factory=dict)
    starred_albums: dict[str, datetime] = field(default_factory=dict)
    starred_artists: dict[str, datetime] = field(default_factory=dict)


async def _starred(db: AsyncSession, user_id: str, column, ids: list[str]) -> dict[str, datetime]:
    out: dict[str, datetime] = {}
    for i in range(0, len(ids), 500):
        rows = (await db.execute(
            select(column, Favorite.starred_at)
            .where(Favorite.user_id == user_id, column.in_(ids[i:i + 500]))
        )).all()
        out.update({r[0]: r[1] for r in rows})
    return out


async def personal_view(request: Request, db: AsyncSession, tracks=(), albums=(), artists=(),
                        user_id: str | None = None) -> Personal:
    """The caller's stats and stars for these items (the owner for anonymous grace calls)."""
    uid = user_id or await caller_id(request, db)
    view = Personal(user_id=uid)
    if not uid:
        return view
    track_ids = list(dict.fromkeys(t.id for t in tracks if t is not None))
    album_ids = list(dict.fromkeys(a.id for a in albums if a is not None))
    artist_ids = list(dict.fromkeys(a.id for a in artists if a is not None))
    if track_ids:
        view.stats = await stats_for(db, uid, track_ids)
        view.starred_tracks = await _starred(db, uid, Favorite.track_id, track_ids)
    if album_ids:
        view.starred_albums = await _starred(db, uid, Favorite.album_id, album_ids)
    if artist_ids:
        view.starred_artists = await _starred(db, uid, Favorite.artist_id, artist_ids)
    return view
