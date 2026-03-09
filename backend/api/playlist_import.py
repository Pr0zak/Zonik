"""Playlist import API — fetch, search, and import external playlists."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db

router = APIRouter()


class FetchRequest(BaseModel):
    url: str
    source: str | None = None


class SearchRequest(BaseModel):
    query: str
    sources: list[str] | None = None
    limit: int = 10


class ImportRequest(BaseModel):
    name: str
    tracks: list[dict]  # [{title, artist, album?, duration_seconds?}]
    download_missing: bool = False


@router.post("/fetch")
async def fetch_playlist(req: FetchRequest, db: AsyncSession = Depends(get_db)):
    """Fetch a playlist by URL (auto-detects Spotify, Apple Music, Deezer)."""
    from backend.services.playlist_import import fetch_playlist, match_tracks_to_library

    result = await fetch_playlist(req.url, req.source)
    if "error" in result:
        return result

    # Match tracks against library
    result["tracks"] = await match_tracks_to_library(result["tracks"], db)
    result["matched_count"] = sum(1 for t in result["tracks"] if t.get("in_library"))

    return result


@router.post("/search")
async def search_playlists(req: SearchRequest):
    """Search for playlists across external services."""
    from backend.services.playlist_import import search_playlists
    results = await search_playlists(req.query, req.sources, req.limit)
    return {"results": results}


@router.post("/import")
async def import_playlist(req: ImportRequest, db: AsyncSession = Depends(get_db)):
    """Create a local playlist from imported tracks.

    Only includes tracks that are in the library. Optionally downloads missing tracks.
    """
    from backend.models.playlist import Playlist, PlaylistTrack
    from backend.services.playlist_import import match_tracks_to_library

    # Match tracks to library
    matched_tracks = await match_tracks_to_library(req.tracks, db)

    # Create playlist with matched tracks
    playlist_id = str(uuid.uuid4())
    playlist = Playlist(
        id=playlist_id,
        name=req.name,
        description=f"Imported playlist ({sum(1 for t in matched_tracks if t.get('in_library'))} of {len(matched_tracks)} tracks matched)",
        created_at=datetime.utcnow(),
    )
    db.add(playlist)

    position = 0
    for t in matched_tracks:
        if t.get("in_library") and t.get("local_track_id"):
            db.add(PlaylistTrack(
                id=str(uuid.uuid4()),
                playlist_id=playlist_id,
                track_id=t["local_track_id"],
                position=position,
            ))
            position += 1

    await db.commit()

    # Optionally trigger downloads for missing tracks
    download_jobs = 0
    if req.download_missing:
        from backend.api.download import enqueue_download
        for t in matched_tracks:
            if not t.get("in_library") and t.get("title") and t.get("artist"):
                try:
                    await enqueue_download(t["artist"], t["title"])
                    download_jobs += 1
                except Exception:
                    pass

    return {
        "playlist_id": playlist_id,
        "name": req.name,
        "matched": position,
        "total": len(matched_tracks),
        "download_jobs": download_jobs,
    }


class AIReviewRequest(BaseModel):
    tracks: list[dict]


@router.post("/ai-review")
async def ai_review_import(req: AIReviewRequest, db: AsyncSession = Depends(get_db)):
    """AI review of imported tracks for taste compatibility."""
    from backend.services.ai.playlist_curator import review_import
    from backend.services.recommender import build_taste_profile

    profile = await build_taste_profile(db)
    summary = f"Top genres: {', '.join(g['name'] for g in profile.get('genres', [])[:5])}. " \
              f"Top artists: {', '.join(a['name'] for a in profile.get('top_artists', [])[:5])}."

    return await review_import(req.tracks, summary)
