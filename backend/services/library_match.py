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
_index_strict: dict[tuple[str, str], str] = {}
_index_built_at = 0.0
_index_count = -1


def norm_title(s: str) -> str:
    s = _PAREN_SUFFIX_RE.sub("", s or "").strip()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def norm_title_strict(s: str) -> str:
    """Like norm_title but keeps a trailing "(...)"/"[...]", so "Song (X Remix)" and
    "Song" stay different tracks."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def norm_artist(s: str) -> str:
    # The primary artist ends at the first "," or ";" — ";" is how multi-value
    # artist tags are joined ("BB Cooper; Jake Daniels"), and without this split a
    # recommendation for "BB Cooper" never matched that library track.
    primary = re.split(r"[,;]", s or "", 1)[0]
    primary = _FEAT_RE.sub("", primary).strip()
    return re.sub(r"[^a-z0-9]", "", primary.lower())


_CREDIT_SPLIT_RE = re.compile(r"\s*(?:,|&|/|\+|\bx\b|\band\b|\bwith\b|\bfeat\.?|\bfeaturing\b|\bft\.?)\s*", re.IGNORECASE)


def artist_names(s: str) -> set[str]:
    """Every credited artist in a credit line, normalized: "College & Electric
    Youth" -> {"college", "electricyouth"}."""
    return {re.sub(r"[^a-z0-9]", "", p.lower()) for p in _CREDIT_SPLIT_RE.split(s or "")} - {""}


def artists_overlap(a: str, b: str) -> bool:
    """Do two credit lines share an artist? Catalogs credit collaborations
    differently ("College & Electric Youth" vs "COLLEGE")."""
    return bool(artist_names(a) & artist_names(b))


def key_artist(s: str) -> str:
    """Index key for an artist. A name with no Latin letters or digits (CJK, Cyrillic)
    normalises to "", which would make every such name one key; fall back to the
    casefolded raw text so those still match only themselves."""
    return norm_artist(s) or (s or "").casefold().strip()


def key_title(s: str, strict: bool = False) -> str:
    """Index key for a title, with the same non-Latin fallback as key_artist."""
    return (norm_title_strict(s) if strict else norm_title(s)) or (s or "").casefold().strip()


def _index_keys(artist: str) -> list[str]:
    """Artist keys a library track is indexed under: the primary artist first, then
    every other credited name. Files tag collaborations as "Miss Monique & Glowal" or
    "Miss Monique and Glowal" while Last.fm says "Miss Monique, Glowal"; keyed only by
    the primary-artist rule that was one track the library never owned, so the
    recommendation downloaded it again every night."""
    keys = [key_artist(artist)]
    for name in artist_names(artist):
        if name not in keys:
            keys.append(name)
    return keys


def _lookup_keys(artist: str) -> list[str]:
    """Keys tried for a query artist, most specific first."""
    return _index_keys(artist)


async def _library_index(db: AsyncSession, strict_title: bool = False) -> dict[tuple[str, str], str]:
    global _index, _index_strict, _index_built_at, _index_count
    count = (await db.execute(select(func.count(Track.id)))).scalar_one()
    if count == _index_count and time.monotonic() - _index_built_at < _INDEX_TTL_S:
        return _index_strict if strict_title else _index
    # Library is small (~5-10k tracks); one full scan is cheaper than an
    # OR-of-many-conditions query and avoids exact-match brittleness.
    rows = await db.execute(
        select(Track.id, Track.title, Artist.name).join(Artist, Track.artist_id == Artist.id)
    )
    index: dict[tuple[str, str], str] = {}
    strict: dict[tuple[str, str], str] = {}
    for track_id, title, artist in rows.all():
        if title and artist:
            nt, nts = key_title(title), key_title(title, strict=True)
            for na in _index_keys(artist):
                index.setdefault((na, nt), track_id)
                strict.setdefault((na, nts), track_id)
    _index, _index_strict = index, strict
    _index_built_at, _index_count = time.monotonic(), count
    return strict if strict_title else index


async def match_library(db: AsyncSession, artist: str, title: str, strict_title: bool = False) -> str | None:
    """Library track id for artist + title, or None. strict_title keeps a trailing
    "(...)" version suffix significant."""
    if not artist or not title:
        return None
    index = await _library_index(db, strict_title)
    return _find(index, artist, key_title(title, strict=strict_title))


def _find(index: dict[tuple[str, str], str], artist: str, ntt: str) -> str | None:
    if not ntt:
        return None
    for na in _lookup_keys(artist):
        if na and (na, ntt) in index:
            return index[(na, ntt)]
    return None


async def batch_library_match(
    db: AsyncSession,
    items: list[dict],
    name_key: str = "name",
    artist_key: str = "artist",
    strict_title: bool = False,
) -> None:
    """Set in_library / track_id on each dict, from one library index."""
    if not items:
        return
    index = await _library_index(db, strict_title)
    for t in items:
        name = t.get(name_key) or ""
        artist = t.get(artist_key) or ""
        matched = _find(index, artist, key_title(name, strict=strict_title))
        t["in_library"] = matched is not None
        t["track_id"] = matched
