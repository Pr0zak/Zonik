from __future__ import annotations

import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.helpers import paginate
from backend.api.library_cleanup import router as cleanup_router
from backend.api.library_dashboard import router as dashboard_router
from backend.database import get_db, async_session
from backend.models.track import Track
from backend.models.artist import Artist
from backend.models.album import Album
from backend.models.job import Job
from backend.api.websocket import broadcast_job_update

router = APIRouter()
router.include_router(cleanup_router)
router.include_router(dashboard_router)

ARTIST_SORT_COLUMNS = {"name"}
ALBUM_SORT_COLUMNS = {"title", "year", "artist_id"}


@router.get("/stats")
async def library_stats(db: AsyncSession = Depends(get_db)):
    tracks = (await db.execute(select(func.count(Track.id)))).scalar() or 0
    artists = (await db.execute(select(func.count(Artist.id)))).scalar() or 0
    albums = (await db.execute(select(func.count(Album.id)))).scalar() or 0
    total_size = (await db.execute(select(func.sum(Track.file_size)))).scalar() or 0
    total_duration = (await db.execute(select(func.sum(Track.duration_seconds)))).scalar() or 0

    formats = {}
    result = await db.execute(
        select(Track.format, func.count(Track.id)).group_by(Track.format)
    )
    for fmt, count in result.all():
        formats[fmt or "unknown"] = count

    return {
        "tracks": tracks,
        "artists": artists,
        "albums": albums,
        "total_size_bytes": total_size,
        "total_duration_seconds": total_duration,
        "formats": formats,
    }


@router.post("/scan")
async def scan_library(background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())

    async def run_scan():
        from backend.services.scanner import scan_library as do_scan
        async with async_session() as db:
            job = Job(id=job_id, type="library_scan", card="lib", status="running", started_at=datetime.utcnow())
            db.add(job)
            await db.commit()
            await broadcast_job_update({"id": job_id, "type": "library_scan", "status": "running", "progress": 0, "total": 0})

            async def on_progress(stats, total_files):
                # Only broadcast via WebSocket — don't write to DB mid-scan (SQLite locks)
                await broadcast_job_update({
                    "id": job_id, "type": "library_scan", "status": "running",
                    "progress": stats["scanned"], "total": total_files,
                })

            status = "completed"
            result_json = "{}"
            progress = 0
            total = 0
            try:
                stats = await do_scan(db, progress_callback=on_progress)
                status = "completed"
                result_json = json.dumps(stats)
                progress = stats.get("scanned", 0)
                total = progress
            except Exception as e:
                status = "failed"
                result_json = json.dumps({"error": str(e)})
            finally:
                # Use a fresh session to update the job — the scan session may be broken
                async with async_session() as finish_db:
                    result = await finish_db.execute(select(Job).where(Job.id == job_id))
                    fjob = result.scalar_one_or_none()
                    if fjob:
                        fjob.status = status
                        fjob.result = result_json
                        fjob.progress = progress
                        fjob.total = total
                        fjob.finished_at = datetime.utcnow()
                        await finish_db.commit()
                await broadcast_job_update({
                    "id": job_id, "type": "library_scan", "status": status,
                    "progress": progress, "total": total,
                })

                # Refresh Soulseek shared file list after scan and report to server
                if status == "completed":
                    try:
                        from backend.soulseek.shares import refresh_shares
                        from backend.config import get_settings
                        refresh_shares(get_settings().library.music_dir)
                        # Re-report share counts to Soulseek server
                        from backend.soulseek import get_client
                        client = get_client()
                        if client and client.server.connected:
                            await client._report_shares_to_server()
                    except Exception:
                        pass

                # Auto-trigger analysis/enrichment on new additions
                if status == "completed" and stats.get("added", 0) > 0:
                    await _auto_trigger_post_scan(stats["added"])

    background_tasks.add_task(run_scan)
    return {"job_id": job_id}


async def _auto_trigger_post_scan(added_count: int):
    """Check if analysis/enrichment should auto-run after scan."""
    import json as _json
    import logging
    from backend.models.schedule import ScheduleTask
    from backend.workers.scheduler import run_task

    log = logging.getLogger(__name__)
    async with async_session() as db:
        for task_name in ("audio_analysis", "enrichment"):
            result = await db.execute(
                select(ScheduleTask).where(ScheduleTask.task_name == task_name)
            )
            task = result.scalar_one_or_none()
            if not task or not task.config:
                continue
            try:
                config = _json.loads(task.config)
            except (ValueError, TypeError):
                continue
            if config.get("auto_after_scan"):
                log.info(f"Auto-triggering {task_name} after scan ({added_count} new tracks)")
                try:
                    async with async_session() as task_db:
                        await run_task(task_name, task_db)
                except Exception as e:
                    log.error(f"Auto-trigger {task_name} failed: {e}")


@router.get("/recent")
async def recent_tracks(limit: int = 20, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Track).order_by(Track.created_at.desc()).limit(limit)
    )
    tracks = result.scalars().all()
    return [
        {"id": t.id, "title": t.title, "artist_id": t.artist_id, "created_at": t.created_at.isoformat() if t.created_at else None}
        for t in tracks
    ]


@router.get("/artists")
async def list_artists(
    offset: int = 0,
    limit: int = 50,
    search: str | None = None,
    sort: str = "name",
    order: str = "asc",
    db: AsyncSession = Depends(get_db),
):
    base = select(Artist)

    if search:
        base = base.where(Artist.name.ilike(f"%{search}%"))

    sort_col = getattr(Artist, sort) if sort in ARTIST_SORT_COLUMNS else Artist.name
    base = base.order_by(sort_col.asc() if order == "asc" else sort_col.desc())

    total = (await db.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar() or 0

    query = base.offset(offset).limit(limit)

    # Subquery for track counts per artist
    track_count_sq = (
        select(Track.artist_id, func.count(Track.id).label("track_count"))
        .group_by(Track.artist_id)
        .subquery()
    )
    # Subquery for first album cover per artist
    album_cover_sq = (
        select(
            Album.artist_id,
            func.min(Album.id).label("album_id"),
        )
        .group_by(Album.artist_id)
        .subquery()
    )

    full_query = (
        query
        .outerjoin(track_count_sq, Artist.id == track_count_sq.c.artist_id)
        .outerjoin(album_cover_sq, Artist.id == album_cover_sq.c.artist_id)
        .add_columns(
            func.coalesce(track_count_sq.c.track_count, 0).label("track_count"),
            album_cover_sq.c.album_id.label("cover_album_id"),
        )
    )

    result = await db.execute(full_query)
    rows = result.all()

    items = [
        {
            "id": a.id,
            "name": a.name,
            "image_url": a.image_url,
            "cover_art": cover_album_id,
            "track_count": track_count,
        }
        for a, track_count, cover_album_id in rows
    ]

    return {"artists": items, "total": total}


@router.get("/albums")
async def list_albums(
    offset: int = 0,
    limit: int = 50,
    search: str | None = None,
    sort: str = "title",
    order: str = "asc",
    artist_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy.orm import selectinload
    query = select(Album).options(selectinload(Album.artist))

    if search:
        query = query.where(Album.title.ilike(f"%{search}%"))
    if artist_id:
        query = query.where(Album.artist_id == artist_id)

    sort_col = getattr(Album, sort) if sort in ALBUM_SORT_COLUMNS else Album.title
    query = query.order_by(sort_col.asc() if order == "asc" else sort_col.desc())

    page = await paginate(db, query, offset, limit)
    albums = page["items"]
    total = page["total"]

    return {
        "albums": [
            {
                "id": a.id,
                "title": a.title,
                "artist": a.artist.name if a.artist else None,
                "artist_id": a.artist_id,
                "year": a.year,
                "cover_art": a.id,
                "track_count": a.track_count or 0,
            }
            for a in albums
        ],
        "total": total,
    }


@router.get("/genres")
async def list_genres(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Track.genre, func.count(Track.id))
        .where(Track.genre.isnot(None))
        .group_by(Track.genre)
        .order_by(func.count(Track.id).desc())
    )
    return [{"name": name, "count": count} for name, count in result.all()]
