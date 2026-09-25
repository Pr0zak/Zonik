"""Is this (artist, title) already in the library? One answer for every caller.

Discovery, catalog search, the download trigger and playlist import used to
match external tracks against the library with three different rules (a
normalized match, an exact lowercase match, and none at all). They share this
one now.

The match is permissive: title and artist are reduced to lowercase
alphanumerics, a trailing "(...)"/"[...]" on the title ("(Remastered 2014)")
and a "feat./featuring/ft." section on the artist are dropped, and only the
primary (first comma-separated) artist counts. That absorbs the usual naming
differences between Spotify, Deezer, Last.fm and file tags.
"""
from __future__ import annotations

import re
import time

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.artist import Artist
from backend.models.track import Track

_PAREN_SUFFIX_RE = re.compile(r"\s*[\(\[][^\(\)\[\]]*[\)\]]\s*$")
_FEAT_RE = re.compile(r"\s+(feat\.?|featuring|ft\.?)\s+.+$", re.IGNORECASE)

# The library index is rebuilt at most this often, or sooner when the track
# count changes (an import or a delete), so a finished download shows as owned
# on the next search.
_INDEX_TTL_S = 60.0
_index: dict[tuple[str, str], str] = {}
_index_built_at = 0.0
_index_count = -1


def norm_title(s: str) -> str:
    s = _PAREN_SUFFIX_RE.sub("", s or "").strip()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def norm_artist(s: str) -> str:
    primary = (s or "").split(",", 1)[0]
    primary = _FEAT_RE.sub("", primary).strip()
    return re.sub(r"[^a-z0-9]", "", primary.lower())


async def _library_index(db: AsyncSession) -> dict[tuple[str, str], str]:
    global _index, _index_built_at, _index_count
    count = (await db.execute(select(func.count(Track.id)))).scalar_one()
    if count == _index_count and time.monotonic() - _index_built_at < _INDEX_TTL_S:
        return _index
    # Library is small (~5-10k tracks); one full scan is cheaper than an
    # OR-of-many-conditions query and avoids exact-match brittleness.
    rows = await db.execute(
        select(Track.id, Track.title, Artist.name).join(Artist, Track.artist_id == Artist.id)
    )
    index: dict[tuple[str, str], str] = {}
    for track_id, title, artist in rows.all():
        if title and artist:
            index.setdefault((norm_artist(artist), norm_title(title)), track_id)
    _index, _index_built_at, _index_count = index, time.monotonic(), count
    return index


async def match_library(db: AsyncSession, artist: str, title: str) -> str | None:
    """Library track id for artist + title, or None."""
    if not artist or not title:
        return None
    index = await _library_index(db)
    return index.get((norm_artist(artist), norm_title(title)))


async def batch_library_match(
    db: AsyncSession,
    items: list[dict],
    name_key: str = "name",
    artist_key: str = "artist",
) -> None:
    """Set in_library / track_id on each dict, from one library index."""
    if not items:
        return
    index = await _library_index(db)
    for t in items:
        name = t.get(name_key) or ""
        artist = t.get(artist_key) or ""
        matched = index.get((norm_artist(artist), norm_title(name))) if name and artist else None
        t["in_library"] = matched is not None
        t["track_id"] = matched
