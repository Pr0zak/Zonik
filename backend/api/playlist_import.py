"""Playlist import API — fetch, search, and import external playlists."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Request
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
async def import_playlist(req: ImportRequest, background_tasks: BackgroundTasks, request: Request,
                          db: AsyncSession = Depends(get_db)):
    """Create a local playlist from imported tracks.

    Only includes tracks that are in the library. Optionally downloads missing tracks.
    """
    from backend.models.playlist import Playlist, PlaylistTrack
    from backend.services.playlist_import import match_tracks_to_library
    from backend.services.user_data import caller_id

    # Match tracks to library
    matched_tracks = await match_tracks_to_library(req.tracks, db)

    # Create playlist with matched tracks
    playlist_id = str(uuid.uuid4())
    # Owned by whoever imported it. (`comment`: Playlist has no `description` column, so
    # the old keyword made every import fail with a TypeError.)
    playlist = Playlist(
        id=playlist_id,
        name=req.name,
        user_id=await caller_id(request, db),
        comment=f"Imported playlist ({sum(1 for t in matched_tracks if t.get('in_library'))} of {len(matched_tracks)} tracks matched)",
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

    # Optionally download the missing tracks — in the background, through the tracked
    # path (backoff, duration gate, outcome recorded), a few at a time.
    download_jobs = 0
    if req.download_missing:
        items = []
        for t in matched_tracks:
            if not t.get("in_library") and t.get("title") and t.get("artist"):
                dur = t.get("duration_seconds")
                items.append({
                    "artist": t["artist"], "track": t["title"],
                    "expected_duration": int(round(dur)) if isinstance(dur, (int, float)) and dur > 0 else None,
                })
        if items:
            from backend.services.auto_download import download_tracked_many
            background_tasks.add_task(download_tracked_many, items, source="playlist",
                                      label=req.name or "Playlist import", kind="playlist")
        download_jobs = len(items)

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
async def ai_review_import(req: AIReviewRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """AI review of imported tracks for compatibility with the caller's taste."""
    from backend.services.ai.playlist_curator import review_import
    from backend.services.recommender import build_taste_profile
    from backend.services.user_data import caller_id

    profile = await build_taste_profile(db, await caller_id(request, db))
    summary = f"Top genres: {', '.join(g['name'] for g in profile.get('genres', [])[:5])}. " \
              f"Top artists: {', '.join(a['name'] for a in profile.get('top_artists', [])[:5])}."

    return await review_import(req.tracks, summary)
