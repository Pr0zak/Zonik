"""Music Map API - graph data for library visualization."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db

router = APIRouter()


@router.get("/graph")
async def get_graph(
    max_artists: int = Query(200, le=500),
    min_genre_tracks: int = Query(3, ge=1),
    include_tracks: bool = Query(False),
    max_tracks_per_artist: int = Query(50, le=100),
    layout: str = Query("force"),
    similarity_threshold: float = Query(0.7, ge=0.0, le=1.0),
    db: AsyncSession = Depends(get_db),
):
    """Get graph data for the Music Map visualization."""
    from backend.services.graph_builder import build_graph
    return await build_graph(
        db,
        max_artists=max_artists,
        min_genre_tracks=min_genre_tracks,
        include_tracks=include_tracks,
        max_tracks_per_artist=max_tracks_per_artist,
        layout=layout,
        similarity_threshold=similarity_threshold,
    )


# --- Sound Atlas (per-track CLAP projection) ---

class LocateRequest(BaseModel):
    query: str
    k: int = 12


class PathRequest(BaseModel):
    start_id: str
    end_id: str
    steps: int = 12


@router.get("/soundscape")
async def soundscape(db: AsyncSession = Depends(get_db)):
    """Cached 2D sound projection + per-point metadata (parallel arrays)."""
    from backend.services.soundscape import get_soundscape
    return await get_soundscape(db)


@router.post("/soundscape/recompute")
async def soundscape_recompute(background_tasks: BackgroundTasks):
    """Kick off a (re)projection in the background (~1-2 min). Poll GET /soundscape."""
    from backend.services.soundscape import compute_soundscape, is_computing
    if is_computing():
        return {"status": "already_running"}

    async def _run():
        from backend.database import async_session
        async with async_session() as db:
            await compute_soundscape(db)

    background_tasks.add_task(_run)
    return {"status": "started"}


@router.post("/soundscape/locate")
async def soundscape_locate(req: LocateRequest, db: AsyncSession = Depends(get_db)):
    """Locate a text vibe ('rainy lo-fi jazz') on the map + return nearest tracks."""
    from backend.services.soundscape import locate_text
    return await locate_text(db, req.query, k=max(1, min(req.k, 50)))


@router.get("/listening-clock")
async def listening_clock(db: AsyncSession = Depends(get_db)):
    """7×24 weekday×hour heatmap of when you listen (+ dominant genre per cell)."""
    from backend.services.insights import listening_clock as _clock
    return await _clock(db)


@router.get("/neglected-gems")
async def neglected_gems(limit: int = Query(40, ge=1, le=120), db: AsyncSession = Depends(get_db)):
    """Owned-but-never-played tracks ranked by closeness to your taste centroid."""
    from backend.services.insights import neglected_gems as _gems
    return await _gems(db, limit=limit)


@router.get("/audio-features")
async def audio_features(db: AsyncSession = Depends(get_db)):
    """Per-track Essentia features for the Camelot wheel + Tempo×Punch grid."""
    from backend.services.insights import audio_features as _af
    return await _af(db)


@router.get("/streak-calendar")
async def streak_calendar(db: AsyncSession = Depends(get_db)):
    """Daily play counts for a GitHub-style listening-streak heatmap."""
    from backend.services.insights import streak_calendar as _sc
    return await _sc(db)


@router.post("/sonic-path")
async def sonic_path(req: PathRequest, db: AsyncSession = Depends(get_db)):
    """A queue that morphs from one track's sound to another's through CLAP space."""
    from backend.services.soundscape import sonic_path as _sp
    return await _sp(db, req.start_id, req.end_id, steps=max(3, min(req.steps, 30)))
