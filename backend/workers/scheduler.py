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
from backend.api.websocket import broadcast_job_update

log = logging.getLogger(__name__)

# Friendly labels for task names (used in WebSocket broadcasts)
_TASK_LABELS = {
    "lastfm_top_tracks": "Top Charts Scan",
    "discover_similar": "Similar Tracks Scan",
    "discover_artists": "Similar Artists Scan",
    "library_scan": "Library Scan",
    "enrichment": "Enrichment",
    "audio_analysis": "Audio Analysis",
    "library_cleanup": "Library Cleanup",
    "kimahub_favorites_sync": "KimaHub Sync",
}


async def run_task(task_name: str, db: AsyncSession, job_id: str | None = None):
    """Execute a scheduled task by name."""
    # Load task config for count
    task_row = (await db.execute(
        select(ScheduleTask).where(ScheduleTask.task_name == task_name)
    )).scalar_one_or_none()
    count = task_row.count if task_row and task_row.count else None
    task_config = {}
    if task_row and task_row.config:
        try:
            task_config = json.loads(task_row.config)
        except (ValueError, TypeError):
            pass

    if not job_id:
        job_id = str(uuid.uuid4())
    job = Job(
        id=job_id, type=task_name, card="sched", status="running",
        started_at=datetime.utcnow(),
    )
    db.add(job)
    await db.commit()
    desc = _TASK_LABELS.get(task_name, task_name)
    await broadcast_job_update({"id": job_id, "type": task_name, "status": "running", "progress": 0, "total": 1, "description": desc})

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

        elif task_name == "playlist_unfavorites":
            await _run_unfavorites_playlist(db)

        elif task_name == "audio_analysis":
            from backend.services.analyzer import analyze_track_async
            from backend.models.analysis import TrackAnalysis
            analyzed_ids = (await db.execute(select(TrackAnalysis.track_id))).scalars().all()
            tracks = (await db.execute(
                select(Track.id, Track.file_path).where(Track.id.notin_(analyzed_ids))
            )).all()
            failed_count = 0
            for track_id, file_path in tracks:
                try:
                    analysis = await analyze_track_async(file_path)
                    if analysis:
                        await db.merge(TrackAnalysis(track_id=track_id, **analysis))
                except Exception as e:
                    failed_count += 1
                    log.warning(f"[scheduler] Analysis failed for {file_path}: {e}")
            await db.commit()
            if failed_count:
                job.result = json.dumps({"analyzed": len(tracks) - failed_count, "failed": failed_count})

        elif task_name == "kimahub_favorites_sync":
            result = await _run_kimahub_favorites_sync(db)
            job.result = json.dumps(result)

        elif task_name == "library_cleanup":
            from backend.services.cleanup import remove_orphaned_tracks
            result = await remove_orphaned_tracks(db)
            job.result = json.dumps(result)

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
        await broadcast_job_update({"id": job_id, "type": task_name, "status": job.status, "progress": 1, "total": 1, "description": desc})

        # Auto-download missing tracks if configured
        if (
            job.status == "completed"
            and task_config.get("auto_download")
            and task_name in ("lastfm_top_tracks", "discover_similar")
            and job.tracks
        ):
            try:
                missing = json.loads(job.tracks)
                if missing:
                    await _auto_download_missing(missing, task_name)
            except Exception as e:
                log.error(f"Auto-download after {task_name} failed: {e}")


async def _auto_download_missing(missing: list[dict], source: str):
    """Trigger bulk download of missing tracks found by discovery."""
    from backend.services.soulseek import search_and_download
    from backend.database import async_session

    total = len(missing)
    log.info(f"Auto-downloading {total} missing tracks from {source}")
    job_id = str(uuid.uuid4())
    desc = f"Auto-download ({total} tracks)"

    # Create a tracking job for the auto-download phase
    async with async_session() as db:
        dl_job = Job(id=job_id, type="bulk_download", card="dl", status="running", started_at=datetime.utcnow())
        db.add(dl_job)
        await db.commit()
    await broadcast_job_update({"id": job_id, "type": "bulk_download", "status": "running", "progress": 0, "total": total, "description": desc})

    # Use global download semaphore to respect queue limits
    from backend.api.download import _get_semaphore
    sem = _get_semaphore()

    completed = 0
    failed = 0
    for i, t in enumerate(missing):
        artist = t.get("artist", "")
        track = t.get("track", "")
        if not artist or not track:
            continue
        async with sem:
            try:
                await search_and_download(artist, track)
                completed += 1
            except Exception as e:
                failed += 1
                log.warning(f"Auto-download failed for {artist} - {track}: {e}")
        await broadcast_job_update({"id": job_id, "type": "bulk_download", "status": "running", "progress": i + 1, "total": total, "description": f"{desc} — {artist} - {track}"})

    # Finalize
    status = "completed" if completed > 0 else "failed"
    async with async_session() as db:
        dl_job = await db.get(Job, job_id)
        if dl_job:
            dl_job.status = status
            dl_job.finished_at = datetime.utcnow()
            dl_job.result = json.dumps({"completed": completed, "failed": failed, "total": total})
            await db.commit()
    await broadcast_job_update({"id": job_id, "type": "bulk_download", "status": status, "progress": total, "total": total, "description": desc})


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
    """Find similar tracks from favorites, flag missing ones."""
    from backend.services.lastfm import get_similar_tracks
    from backend.services.soulseek import normalize_text
    favorites = (await db.execute(
        select(Favorite).options(
            selectinload(Favorite.track).selectinload(Track.artist)
        ).where(Favorite.track_id.isnot(None)).limit(count)
    )).scalars().all()

    missing = []
    in_library = 0
    seen: set[str] = set()

    for fav in favorites:
        if not fav.track or not fav.track.artist:
            continue
        similar = await get_similar_tracks(fav.track.artist.name, fav.track.title, limit=5)
        for t in similar:
            key = normalize_text(f"{t['artist']} {t['name']}")
            if key in seen:
                continue
            seen.add(key)

            result = await db.execute(
                select(Track).join(Artist, Track.artist_id == Artist.id).where(
                    Track.title.ilike(t["name"]),
                    Artist.name.ilike(t["artist"]),
                ).limit(1)
            )
            if result.scalar_one_or_none():
                in_library += 1
            else:
                missing.append({
                    "artist": t["artist"], "track": t["name"], "status": "missing",
                    "source": f"{fav.track.artist.name} — {fav.track.title}",
                })

    job.total = len(seen)
    job.progress = in_library
    job.tracks = json.dumps(missing)
    job.result = json.dumps({
        "favorites_checked": len(favorites),
        "similar_found": len(seen),
        "in_library": in_library,
        "missing": len(missing),
    })


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


async def _run_unfavorites_playlist(db: AsyncSession):
    """Create/replace Unfavorites playlist from all tracks NOT starred."""
    from sqlalchemy import delete

    existing = (await db.execute(select(Playlist).where(Playlist.name == "Unfavorites"))).scalar_one_or_none()
    if existing:
        await db.execute(delete(PlaylistTrack).where(PlaylistTrack.playlist_id == existing.id))
        await db.execute(delete(Playlist).where(Playlist.id == existing.id))

    fav_ids = (await db.execute(
        select(Favorite.track_id).where(Favorite.track_id.isnot(None))
    )).scalars().all()

    query = select(Track.id).order_by(Track.title)
    if fav_ids:
        query = query.where(Track.id.notin_(fav_ids))
    unfav_tracks = (await db.execute(query)).scalars().all()

    if not unfav_tracks:
        return

    playlist = Playlist(id=str(uuid.uuid4()), name="Unfavorites", is_public=True)
    db.add(playlist)
    await db.flush()
    for i, tid in enumerate(unfav_tracks):
        db.add(PlaylistTrack(id=str(uuid.uuid4()), playlist_id=playlist.id, track_id=tid, position=i))
    await db.commit()
