from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db, async_session
from backend.models.track import Track
from backend.models.artist import Artist
from backend.models.album import Album
from backend.models.job import Job

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
            try:
                stats = await do_scan(db)
                job.status = "completed"
                job.result = str(stats)
            except Exception as e:
                job.status = "failed"
                job.result = str(e)
            finally:
                job.finished_at = datetime.utcnow()
                await db.merge(job)
                await db.commit()

    background_tasks.add_task(run_scan)
    return {"job_id": job_id}


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


@router.get("/genres")
async def list_genres(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Track.genre, func.count(Track.id))
        .where(Track.genre.isnot(None))
        .group_by(Track.genre)
        .order_by(func.count(Track.id).desc())
    )
    return [{"name": name, "count": count} for name, count in result.all()]
