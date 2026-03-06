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
            await _run_lastfm_loved_sync(db, job)

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
    """Trigger individual download jobs for each missing track."""
    import asyncio
    from backend.database import async_session
    from backend.api.download import _do_download_inner, _get_semaphore, DownloadRequest

    total = len(missing)
    log.info(f"Auto-downloading {total} missing tracks from {source}")

    sem = _get_semaphore()

    async def download_one(t: dict):
        artist = t.get("artist", "")
        track = t.get("track", "")
        if not artist or not track:
            return
        job_id = str(uuid.uuid4())
        desc = f"{artist} — {track}"
        req = DownloadRequest(artist=artist, track=track)

        async with async_session() as db:
            # If queue is full, show as queued
            if sem.locked():
                job = Job(
                    id=job_id, type="download", card="dl", status="pending",
                    started_at=datetime.utcnow(),
                    tracks=json.dumps([{"artist": artist, "track": track, "status": "queued"}]),
                )
                db.add(job)
                await db.commit()
                await broadcast_job_update({"id": job_id, "type": "download", "status": "pending", "progress": 0, "total": 1, "description": f"Queued: {desc}"})
                async with sem:
                    job.status = "running"
                    await db.merge(job)
                    await db.commit()
                    await broadcast_job_update({"id": job_id, "type": "download", "status": "running", "progress": 0, "total": 1, "description": desc})
                    await _do_download_inner(db, job, job_id, desc, req)
            else:
                job = Job(
                    id=job_id, type="download", card="dl", status="running",
                    started_at=datetime.utcnow(),
                    tracks=json.dumps([{"artist": artist, "track": track, "status": "pending"}]),
                )
                db.add(job)
                await db.commit()
                await broadcast_job_update({"id": job_id, "type": "download", "status": "running", "progress": 0, "total": 1, "description": desc})
                async with sem:
                    await _do_download_inner(db, job, job_id, desc, req)

    # Fire all downloads concurrently — semaphore handles the queue limit
    tasks = [asyncio.create_task(download_one(t)) for t in missing]
    await asyncio.gather(*tasks, return_exceptions=True)


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


async def _run_lastfm_loved_sync(db: AsyncSession, job: Job):
    """Sync Zonik favorites → Last.fm loved tracks."""
    from backend.config import get_settings
    from backend.services.scrobbler import sync_loved_tracks

    settings = get_settings()
    session_key = settings.lastfm.session_key
    if not session_key:
        job.result = json.dumps({"error": "No Last.fm session key. Authenticate via Settings > Last.fm."})
        return

    username = settings.lastfm.username
    result = await sync_loved_tracks(session_key, username=username)
    job.total = result["total"]
    job.progress = result["synced"] + result["skipped"]
    job.result = json.dumps(result)
