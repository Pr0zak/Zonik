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
            func.case(
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
        select(Job.type, func.count(Job.id), func.sum(func.case((Job.status == "completed", 1), else_=0)))
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
