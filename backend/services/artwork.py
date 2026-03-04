"""Multi-source cover art fetcher: Deezer > Cover Art Archive > iTunes > Last.fm."""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import httpx

from backend.config import get_settings

log = logging.getLogger(__name__)


async def fetch_cover_art(artist: str, album: str | None = None, track: str | None = None) -> bytes | None:
    """Try multiple sources to find cover art. Returns image bytes or None."""
    # Try Deezer first
    art = await _deezer_cover(artist, album, track)
    if art:
        return art

    # Try Cover Art Archive (MusicBrainz) if we have an album
    if album:
        art = await _coverartarchive_cover(artist, album)
        if art:
            return art

    # Try iTunes
    art = await _itunes_cover(artist, album, track)
    if art:
        return art

    # Try Last.fm
    art = await _lastfm_cover(artist, album, track)
    if art:
        return art

    return None


async def fetch_and_cache_cover(artist: str, album: str | None = None, track: str | None = None) -> str | None:
    """Fetch cover art and save to cache. Returns cached path or None."""
    art_data = await fetch_cover_art(artist, album, track)
    if not art_data:
        return None

    settings = get_settings()
    cache_dir = Path(settings.library.cover_cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    art_hash = hashlib.md5(art_data).hexdigest()
    ext = "jpg"
    if art_data[:8] == b"\x89PNG\r\n\x1a\n":
        ext = "png"
    art_path = cache_dir / f"{art_hash}.{ext}"
    if not art_path.exists():
        art_path.write_bytes(art_data)

    return str(art_path)


async def _deezer_cover(artist: str, album: str | None, track: str | None) -> bytes | None:
    """Fetch cover from Deezer API."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            query = f'artist:"{artist}"'
            if album:
                query += f' album:"{album}"'
            elif track:
                query += f' track:"{track}"'

            resp = await client.get(
                "https://api.deezer.com/search",
                params={"q": query, "limit": 1},
            )
            if resp.status_code != 200:
                return None

            data = resp.json()
            tracks = data.get("data", [])
            if not tracks:
                return None

            # Get album cover (large)
            album_data = tracks[0].get("album", {})
            cover_url = album_data.get("cover_xl") or album_data.get("cover_big") or album_data.get("cover_medium")
            if not cover_url:
                return None

            img_resp = await client.get(cover_url)
            if img_resp.status_code == 200 and len(img_resp.content) > 1000:
                return img_resp.content
    except Exception as e:
        log.debug(f"Deezer cover fetch failed: {e}")
    return None


async def _coverartarchive_cover(artist: str, album: str) -> bytes | None:
    """Fetch cover from MusicBrainz Cover Art Archive."""
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            # Search MusicBrainz for release
            resp = await client.get(
                "https://musicbrainz.org/ws/2/release",
                params={
                    "query": f'artist:"{artist}" AND release:"{album}"',
                    "limit": 1, "fmt": "json",
                },
                headers={"User-Agent": "Zonik/0.1.0 (music backend)"},
            )
            if resp.status_code != 200:
                return None

            releases = resp.json().get("releases", [])
            if not releases:
                return None

            mbid = releases[0].get("id")
            if not mbid:
                return None

            # Fetch cover from CAA
            img_resp = await client.get(f"https://coverartarchive.org/release/{mbid}/front-500")
            if img_resp.status_code == 200 and len(img_resp.content) > 1000:
                return img_resp.content
    except Exception as e:
        log.debug(f"Cover Art Archive fetch failed: {e}")
    return None


async def _itunes_cover(artist: str, album: str | None, track: str | None) -> bytes | None:
    """Fetch cover from iTunes Search API."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            term = f"{artist} {album or track or ''}"
            resp = await client.get(
                "https://itunes.apple.com/search",
                params={"term": term, "media": "music", "limit": 1},
            )
            if resp.status_code != 200:
                return None

            results = resp.json().get("results", [])
            if not results:
                return None

            art_url = results[0].get("artworkUrl100", "")
            if not art_url:
                return None
            # Get higher resolution
            art_url = art_url.replace("100x100", "600x600")

            img_resp = await client.get(art_url)
            if img_resp.status_code == 200 and len(img_resp.content) > 1000:
                return img_resp.content
    except Exception as e:
        log.debug(f"iTunes cover fetch failed: {e}")
    return None


async def _lastfm_cover(artist: str, album: str | None, track: str | None) -> bytes | None:
    """Fetch cover from Last.fm."""
    try:
        from backend.services.lastfm import lastfm_api

        if album:
            data = await lastfm_api("album.getInfo", {"artist": artist, "album": album})
            images = data.get("album", {}).get("image", []) if data else []
        elif track:
            data = await lastfm_api("track.getInfo", {"artist": artist, "track": track})
            images = data.get("track", {}).get("album", {}).get("image", []) if data else []
        else:
            return None

        # Get largest image
        url = ""
        for img in reversed(images):
            if img.get("#text"):
                url = img["#text"]
                break

        if not url:
            return None

        async with httpx.AsyncClient(timeout=10) as client:
            img_resp = await client.get(url)
            if img_resp.status_code == 200 and len(img_resp.content) > 1000:
                return img_resp.content
    except Exception as e:
        log.debug(f"Last.fm cover fetch failed: {e}")
    return None
