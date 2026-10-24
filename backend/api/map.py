"""Music Map API - graph data for library visualization."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, BackgroundTasks, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.services.user_data import caller_id

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
async def soundscape(request: Request, db: AsyncSession = Depends(get_db)):
    """Cached 2D sound projection + per-point metadata (parallel arrays). The play heat
    (play_count, skip_count, recency_days) is the caller's own listening."""
    from backend.services.soundscape import get_soundscape
    data = await get_soundscape(db)
    await _overlay_caller_heat(db, data, await caller_id(request, db))
    return data


async def _overlay_caller_heat(db: AsyncSession, data: dict, user_id: str | None) -> None:
    """Swap the soundscape's global play/skip/recency arrays (library totals, which the
    projection service keeps) for the caller's (multi-user P2)."""
    ids = data.get("ids")
    if not ids or user_id is None:
        return
    from datetime import datetime, timezone
    from backend.services.user_data import stats_for
    stats = await stats_for(db, user_id, ids)
    now = datetime.now(timezone.utc)
    plays, skips, recency = [], [], []
    for tid in ids:
        st = stats.get(tid)
        plays.append((st.play_count or 0) if st else 0)
        skips.append((st.skip_count or 0) if st else 0)
        lp = st.last_played_at if st else None
        if lp is not None:
            if lp.tzinfo is None:
                lp = lp.replace(tzinfo=timezone.utc)
            recency.append(round((now - lp).total_seconds() / 86400, 1))
        else:
            recency.append(None)
    data["play_count"], data["skip_count"], data["recency_days"] = plays, skips, recency


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
async def listening_clock(request: Request, db: AsyncSession = Depends(get_db)):
    """7×24 weekday×hour heatmap of when you listen (+ dominant genre per cell)."""
    from backend.services.insights import listening_clock as _clock
    return await _clock(db, user_id=await caller_id(request, db))


@router.get("/neglected-gems")
async def neglected_gems(request: Request, limit: int = Query(40, ge=1, le=120), db: AsyncSession = Depends(get_db)):
    """Owned-but-never-played tracks ranked by closeness to your taste centroid."""
    from backend.services.insights import neglected_gems as _gems
    return await _gems(db, limit=limit, user_id=await caller_id(request, db))


class DismissRequest(BaseModel):
    track_id: str


@router.post("/gems/dismiss")
async def gems_dismiss(req: DismissRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Never suggest this track to the caller as a neglected gem again."""
    from backend.services.insights import dismiss_gem
    return await dismiss_gem(db, req.track_id, user_id=await caller_id(request, db))


@router.get("/audio-features")
async def audio_features(request: Request, db: AsyncSession = Depends(get_db)):
    """Per-track Essentia features for the Camelot wheel + Tempo×Punch grid."""
    from backend.services.insights import audio_features as _af
    return await _af(db, user_id=await caller_id(request, db))


@router.get("/streak-calendar")
async def streak_calendar(request: Request, db: AsyncSession = Depends(get_db)):
    """Daily play counts for a GitHub-style listening-streak heatmap."""
    from backend.services.insights import streak_calendar as _sc
    return await _sc(db, user_id=await caller_id(request, db))


@router.post("/sonic-path")
async def sonic_path(req: PathRequest, db: AsyncSession = Depends(get_db)):
    """A queue that morphs from one track's sound to another's through CLAP space."""
    from backend.services.soundscape import sonic_path as _sp
    return await _sp(db, req.start_id, req.end_id, steps=max(3, min(req.steps, 30)))


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    """Gaps in the analysis pipeline that distort the map, each with a fix."""
    from backend.services.map_health import map_health
    return await map_health(db)


# --- Listening layers (plays over time, order, rotation) ---

@router.get("/taste-river")
async def taste_river(request: Request, weeks: int = Query(52, ge=4, le=156), db: AsyncSession = Depends(get_db)):
    """Plays per genre family per week."""
    from backend.services.listening import taste_river as _tr
    return await _tr(db, weeks=weeks, user_id=await caller_id(request, db))


@router.get("/genre-flow")
async def genre_flow(request: Request, days: int = Query(90, ge=7, le=730), db: AsyncSession = Depends(get_db)):
    """Which genre family you play after each one, within a session."""
    from backend.services.listening import genre_flow as _gf
    return await _gf(db, days=days, user_id=await caller_id(request, db))


@router.get("/rotation")
async def rotation(request: Request, days: int = Query(30, ge=7, le=180), db: AsyncSession = Depends(get_db)):
    """Tracks by plays this period against the period before, with trend flags."""
    from backend.services.listening import rotation as _rot
    return await _rot(db, days=days, user_id=await caller_id(request, db))


@router.get("/trail")
async def trail(request: Request, hours: int = Query(0, ge=0, le=24 * 30), db: AsyncSession = Depends(get_db)):
    """Plays in order since midnight (hours=0) or the last N hours, plus now playing and the saved queue."""
    from backend.services.listening import trail as _trail
    return await _trail(db, hours=hours, user_id=await caller_id(request, db))


@router.get("/track/{track_id}/listening")
async def track_listening(track_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """One track's plays per month, devices, skips and what you usually play after it."""
    from fastapi import HTTPException
    from backend.services.listening import track_listening as _tl
    r = await _tl(db, track_id, user_id=await caller_id(request, db))
    if r is None:
        raise HTTPException(404, "Track not found")
    return r
