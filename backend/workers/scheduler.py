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
from backend.models.artist import Artist
from backend.models.favorite import Favorite
from backend.models.playlist import Playlist, PlaylistTrack

log = logging.getLogger(__name__)


async def run_task(task_name: str, db: AsyncSession, job_id: str | None = None):
    """Execute a scheduled task by name."""
    # Load task config for count
    task_row = (await db.execute(
        select(ScheduleTask).where(ScheduleTask.task_name == task_name)
    )).scalar_one_or_none()
    count = task_row.count if task_row and task_row.count else None

    if not job_id:
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
            query = select(Track.id).where(
                (Track.genre.is_(None)) | (Track.cover_art_path.is_(None))
            )
            tracks = (await db.execute(query)).scalars().all()
            result = await enrich_batch(db, tracks)
            job.result = json.dumps(result)

        elif task_name == "lastfm_top_tracks":
            await _run_lastfm_top_tracks(db, job, count=count or 50)

        elif task_name == "discover_similar":
            await _run_discover_similar(db, job, count=count or 10)

        elif task_name == "lastfm_sync":
            job.result = json.dumps({"status": "sync_placeholder"})

        elif task_name == "playlist_weekly_top":
            await _run_auto_playlist(db, "Weekly Top Tracks", "lastfm_top", count=count or 50)

        elif task_name == "playlist_weekly_discover":
            await _run_auto_playlist(db, "Weekly Discover", "discover", count=count or 30)

        elif task_name == "playlist_favorites":
            await _run_favorites_playlist(db)

        elif task_name == "audio_analysis":
            from backend.services.analyzer import analyze_track_async
            from backend.models.analysis import TrackAnalysis
            analyzed_ids = (await db.execute(select(TrackAnalysis.track_id))).scalars().all()
            tracks = (await db.execute(
                select(Track.id, Track.file_path).where(Track.id.notin_(analyzed_ids))
            )).all()
            for track_id, file_path in tracks:
                analysis = await analyze_track_async(file_path)
                if analysis:
                    await db.merge(TrackAnalysis(track_id=track_id, **analysis))
            await db.commit()

        elif task_name == "kimahub_favorites_sync":
            result = await _run_kimahub_favorites_sync(db)
            job.result = json.dumps(result)

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


async def _run_lastfm_top_tracks(db: AsyncSession, job: Job, count: int = 50):
    """Pull Last.fm top chart, find missing tracks, store list for download."""
    from backend.services.lastfm import get_top_tracks
    chart = await get_top_tracks(limit=count)
    missing = []
    in_library = 0
    for t in chart:
        result = await db.execute(
            select(Track).join(Artist, Track.artist_id == Artist.id).where(
                Track.title.ilike(t["name"]),
                Artist.name.ilike(t["artist"]),
            ).limit(1)
        )
        if result.scalar_one_or_none():
            in_library += 1
        else:
            missing.append({"artist": t["artist"], "track": t["name"], "status": "missing"})

    job.total = len(chart)
    job.progress = in_library
    job.tracks = json.dumps(missing)
    job.result = json.dumps({
        "total_chart": len(chart),
        "in_library": in_library,
        "missing": len(missing),
    })


async def _run_discover_similar(db: AsyncSession, job: Job, count: int = 10):
    """Find similar tracks from favorites."""
    from backend.services.lastfm import get_similar_tracks
    favorites = (await db.execute(
        select(Favorite).options(
            selectinload(Favorite.track).selectinload(Track.artist)
        ).where(Favorite.track_id.isnot(None)).limit(count)
    )).scalars().all()

    found = 0
    for fav in favorites:
        if not fav.track or not fav.track.artist:
            continue
        similar = await get_similar_tracks(fav.track.artist.name, fav.track.title, limit=5)
        found += len(similar)

    job.result = json.dumps({"favorites_checked": len(favorites), "similar_found": found})


async def _run_auto_playlist(db: AsyncSession, name: str, source: str, count: int = 50):
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
        chart = await get_top_tracks(limit=count)
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
        result = await db.execute(select(Track.id).order_by(func.random()).limit(count))
        track_ids = result.scalars().all()

    if not track_ids:
        return

    playlist = Playlist(id=str(uuid.uuid4()), name=name, is_public=True)
    db.add(playlist)
    await db.flush()
    for i, tid in enumerate(track_ids):
        db.add(PlaylistTrack(id=str(uuid.uuid4()), playlist_id=playlist.id, track_id=tid, position=i))
    await db.commit()


async def _run_kimahub_favorites_sync(db: AsyncSession) -> dict:
    """Sync liked tracks from KimaHub PostgreSQL into Zonik favorites."""
    import hashlib

    from backend.config import get_settings

    kimahub_db_url = get_settings().kimahub.db_url
    if not kimahub_db_url:
        return {"error": "kimahub_db_url not configured in zonik.toml"}

    try:
        import asyncpg
    except ImportError:
        # Fallback to sync psycopg2
        pass

    imported = 0
    skipped = 0
    not_found = 0

    try:
        conn = await asyncpg.connect(kimahub_db_url)
        rows = await conn.fetch("""
            SELECT t."filePath", t.title, a.name as artist
            FROM "LikedTrack" lt
            JOIN "Track" t ON t.id = lt."trackId"
            JOIN "Album" al ON al.id = t."albumId"
            JOIN "Artist" a ON a.id = al."artistId"
        """)
        await conn.close()
    except Exception as e:
        return {"error": f"Failed to connect to KimaHub DB: {str(e)}"}

    # Resolve admin user ID
    from backend.models.user import User
    user_result = await db.execute(select(User).where(User.username == "admin"))
    user = user_result.scalar_one_or_none()
    if not user:
        return {"error": "admin user not found"}
    admin_id = user.id

    for row in rows:
        file_path = row["filePath"]
        # Generate Zonik track ID from file path
        track_id = hashlib.md5(file_path.encode()).hexdigest()
        track = await db.get(Track, track_id)

        if not track:
            not_found += 1
            continue

        # Check if already favorited
        existing = (await db.execute(
            select(Favorite).where(
                Favorite.user_id == admin_id,
                Favorite.track_id == track.id,
            )
        )).scalar_one_or_none()

        if existing:
            skipped += 1
            continue

        fav = Favorite(
            id=str(uuid.uuid4()),
            user_id=admin_id,
            track_id=track.id,
            starred_at=datetime.utcnow(),
        )
        db.add(fav)
        imported += 1

    await db.commit()
    return {"imported": imported, "skipped": skipped, "not_found": not_found, "total": len(rows)}


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
