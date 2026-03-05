from __future__ import annotations

import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db, async_session
from backend.models.track import Track
from backend.models.artist import Artist
from backend.models.album import Album
from backend.models.job import Job
from backend.api.websocket import broadcast_job_update

router = APIRouter()


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
    query = select(Artist)
    count_q = select(func.count(Artist.id))

    if search:
        query = query.where(Artist.name.ilike(f"%{search}%"))
        count_q = count_q.where(Artist.name.ilike(f"%{search}%"))

    sort_col = getattr(Artist, sort, Artist.name)
    query = query.order_by(sort_col.asc() if order == "asc" else sort_col.desc())
    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    artists = result.scalars().all()
    total = (await db.execute(count_q)).scalar() or 0

    items = []
    for a in artists:
        track_count = (await db.execute(
            select(func.count(Track.id)).where(Track.artist_id == a.id)
        )).scalar() or 0
        # Get cover art from first album
        album_result = await db.execute(
            select(Album.id, Album.cover_art_path).where(Album.artist_id == a.id).limit(1)
        )
        album_row = album_result.first()
        items.append({
            "id": a.id,
            "name": a.name,
            "image_url": a.image_url,
            "cover_art": album_row[0] if album_row else None,
            "track_count": track_count,
        })

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
    count_q = select(func.count(Album.id))

    if search:
        query = query.where(Album.title.ilike(f"%{search}%"))
        count_q = count_q.where(Album.title.ilike(f"%{search}%"))
    if artist_id:
        query = query.where(Album.artist_id == artist_id)
        count_q = count_q.where(Album.artist_id == artist_id)

    sort_col = getattr(Album, sort, Album.title)
    query = query.order_by(sort_col.asc() if order == "asc" else sort_col.desc())
    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    albums = result.scalars().all()
    total = (await db.execute(count_q)).scalar() or 0

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


# --- Cleanup Endpoints ---

@router.post("/cleanup/orphans/preview")
async def preview_orphans(db: AsyncSession = Depends(get_db)):
    """Preview orphaned tracks (files missing from disk)."""
    from backend.services.cleanup import find_orphaned_tracks
    orphans = await find_orphaned_tracks(db)
    return {"orphans": orphans, "count": len(orphans)}


@router.post("/cleanup/orphans")
async def remove_orphans(db: AsyncSession = Depends(get_db)):
    """Remove orphaned tracks from database."""
    from backend.services.cleanup import remove_orphaned_tracks
    return await remove_orphaned_tracks(db)


@router.post("/cleanup/duplicates/preview")
async def preview_duplicates(db: AsyncSession = Depends(get_db)):
    """Preview duplicate tracks."""
    from backend.services.cleanup import find_duplicates
    groups = await find_duplicates(db)
    total_dupes = sum(len(g["remove"]) for g in groups)
    return {"groups": groups, "total_groups": len(groups), "total_duplicates": total_dupes}


@router.post("/cleanup/duplicates")
async def remove_dupes(
    request: dict,
    db: AsyncSession = Depends(get_db),
):
    """Remove specified duplicate tracks. Body: {remove_ids: [...], delete_files: bool}"""
    from backend.services.cleanup import remove_duplicates
    remove_ids = request.get("remove_ids", [])
    delete_files = request.get("delete_files", False)
    if not remove_ids:
        return {"error": "No track IDs provided"}
    return await remove_duplicates(db, remove_ids, delete_files)


@router.post("/cleanup/organize/preview")
async def preview_organize_files(db: AsyncSession = Depends(get_db)):
    """Preview file rename/sort operations."""
    from backend.services.cleanup import preview_organize
    moves = await preview_organize(db)
    return {"moves": moves, "count": len(moves)}


@router.post("/cleanup/organize")
async def organize_files(
    request: dict | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Execute file rename/sort. Optional body: {move_ids: [...]}"""
    from backend.services.cleanup import execute_organize
    move_ids = request.get("move_ids") if request else None
    return await execute_organize(db, move_ids)


@router.get("/genres")
async def list_genres(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Track.genre, func.count(Track.id))
        .where(Track.genre.isnot(None))
        .group_by(Track.genre)
        .order_by(func.count(Track.id).desc())
    )
    return [{"name": name, "count": count} for name, count in result.all()]


@router.get("/stats/detailed")
async def detailed_stats(db: AsyncSession = Depends(get_db)):
    """Detailed library statistics for the stats page."""
    from backend.models.analysis import TrackAnalysis
    from backend.models.embedding import TrackEmbedding
    from backend.models.favorite import Favorite
    from backend.models.playlist import Playlist
    from backend.models.job import Job

    # Basic counts
    track_count = (await db.execute(select(func.count(Track.id)))).scalar() or 0
    artist_count = (await db.execute(select(func.count(Artist.id)))).scalar() or 0
    album_count = (await db.execute(select(func.count(Album.id)))).scalar() or 0
    total_size = (await db.execute(select(func.sum(Track.file_size)))).scalar() or 0
    total_duration = (await db.execute(select(func.sum(Track.duration_seconds)))).scalar() or 0

    # Formats
    formats = {}
    fmt_result = await db.execute(
        select(Track.format, func.count(Track.id)).group_by(Track.format)
    )
    for fmt, count in fmt_result.all():
        formats[fmt or "unknown"] = count

    # Genres (top 20)
    genre_result = await db.execute(
        select(Track.genre, func.count(Track.id))
        .where(Track.genre.isnot(None))
        .group_by(Track.genre)
        .order_by(func.count(Track.id).desc())
        .limit(20)
    )
    genres = [{"name": g, "count": c} for g, c in genre_result.all()]

    # Top artists by track count
    top_artists_result = await db.execute(
        select(Artist.name, func.count(Track.id))
        .join(Track, Track.artist_id == Artist.id)
        .group_by(Artist.id)
        .order_by(func.count(Track.id).desc())
        .limit(15)
    )
    top_artists = [{"name": n, "count": c} for n, c in top_artists_result.all()]

    # Year distribution
    year_result = await db.execute(
        select(Track.year, func.count(Track.id))
        .where(Track.year.isnot(None))
        .group_by(Track.year)
        .order_by(Track.year)
    )
    years = [{"year": y, "count": c} for y, c in year_result.all()]

    # Bitrate distribution
    bitrate_result = await db.execute(
        select(
            case(
                (Track.bitrate < 128, "< 128"),
                (Track.bitrate < 256, "128-255"),
                (Track.bitrate < 320, "256-319"),
                (Track.bitrate == 320, "320"),
                (Track.bitrate > 320, "Lossless"),
                else_="Unknown"
            ).label("range"),
            func.count(Track.id)
        )
        .where(Track.bitrate.isnot(None))
        .group_by("range")
    )
    bitrates = {r: c for r, c in bitrate_result.all()}

    # Analysis / embedding counts
    analyzed = (await db.execute(select(func.count(TrackAnalysis.track_id)))).scalar() or 0
    embedded = (await db.execute(select(func.count(TrackEmbedding.track_id)))).scalar() or 0
    favorites = (await db.execute(select(func.count(Favorite.id)))).scalar() or 0
    playlists = (await db.execute(select(func.count(Playlist.id)))).scalar() or 0

    # Most played
    most_played_result = await db.execute(
        select(Track.title, Artist.name, Track.play_count)
        .outerjoin(Artist, Track.artist_id == Artist.id)
        .where(Track.play_count > 0)
        .order_by(Track.play_count.desc())
        .limit(10)
    )
    most_played = [{"title": t, "artist": a, "plays": p} for t, a, p in most_played_result.all()]

    # Recent jobs
    jobs_result = await db.execute(
        select(Job.type, func.count(Job.id), func.sum(case((Job.status == "completed", 1), else_=0)))
        .group_by(Job.type)
    )
    job_stats = [{"type": t, "total": total, "completed": comp or 0} for t, total, comp in jobs_result.all()]

    return {
        "tracks": track_count,
        "artists": artist_count,
        "albums": album_count,
        "total_size_bytes": total_size,
        "total_duration_seconds": total_duration,
        "formats": formats,
        "genres": genres,
        "top_artists": top_artists,
        "years": years,
        "bitrates": bitrates,
        "analyzed": analyzed,
        "embedded": embedded,
        "favorites": favorites,
        "playlists": playlists,
        "most_played": most_played,
        "job_stats": job_stats,
    }
