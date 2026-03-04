"""Discovery API routes - Last.fm top tracks, similar artists/tracks, auth."""
from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, Query
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

    # Check which tracks are already in library
    for t in chart:
        result = await db.execute(
            select(Track).where(
                Track.title.ilike(f"%{t['name']}%"),
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

            # Check if in library
            existing = await db.execute(
                select(Track).where(Track.title.ilike(f"%{t['name']}%")).limit(1)
            )
            existing_track = existing.scalar_one_or_none()
            t["in_library"] = existing_track is not None
            t["track_id"] = existing_track.id if existing_track else None
            t["source_track"] = track_name
            t["source_artist"] = artist_name
            similar.append(t)

        if len(similar) >= limit:
            break

    return {
        "tracks": similar[:limit],
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
            select(Track).where(Track.title.ilike(f"%{t['name']}%")).limit(1)
        )
        existing_track = existing.scalar_one_or_none()
        t["in_library"] = existing_track is not None
        t["track_id"] = existing_track.id if existing_track else None

    return {
        "tracks": similar[:limit],
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
async def lastfm_auth_url():
    """Get the Last.fm auth URL for the user to visit."""
    settings = get_settings()
    api_key = settings.lastfm.write_api_key
    if not api_key:
        return {"error": "Last.fm write API key not configured"}
    return {"url": f"https://www.last.fm/api/auth/?api_key={api_key}"}


@router.get("/lastfm/callback")
async def lastfm_callback(token: str):
    """Exchange a Last.fm auth token for a session key."""
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
        return {
            "session_key": session["key"],
            "username": session.get("name", ""),
        }
    return {"error": data.get("message", "Authentication failed")}
