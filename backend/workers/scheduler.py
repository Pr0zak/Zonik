"""Scheduled task definitions and execution."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models.job import Job
from backend.models.schedule import ScheduleTask
from backend.models.track import Track
from backend.models.favorite import Favorite
from backend.models.playlist import Playlist, PlaylistTrack

log = logging.getLogger(__name__)


async def run_task(task_name: str, db: AsyncSession):
    """Execute a scheduled task by name."""
    job_id = str(uuid.uuid4())
    job = Job(
        id=job_id, type=task_name, card="sched", status="running",
        started_at=datetime.utcnow(),
    )
    db.add(job)
    await db.commit()

    try:
        if task_name == "library_scan":
            from backend.services.scanner import scan_library
            result = await scan_library(db)
            job.result = json.dumps(result)

        elif task_name == "enrichment":
            from backend.services.enrichment import enrich_batch
            tracks = (await db.execute(
                select(Track.id)
                .where((Track.genre.is_(None)) | (Track.cover_art_path.is_(None)))
                .limit(100)
            )).scalars().all()
            result = await enrich_batch(db, tracks)
            job.result = json.dumps(result)

        elif task_name == "lastfm_top_tracks":
            await _run_lastfm_top_tracks(db, job)

        elif task_name == "discover_similar":
            await _run_discover_similar(db, job)

        elif task_name == "lastfm_sync":
            job.result = json.dumps({"status": "sync_placeholder"})

        elif task_name == "playlist_weekly_top":
            await _run_auto_playlist(db, "Weekly Top Tracks", "lastfm_top")

        elif task_name == "playlist_weekly_discover":
            await _run_auto_playlist(db, "Weekly Discover", "discover")

        elif task_name == "playlist_favorites":
            await _run_favorites_playlist(db)

        elif task_name == "audio_analysis":
            from backend.services.analyzer import analyze_track_async
            from backend.models.analysis import TrackAnalysis
            analyzed_ids = (await db.execute(select(TrackAnalysis.track_id))).scalars().all()
            tracks = (await db.execute(
                select(Track.id, Track.file_path).where(Track.id.notin_(analyzed_ids)).limit(50)
            )).all()
            for track_id, file_path in tracks:
                analysis = await analyze_track_async(file_path)
                if analysis:
                    await db.merge(TrackAnalysis(track_id=track_id, **analysis))
            await db.commit()

        elif task_name == "library_cleanup":
            job.result = json.dumps({"status": "cleanup_placeholder"})

        job.status = "completed"
    except Exception as e:
        log.error(f"Scheduled task {task_name} failed: {e}")
        job.status = "failed"
        job.result = json.dumps({"error": str(e)})
    finally:
        job.finished_at = datetime.utcnow()

        # Update last_run_at
        result = await db.execute(select(ScheduleTask).where(ScheduleTask.task_name == task_name))
        task = result.scalar_one_or_none()
        if task:
            task.last_run_at = datetime.utcnow()

        await db.merge(job)
        await db.commit()


async def _run_lastfm_top_tracks(db: AsyncSession, job: Job):
    """Download missing Last.fm top tracks."""
    from backend.services.lastfm import get_top_tracks
    chart = await get_top_tracks(limit=50)
    missing = []
    for t in chart:
        result = await db.execute(
            select(Track).where(Track.title.ilike(f"%{t['name']}%")).limit(1)
        )
        if not result.scalar_one_or_none():
            missing.append(t)

    job.total = len(missing)
    job.result = json.dumps({"total_chart": len(chart), "missing": len(missing)})


async def _run_discover_similar(db: AsyncSession, job: Job):
    """Find similar tracks from favorites."""
    from backend.services.lastfm import get_similar_tracks
    favorites = (await db.execute(
        select(Favorite).options(
            selectinload(Favorite.track).selectinload(Track.artist)
        ).where(Favorite.track_id.isnot(None)).limit(10)
    )).scalars().all()

    found = 0
    for fav in favorites:
        if not fav.track or not fav.track.artist:
            continue
        similar = await get_similar_tracks(fav.track.artist.name, fav.track.title, limit=5)
        found += len(similar)

    job.result = json.dumps({"favorites_checked": len(favorites), "similar_found": found})


async def _run_auto_playlist(db: AsyncSession, name: str, source: str):
    """Create/replace an auto-generated playlist."""
    # Delete existing playlist with same name
    from sqlalchemy import delete
    existing = (await db.execute(select(Playlist).where(Playlist.name == name))).scalar_one_or_none()
    if existing:
        await db.execute(delete(PlaylistTrack).where(PlaylistTrack.playlist_id == existing.id))
        await db.execute(delete(Playlist).where(Playlist.id == existing.id))

    # Get track IDs based on source
    track_ids = []
    if source == "lastfm_top":
        from backend.services.lastfm import get_top_tracks
        chart = await get_top_tracks(limit=50)
        for t in chart:
            result = await db.execute(
                select(Track.id).where(Track.title.ilike(f"%{t['name']}%")).limit(1)
            )
            tid = result.scalar_one_or_none()
            if tid:
                track_ids.append(tid)
    elif source == "discover":
        # Use random selection of library tracks for now
        from sqlalchemy import func
        result = await db.execute(select(Track.id).order_by(func.random()).limit(30))
        track_ids = result.scalars().all()

    if not track_ids:
        return

    playlist = Playlist(id=str(uuid.uuid4()), name=name, is_public=True)
    db.add(playlist)
    await db.flush()
    for i, tid in enumerate(track_ids):
        db.add(PlaylistTrack(id=str(uuid.uuid4()), playlist_id=playlist.id, track_id=tid, position=i))
    await db.commit()


async def _run_favorites_playlist(db: AsyncSession):
    """Create/replace Favorites playlist from all starred tracks."""
    from sqlalchemy import delete
    existing = (await db.execute(select(Playlist).where(Playlist.name == "Favorites"))).scalar_one_or_none()
    if existing:
        await db.execute(delete(PlaylistTrack).where(PlaylistTrack.playlist_id == existing.id))
        await db.execute(delete(Playlist).where(Playlist.id == existing.id))

    favorites = (await db.execute(
        select(Favorite.track_id).where(Favorite.track_id.isnot(None))
    )).scalars().all()

    if not favorites:
        return

    playlist = Playlist(id=str(uuid.uuid4()), name="Favorites", is_public=True)
    db.add(playlist)
    await db.flush()
    for i, tid in enumerate(favorites):
        db.add(PlaylistTrack(id=str(uuid.uuid4()), playlist_id=playlist.id, track_id=tid, position=i))
    await db.commit()
