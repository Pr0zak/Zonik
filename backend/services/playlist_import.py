"""External playlist import — Spotify, Apple Music, Deezer.

Fetches playlist metadata and track lists from external services,
then matches against local library or triggers Soulseek downloads.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urlparse, parse_qs

import httpx

from backend.config import get_settings

_log = logging.getLogger(__name__)

# URL patterns for auto-detection
_SPOTIFY_RE = re.compile(r"open\.spotify\.com/playlist/([a-zA-Z0-9]+)")
_APPLE_RE = re.compile(r"music\.apple\.com/(\w+)/playlist/.+?/pl\.([a-zA-Z0-9]+)")
_DEEZER_RE = re.compile(r"deezer\.com/(?:\w+/)?playlist/(\d+)")


def detect_source(url: str) -> tuple[str, str] | None:
    """Detect playlist source and extract ID from URL.

    Returns (source, playlist_id) or None.
    """
    m = _SPOTIFY_RE.search(url)
    if m:
        return ("spotify", m.group(1))

    m = _APPLE_RE.search(url)
    if m:
        return ("apple_music", m.group(2))

    m = _DEEZER_RE.search(url)
    if m:
        return ("deezer", m.group(1))

    return None


# ---------- Spotify ----------

async def _spotify_get_token() -> str | None:
    """Get Spotify access token using client credentials flow."""
    settings = get_settings()
    client_id = settings.spotify.client_id
    client_secret = settings.spotify.client_secret
    if not client_id or not client_secret:
        return None

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://accounts.spotify.com/api/token",
            data={"grant_type": "client_credentials"},
            auth=(client_id, client_secret),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]


async def fetch_spotify_playlist(playlist_id: str) -> dict:
    """Fetch a Spotify playlist's metadata and tracks."""
    token = await _spotify_get_token()
    if not token:
        return {"error": "Spotify credentials not configured"}

    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"Bearer {token}"}

        # Get playlist metadata
        resp = await client.get(
            f"https://api.spotify.com/v1/playlists/{playlist_id}",
            headers=headers,
            params={"fields": "name,description,images,tracks.total,owner.display_name"},
            timeout=15,
        )
        resp.raise_for_status()
        meta = resp.json()

        # Get all tracks (paginated)
        tracks = []
        url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
        params = {"fields": "items(track(name,artists(name),album(name,images),duration_ms)),next", "limit": 100}

        while url and len(tracks) < 500:
            resp = await client.get(url, headers=headers, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("items", []):
                t = item.get("track")
                if not t or not t.get("name"):
                    continue
                tracks.append({
                    "title": t["name"],
                    "artist": ", ".join(a["name"] for a in t.get("artists", [])),
                    "album": t.get("album", {}).get("name", ""),
                    "duration_seconds": (t.get("duration_ms", 0) or 0) // 1000,
                    "image_url": (t.get("album", {}).get("images", [{}])[0].get("url", "")),
                })
            url = data.get("next")
            params = {}  # next URL includes params

    return {
        "source": "spotify",
        "id": playlist_id,
        "name": meta.get("name", ""),
        "description": meta.get("description", ""),
        "image_url": (meta.get("images", [{}])[0].get("url", "")),
        "owner": meta.get("owner", {}).get("display_name", ""),
        "track_count": meta.get("tracks", {}).get("total", len(tracks)),
        "tracks": tracks,
    }


async def search_spotify_playlists(query: str, limit: int = 10) -> list[dict]:
    """Search Spotify for playlists matching a query."""
    token = await _spotify_get_token()
    if not token:
        return []

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.spotify.com/v1/search",
            headers={"Authorization": f"Bearer {token}"},
            params={"q": query, "type": "playlist", "limit": limit},
            timeout=15,
        )
        resp.raise_for_status()
        items = resp.json().get("playlists", {}).get("items", [])

    return [
        {
            "source": "spotify",
            "id": p["id"],
            "name": p.get("name", ""),
            "description": p.get("description", ""),
            "image_url": (p.get("images", [{}])[0].get("url", "")),
            "owner": p.get("owner", {}).get("display_name", ""),
            "track_count": p.get("tracks", {}).get("total", 0),
        }
        for p in items if p
    ]


# ---------- Apple Music ----------

async def fetch_apple_music_playlist(playlist_id: str, storefront: str = "us") -> dict:
    """Fetch an Apple Music playlist (public API, no auth needed for catalog playlists)."""
    settings = get_settings()
    token = settings.apple_music.developer_token
    if not token:
        return {"error": "Apple Music developer token not configured"}

    async with httpx.AsyncClient() as client:
        headers = {"Authorization": f"Bearer {token}"}
        resp = await client.get(
            f"https://api.music.apple.com/v1/catalog/{storefront}/playlists/{playlist_id}",
            headers=headers,
            params={"include": "tracks"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [{}])[0]
        attrs = data.get("attributes", {})

        tracks = []
        for t in data.get("relationships", {}).get("tracks", {}).get("data", []):
            ta = t.get("attributes", {})
            artwork = ta.get("artwork", {})
            img = artwork.get("url", "").replace("{w}", "300").replace("{h}", "300") if artwork.get("url") else ""
            tracks.append({
                "title": ta.get("name", ""),
                "artist": ta.get("artistName", ""),
                "album": ta.get("albumName", ""),
                "duration_seconds": (ta.get("durationInMillis", 0) or 0) // 1000,
                "image_url": img,
            })

    artwork = attrs.get("artwork", {})
    img = artwork.get("url", "").replace("{w}", "300").replace("{h}", "300") if artwork.get("url") else ""

    return {
        "source": "apple_music",
        "id": playlist_id,
        "name": attrs.get("name", ""),
        "description": attrs.get("description", {}).get("standard", ""),
        "image_url": img,
        "owner": attrs.get("curatorName", ""),
        "track_count": len(tracks),
        "tracks": tracks,
    }


# ---------- Deezer ----------

async def fetch_deezer_playlist(playlist_id: str) -> dict:
    """Fetch a Deezer playlist (public API, no auth needed)."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.deezer.com/playlist/{playlist_id}",
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        if "error" in data:
            return {"error": data["error"].get("message", "Deezer API error")}

        tracks = []
        for t in data.get("tracks", {}).get("data", []):
            tracks.append({
                "title": t.get("title", ""),
                "artist": t.get("artist", {}).get("name", ""),
                "album": t.get("album", {}).get("title", ""),
                "duration_seconds": t.get("duration", 0),
                "image_url": t.get("album", {}).get("cover_medium", ""),
            })

    return {
        "source": "deezer",
        "id": playlist_id,
        "name": data.get("title", ""),
        "description": data.get("description", ""),
        "image_url": data.get("picture_medium", ""),
        "owner": data.get("creator", {}).get("name", ""),
        "track_count": data.get("nb_tracks", len(tracks)),
        "tracks": tracks,
    }


async def search_deezer_playlists(query: str, limit: int = 10) -> list[dict]:
    """Search Deezer for playlists."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.deezer.com/search/playlist",
            params={"q": query, "limit": limit},
            timeout=15,
        )
        resp.raise_for_status()
        items = resp.json().get("data", [])

    return [
        {
            "source": "deezer",
            "id": str(p["id"]),
            "name": p.get("title", ""),
            "description": "",
            "image_url": p.get("picture_medium", ""),
            "owner": p.get("user", {}).get("name", ""),
            "track_count": p.get("nb_tracks", 0),
        }
        for p in items
    ]


# ---------- Unified ----------

async def fetch_playlist(url_or_id: str, source: str | None = None) -> dict:
    """Fetch playlist from any supported source. Auto-detects from URL."""
    if not source:
        detected = detect_source(url_or_id)
        if not detected:
            return {"error": f"Could not detect playlist source from: {url_or_id}"}
        source, playlist_id = detected
    else:
        playlist_id = url_or_id

    if source == "spotify":
        return await fetch_spotify_playlist(playlist_id)
    elif source == "apple_music":
        return await fetch_apple_music_playlist(playlist_id)
    elif source == "deezer":
        return await fetch_deezer_playlist(playlist_id)
    else:
        return {"error": f"Unknown source: {source}"}


async def search_playlists(query: str, sources: list[str] | None = None, limit: int = 10) -> list[dict]:
    """Search for playlists across configured sources."""
    results = []
    sources = sources or ["spotify", "deezer"]  # Apple Music search requires different approach

    if "spotify" in sources:
        try:
            results.extend(await search_spotify_playlists(query, limit))
        except Exception as e:
            _log.warning(f"Spotify search failed: {e}")

    if "deezer" in sources:
        try:
            results.extend(await search_deezer_playlists(query, limit))
        except Exception as e:
            _log.warning(f"Deezer search failed: {e}")

    return results[:limit * 2]  # cap total results


async def match_tracks_to_library(tracks: list[dict], db) -> list[dict]:
    """Match imported tracks against local library.

    Returns tracks enriched with local_track_id (if matched) and in_library flag.
    """
    from sqlalchemy import select, func
    from backend.models.track import Track
    from backend.models.artist import Artist

    matched = 0
    for t in tracks:
        title = t.get("title", "").strip()
        artist = t.get("artist", "").strip()
        if not title:
            t["in_library"] = False
            continue

        # Exact match on title + artist
        stmt = (
            select(Track.id)
            .join(Artist, Track.artist_id == Artist.id, isouter=True)
            .where(
                func.lower(Track.title) == title.lower(),
                func.lower(Artist.name) == artist.lower(),
            )
            .limit(1)
        )
        result = await db.execute(stmt)
        row = result.scalar_one_or_none()

        if row:
            t["local_track_id"] = row
            t["in_library"] = True
            matched += 1
        else:
            t["in_library"] = False

    return tracks
