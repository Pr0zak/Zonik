"""Last.fm API service - read and write API with rate limiting."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import urllib.parse

import httpx

from backend.config import get_settings

log = logging.getLogger(__name__)

LASTFM_BASE = "https://ws.audioscrobbler.com/2.0/"

# Async rate limiter
_last_call: float = 0
_rate_lock = asyncio.Lock()


async def _rate_limit(min_interval: float = 0.35):
    """Async rate limiter for Last.fm API."""
    global _last_call
    async with _rate_lock:
        now = time.time()
        wait = min_interval - (now - _last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call = time.time()


async def lastfm_api(method: str, params: dict | None = None) -> dict | None:
    """Make a Last.fm read API call."""
    await _rate_limit()
    settings = get_settings()
    p = {"method": method, "api_key": settings.lastfm.api_key, "format": "json"}
    if params:
        p.update(params)

    url = f"{LASTFM_BASE}?{urllib.parse.urlencode(p)}"

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.get(url)
            if resp.status_code == 429:
                log.warning("Last.fm rate limited, backing off 5s")
                await asyncio.sleep(5)
                return None
            if resp.status_code != 200:
                return None
            return resp.json()
        except Exception as e:
            log.warning(f"Last.fm API error: {e}")
            return None


def _api_sig(params: dict) -> str:
    """Generate Last.fm API method signature for write calls."""
    settings = get_settings()
    sorted_params = sorted(params.items())
    sig_string = "".join(f"{k}{v}" for k, v in sorted_params) + settings.lastfm.write_api_secret
    return hashlib.md5(sig_string.encode()).hexdigest()


async def lastfm_write(method: str, params: dict, session_key: str) -> dict:
    """Make an authenticated Last.fm write API call (POST, returns XML)."""
    await _rate_limit()
    settings = get_settings()
    p = dict(params)
    p["method"] = method
    p["api_key"] = settings.lastfm.write_api_key
    p["sk"] = session_key
    p["api_sig"] = _api_sig(p)

    data = urllib.parse.urlencode(p).encode()

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.post(LASTFM_BASE, content=data,
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
            body = resp.text
            if 'status="ok"' in body:
                return {"status": "ok"}
            return {"error": True, "message": body[:200]}
        except Exception as e:
            return {"error": True, "message": str(e)}


# --- High-level API methods ---

async def get_top_tracks(limit: int = 50, page: int = 1) -> list[dict]:
    """Get Last.fm global top tracks chart."""
    data = await lastfm_api("chart.getTopTracks", {"limit": str(limit), "page": str(page)})
    if not data or "tracks" not in data:
        return []
    tracks = data["tracks"].get("track", [])
    return [
        {
            "name": t.get("name", ""),
            "artist": t.get("artist", {}).get("name", ""),
            "playcount": int(t.get("playcount", 0)),
            "listeners": int(t.get("listeners", 0)),
            "url": t.get("url", ""),
        }
        for t in tracks
    ]


async def get_similar_tracks(artist: str, track: str, limit: int = 20) -> list[dict]:
    """Get tracks similar to a given track."""
    data = await lastfm_api("track.getSimilar", {
        "artist": artist, "track": track, "limit": str(limit),
    })
    if not data or "similartracks" not in data:
        return []
    tracks = data["similartracks"].get("track", [])
    return [
        {
            "name": t.get("name", ""),
            "artist": t.get("artist", {}).get("name", ""),
            "match": float(t.get("match", 0)),
        }
        for t in tracks
    ]


async def get_similar_artists(artist: str, limit: int = 20) -> list[dict]:
    """Get artists similar to a given artist."""
    data = await lastfm_api("artist.getSimilar", {"artist": artist, "limit": str(limit)})
    if not data or "similarartists" not in data:
        return []
    artists = data["similarartists"].get("artist", [])
    return [
        {
            "name": a.get("name", ""),
            "match": float(a.get("match", 0)),
            "url": a.get("url", ""),
        }
        for a in artists
    ]


async def get_artist_top_albums(artist: str, limit: int = 10) -> list[dict]:
    """Get top albums for an artist."""
    data = await lastfm_api("artist.getTopAlbums", {"artist": artist, "limit": str(limit)})
    if not data or "topalbums" not in data:
        return []
    albums = data["topalbums"].get("album", [])
    return [
        {
            "name": a.get("name", ""),
            "artist": a.get("artist", {}).get("name", ""),
            "playcount": int(a.get("playcount", 0)),
            "image": next((i["#text"] for i in a.get("image", []) if i.get("size") == "large"), ""),
        }
        for a in albums
    ]


async def get_track_info(artist: str, track: str) -> dict | None:
    """Get detailed track info from Last.fm."""
    data = await lastfm_api("track.getInfo", {"artist": artist, "track": track})
    if not data or "track" not in data:
        return None
    t = data["track"]
    tags = [tag.get("name", "") for tag in t.get("toptags", {}).get("tag", [])]
    return {
        "name": t.get("name", ""),
        "artist": t.get("artist", {}).get("name", ""),
        "album": t.get("album", {}).get("title", "") if t.get("album") else "",
        "duration_ms": int(t.get("duration", 0)),
        "listeners": int(t.get("listeners", 0)),
        "playcount": int(t.get("playcount", 0)),
        "tags": tags,
        "url": t.get("url", ""),
        "mbid": t.get("mbid", ""),
    }


async def get_artist_info(artist: str) -> dict | None:
    """Get detailed artist info from Last.fm."""
    data = await lastfm_api("artist.getInfo", {"artist": artist})
    if not data or "artist" not in data:
        return None
    a = data["artist"]
    tags = [tag.get("name", "") for tag in a.get("tags", {}).get("tag", [])]
    return {
        "name": a.get("name", ""),
        "mbid": a.get("mbid", ""),
        "url": a.get("url", ""),
        "listeners": int(a.get("stats", {}).get("listeners", 0)),
        "playcount": int(a.get("stats", {}).get("playcount", 0)),
        "tags": tags,
        "bio": a.get("bio", {}).get("summary", ""),
        "similar": [s.get("name", "") for s in a.get("similar", {}).get("artist", [])],
        "image": next((i["#text"] for i in a.get("image", []) if i.get("size") == "large"), ""),
    }


async def love_track(artist: str, track: str, session_key: str) -> dict:
    """Love a track on Last.fm."""
    return await lastfm_write("track.love", {"artist": artist, "track": track}, session_key)


async def unlove_track(artist: str, track: str, session_key: str) -> dict:
    """Unlove a track on Last.fm."""
    return await lastfm_write("track.unlove", {"artist": artist, "track": track}, session_key)


async def scrobble_track(artist: str, track: str, timestamp: int, session_key: str, album: str = "") -> dict:
    """Scrobble a track to Last.fm."""
    params = {"artist": artist, "track": track, "timestamp": str(timestamp)}
    if album:
        params["album"] = album
    return await lastfm_write("track.scrobble", params, session_key)
