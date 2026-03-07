"""Discovery API routes - Last.fm top tracks, similar artists/tracks, auth."""
from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.config import get_settings
from backend.database import get_db
from backend.models.track import Track
from backend.models.artist import Artist
from backend.models.favorite import Favorite
from backend.services import lastfm
from backend.services.soulseek import normalize_text

router = APIRouter()


@router.get("/top-tracks")
async def top_tracks(
    limit: int = Query(50, le=200),
    page: int = 1,
    db: AsyncSession = Depends(get_db),
):
    """Get Last.fm top tracks chart, annotated with library presence."""
    chart = await lastfm.get_top_tracks(limit=limit, page=page)

    # Check which tracks are already in library (match both artist + title)
    for t in chart:
        result = await db.execute(
            select(Track).join(Artist, Track.artist_id == Artist.id).where(
                Track.title.ilike(t["name"]),
                Artist.name.ilike(t["artist"]),
            ).limit(1)
        )
        existing = result.scalar_one_or_none()
        t["in_library"] = existing is not None
        t["track_id"] = existing.id if existing else None

    return {
        "tracks": chart,
        "total": len(chart),
        "in_library": sum(1 for t in chart if t["in_library"]),
        "missing": sum(1 for t in chart if not t["in_library"]),
    }


@router.get("/similar-tracks")
async def similar_tracks(
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Get tracks similar to starred tracks via Last.fm."""
    # Get starred tracks
    result = await db.execute(
        select(Favorite)
        .options(selectinload(Favorite.track).selectinload(Track.artist))
        .where(Favorite.track_id.isnot(None))
        .limit(20)
    )
    favorites = result.scalars().all()

    similar = []
    seen: set[str] = set()

    for fav in favorites:
        if not fav.track or not fav.track.artist:
            continue
        artist_name = fav.track.artist.name
        track_name = fav.track.title

        tracks = await lastfm.get_similar_tracks(artist_name, track_name, limit=5)
        for t in tracks:
            key = normalize_text(f"{t['artist']} {t['name']}")
            if key in seen:
                continue
            seen.add(key)
            t["source_track"] = track_name
            t["source_artist"] = artist_name
            similar.append(t)

        if len(similar) >= limit:
            break

    similar = similar[:limit]

    # Batch library match — single query for all similar tracks
    if similar:
        from sqlalchemy import or_, and_, func as sqfunc
        conditions = [
            and_(
                sqfunc.lower(Track.title) == t["name"].lower(),
                sqfunc.lower(Artist.name) == t["artist"].lower(),
            )
            for t in similar
        ]
        lib_result = await db.execute(
            select(Track.id, sqfunc.lower(Track.title), sqfunc.lower(Artist.name))
            .join(Artist, Track.artist_id == Artist.id)
            .where(or_(*conditions))
        )
        lib_map = {(title, artist): track_id for track_id, title, artist in lib_result.all()}

        for t in similar:
            key = (t["name"].lower(), t["artist"].lower())
            matched_id = lib_map.get(key)
            t["in_library"] = matched_id is not None
            t["track_id"] = matched_id

    return {
        "tracks": similar,
        "total": len(similar),
        "from_favorites": len(favorites),
    }


@router.get("/similar-artists")
async def similar_artists(
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Get artists similar to starred artists/tracks."""
    # Get unique artists from favorites
    result = await db.execute(
        select(Favorite)
        .options(selectinload(Favorite.track).selectinload(Track.artist))
        .where(Favorite.track_id.isnot(None))
    )
    favorites = result.scalars().all()

    fav_artists: set[str] = set()
    for fav in favorites:
        if fav.track and fav.track.artist:
            fav_artists.add(fav.track.artist.name)

    # Get existing artist names in library
    lib_result = await db.execute(select(Artist.name))
    library_artists = {r[0].lower() for r in lib_result.all()}

    similar = []
    seen: set[str] = set()
    artist_scores: dict[str, float] = {}

    for artist_name in list(fav_artists)[:15]:
        artists = await lastfm.get_similar_artists(artist_name, limit=10)
        for a in artists:
            key = a["name"].lower()
            if key in seen:
                artist_scores[key] = artist_scores.get(key, 0) + a["match"]
                continue
            seen.add(key)
            a["in_library"] = key in library_artists
            a["source_artist"] = artist_name
            artist_scores[key] = a["match"]
            similar.append(a)

    # Sort by cumulative match score
    similar.sort(key=lambda a: artist_scores.get(a["name"].lower(), 0), reverse=True)

    return {
        "artists": similar[:limit],
        "total": len(similar),
        "from_favorites": len(fav_artists),
    }


@router.get("/search")
async def discovery_search(
    q: str = Query("", min_length=1),
    limit: int = Query(30, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Search Last.fm for tracks and annotate with library presence."""
    from sqlalchemy import or_, and_, func as sqfunc

    # Try "Artist - Track" split first for artist top tracks
    parts = [p.strip() for p in q.split(" - ", 1)]
    if len(parts) == 2 and parts[0] and parts[1]:
        # Search for specific track + similar
        tracks = await lastfm.search_tracks(q, limit=limit)
    else:
        # General search — combine track search + artist top tracks
        tracks = await lastfm.search_tracks(q, limit=limit)
        # Also try as artist name for top tracks
        artist_tracks = await lastfm.get_artist_top_tracks(q, limit=min(limit, 20))
        # Merge, avoiding duplicates
        seen = {normalize_text(f"{t['artist']} {t['name']}") for t in tracks}
        for t in artist_tracks:
            key = normalize_text(f"{t['artist']} {t['name']}")
            if key not in seen:
                seen.add(key)
                tracks.append(t)

    tracks = tracks[:limit]

    # Batch library match
    if tracks:
        conditions = [
            and_(
                sqfunc.lower(Track.title) == t["name"].lower(),
                sqfunc.lower(Artist.name) == t["artist"].lower(),
            )
            for t in tracks
        ]
        lib_result = await db.execute(
            select(Track.id, sqfunc.lower(Track.title), sqfunc.lower(Artist.name))
            .join(Artist, Track.artist_id == Artist.id)
            .where(or_(*conditions))
        )
        lib_map = {(title, artist): track_id for track_id, title, artist in lib_result.all()}

        for t in tracks:
            key = (t["name"].lower(), t["artist"].lower())
            matched_id = lib_map.get(key)
            t["in_library"] = matched_id is not None
            t["track_id"] = matched_id
    else:
        for t in tracks:
            t["in_library"] = False
            t["track_id"] = None

    return {
        "tracks": tracks,
        "total": len(tracks),
        "in_library": sum(1 for t in tracks if t.get("in_library")),
        "missing": sum(1 for t in tracks if not t.get("in_library")),
    }


@router.get("/top-albums")
async def discover_albums(
    artist: str,
    limit: int = Query(10, le=50),
):
    """Get top albums for an artist from Last.fm."""
    albums = await lastfm.get_artist_top_albums(artist, limit=limit)
    return {"albums": albums}


@router.get("/track-info")
async def track_info(artist: str, track: str):
    """Get detailed track info from Last.fm."""
    info = await lastfm.get_track_info(artist, track)
    if not info:
        return {"error": "Track not found on Last.fm"}
    return info


@router.get("/similar-by-track")
async def similar_by_track(
    artist: str,
    track: str,
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Get tracks similar to a specific track via Last.fm, annotated with library status."""
    similar = await lastfm.get_similar_tracks(artist, track, limit=limit)

    for t in similar:
        existing = await db.execute(
            select(Track).join(Artist, Track.artist_id == Artist.id).where(
                Track.title.ilike(t["name"]),
                Artist.name.ilike(t["artist"]),
            ).limit(1)
        )
        existing_track = existing.scalar_one_or_none()
        t["in_library"] = existing_track is not None
        t["track_id"] = existing_track.id if existing_track else None

    return {
        "tracks": similar[:limit],
        "source_artist": artist,
        "source_track": track,
    }


@router.get("/remixes")
async def find_remixes(
    artist: str,
    track: str,
    limit: int = Query(30, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Find remixes, dubs, and edits of a track via Last.fm search."""
    from backend.services.remix_discovery import find_remixes as _find_remixes

    remixes = await _find_remixes(artist, track, limit=limit)

    # Annotate with library status
    for r in remixes:
        existing = await db.execute(
            select(Track).join(Artist, Track.artist_id == Artist.id).where(
                Track.title.ilike(r["name"]),
                Artist.name.ilike(r["artist"]),
            ).limit(1)
        )
        existing_track = existing.scalar_one_or_none()
        r["in_library"] = existing_track is not None
        r["track_id"] = existing_track.id if existing_track else None

    return {
        "remixes": remixes,
        "source_artist": artist,
        "source_track": track,
    }


@router.get("/artist-info")
async def artist_info(artist: str):
    """Get detailed artist info from Last.fm."""
    info = await lastfm.get_artist_info(artist)
    if not info:
        return {"error": "Artist not found on Last.fm"}
    return info


# --- Last.fm Authentication ---

@router.get("/lastfm/auth-url")
async def lastfm_auth_url(request: Request):
    """Get the Last.fm auth URL for the user to visit."""
    settings = get_settings()
    api_key = settings.lastfm.write_api_key
    if not api_key:
        return {"error": "Last.fm write API key not configured"}
    # Build callback URL so Last.fm redirects back automatically
    cb = f"{request.base_url}api/discovery/lastfm/callback"
    return {"url": f"https://www.last.fm/api/auth/?api_key={api_key}&cb={cb}"}


@router.get("/lastfm/callback")
async def lastfm_callback(token: str, request: Request):
    """Exchange a Last.fm auth token for a session key."""
    from fastapi.responses import RedirectResponse
    settings = get_settings()
    api_key = settings.lastfm.write_api_key
    secret = settings.lastfm.write_api_secret

    if not api_key or not secret:
        return {"error": "Last.fm write credentials not configured"}

    params = {
        "method": "auth.getSession",
        "api_key": api_key,
        "token": token,
    }
    sig_string = "".join(f"{k}{v}" for k, v in sorted(params.items())) + secret
    params["api_sig"] = hashlib.md5(sig_string.encode()).hexdigest()
    params["format"] = "json"

    import httpx
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get("https://ws.audioscrobbler.com/2.0/", params=params)
        data = resp.json()

    session = data.get("session", {})
    if session.get("key"):
        # Persist session key to config
        from backend.api.config_api import _read_raw_config, _write_config
        raw = _read_raw_config()
        if "lastfm" not in raw:
            raw["lastfm"] = {}
        raw["lastfm"]["session_key"] = session["key"]
        raw["lastfm"]["username"] = session.get("name", "")
        _write_config(raw)
        # If browser redirect (from Last.fm cb), redirect to settings page
        if request.headers.get("accept", "").startswith("text/html"):
            return RedirectResponse(url="/settings?lastfm_auth=ok")
        return {
            "session_key": session["key"],
            "username": session.get("name", ""),
        }
    # If browser redirect with error, redirect with error param
    if request.headers.get("accept", "").startswith("text/html"):
        return RedirectResponse(url="/settings?lastfm_auth=failed")
    return {"error": data.get("message", "Authentication failed")}


class ArtworkBatchRequest(BaseModel):
    items: list[dict]  # [{artist, track}]


@router.post("/artwork/batch")
async def get_artwork_batch(req: ArtworkBatchRequest):
    """Batch fetch artwork from iTunes Search API (up to 100 items, 10 concurrent)."""
    import asyncio
    import httpx
    import urllib.parse

    items = req.items[:100]
    results = {}
    sem = asyncio.Semaphore(10)

    async def fetch_one(client, item):
        artist = item.get("artist", "")
        track = item.get("track", "")
        key = f"{artist}::{track}".lower()
        async with sem:
            try:
                q = urllib.parse.quote(f"{artist} {track}")
                url = f"https://itunes.apple.com/search?term={q}&media=music&entity=song&limit=1"
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("results"):
                        r = data["results"][0]
                        results[key] = {
                            "image": (r.get("artworkUrl100") or "").replace("100x100", "60x60"),
                            "preview": r.get("previewUrl"),
                        }
                        return
            except Exception:
                pass
            results[key] = {"image": None, "preview": None}

    async with httpx.AsyncClient(timeout=10) as client:
        await asyncio.gather(*[fetch_one(client, item) for item in items])

    return {"results": results}
