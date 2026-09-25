"""Search a music catalog for tracks, owned or not.

Deezer's public search (no key) is the main source: it is typo-tolerant, ranks
by popularity, and returns clean artist/title plus album, duration, cover art
and a 30 s preview. Last.fm track search is the fallback when Deezer fails or
finds nothing. Results are cached briefly, since the phone searches as you type.
"""
from __future__ import annotations

import logging
import time
from collections import OrderedDict

import httpx

from backend.services import lastfm

log = logging.getLogger(__name__)

_CACHE_TTL_S = 300.0
_CACHE_MAX = 256
_cache: OrderedDict[tuple[str, int], tuple[float, dict]] = OrderedDict()


def _cache_get(key: tuple[str, int]) -> dict | None:
    hit = _cache.get(key)
    if not hit:
        return None
    at, value = hit
    if time.monotonic() - at > _CACHE_TTL_S:
        _cache.pop(key, None)
        return None
    _cache.move_to_end(key)
    return value


def _cache_put(key: tuple[str, int], value: dict) -> None:
    _cache[key] = (time.monotonic(), value)
    _cache.move_to_end(key)
    while len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)


def _deezer_query(q: str) -> str:
    """Plain text, with an "Artist - Title" dash dropped.

    Deezer's fielded syntax (artist:"..." track:"...") returns nothing even for
    exact names, while its plain search is fuzzy and ranks the right song first.
    """
    return " ".join(q.replace(" - ", " ").split())


async def _deezer_search(q: str, limit: int) -> list[dict]:
    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.get("https://api.deezer.com/search", params={"q": _deezer_query(q), "limit": limit})
        resp.raise_for_status()
        data = resp.json()
    if "error" in data:  # Deezer reports quota and query errors with HTTP 200
        raise RuntimeError(f"Deezer: {data['error'].get('message', data['error'])}")
    out = []
    for t in data.get("data", []):
        artist = (t.get("artist") or {}).get("name") or ""
        title = t.get("title") or ""
        if not artist or not title:
            continue
        album = t.get("album") or {}
        out.append({
            "title": title,
            "artist": artist,
            "album": album.get("title"),
            "duration": t.get("duration"),
            "cover_url": album.get("cover_medium") or album.get("cover"),
            "preview_url": t.get("preview") or None,
            "explicit": bool(t.get("explicit_lyrics")),
            "source": "deezer",
            "source_id": str(t.get("id")) if t.get("id") else None,
        })
    return out


async def _lastfm_search(q: str, limit: int) -> list[dict]:
    return [
        {
            "title": t["name"],
            "artist": t["artist"],
            "album": None,
            "duration": None,
            "cover_url": None,
            "preview_url": None,
            "explicit": False,
            "source": "lastfm",
            "source_id": t.get("url"),
        }
        for t in await lastfm.search_tracks(q, limit=limit)
    ]


def _dedupe(tracks: list[dict]) -> list[dict]:
    """One row per artist + title (Deezer lists each release of a song)."""
    from backend.services.library_match import norm_artist, norm_title

    seen: set[tuple[str, str]] = set()
    out = []
    for t in tracks:
        key = (norm_artist(t["artist"]), norm_title(t["title"]))
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


async def search_catalog(q: str, limit: int = 25) -> dict:
    """{tracks, source, error?} — tracks carry no library info; callers add it."""
    q = q.strip()
    key = (q.lower(), limit)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    error = None
    tracks: list[dict] = []
    source = "deezer"
    try:
        tracks = await _deezer_search(q, limit)
    except Exception as e:
        log.warning("Catalog: Deezer search failed for %r: %s", q, e)
        error = "Deezer search is unavailable"
    if not tracks:
        try:
            tracks = await _lastfm_search(q, limit)
            source = "lastfm"
        except Exception as e:
            log.warning("Catalog: Last.fm search failed for %r: %s", q, e)
            error = error or "Last.fm search is unavailable"

    result = {"tracks": _dedupe(tracks), "source": source}
    if error and not tracks:
        result["error"] = error
    else:
        _cache_put(key, result)  # don't cache outages
    return result
