from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db, search_fts
from backend.models.track import Track
from backend.models.artist import Artist
from backend.models.album import Album

router = APIRouter()


@router.get("")
async def list_tracks(
    offset: int = 0,
    limit: int = 50,
    sort: str = "title",
    order: str = "asc",
    search: str | None = None,
    genre: str | None = None,
    artist_id: str | None = None,
    album_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(Track).options(selectinload(Track.artist), selectinload(Track.album))

    # Use FTS5 for search (searches title, artist, album) with ILIKE fallback
    fts_ids = None
    if search:
        fts_ids = await search_fts(db, search, limit=500)
        if fts_ids:
            query = query.where(Track.id.in_(fts_ids))
        else:
            # Fallback: substring match on title, artist name, or album title
            like = f"%{search}%"
            query = query.where(
                Track.title.ilike(like)
                | Track.artist_id.in_(
                    select(Artist.id).where(Artist.name.ilike(like))
                )
            )
    if genre:
        query = query.where(Track.genre == genre)
    if artist_id:
        query = query.where(Track.artist_id == artist_id)
    if album_id:
        query = query.where(Track.album_id == album_id)

    sort_col = getattr(Track, sort, Track.title)
    query = query.order_by(sort_col.asc() if order == "asc" else sort_col.desc())
    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    tracks = result.scalars().all()

    count_q = select(func.count(Track.id))
    if search:
        if fts_ids:
            count_q = count_q.where(Track.id.in_(fts_ids))
        else:
            like = f"%{search}%"
            count_q = count_q.where(
                Track.title.ilike(like)
                | Track.artist_id.in_(
                    select(Artist.id).where(Artist.name.ilike(like))
                )
            )
    if genre:
        count_q = count_q.where(Track.genre == genre)
    if artist_id:
        count_q = count_q.where(Track.artist_id == artist_id)
    if album_id:
        count_q = count_q.where(Track.album_id == album_id)
    total = (await db.execute(count_q)).scalar() or 0

    return {
        "tracks": [
            {
                "id": t.id,
                "title": t.title,
                "artist": t.artist.name if t.artist else None,
                "artist_id": t.artist_id,
                "album": t.album.title if t.album else None,
                "album_id": t.album_id,
                "track_number": t.track_number,
                "duration": t.duration_seconds,
                "format": t.format,
                "bitrate": t.bitrate,
                "genre": t.genre,
                "year": t.year,
                "file_size": t.file_size,
                "play_count": t.play_count,
                "cover_art": t.album_id or t.id,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in tracks
        ],
        "total": total,
    }


@router.get("/{track_id}")
async def get_track(track_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Track)
        .options(selectinload(Track.artist), selectinload(Track.album), selectinload(Track.analysis))
        .where(Track.id == track_id)
    )
    track = result.scalar_one_or_none()
    if not track:
        raise HTTPException(404, "Track not found")
    return {
        "id": track.id,
        "title": track.title,
        "artist": track.artist.name if track.artist else None,
        "artist_id": track.artist_id,
        "album": track.album.title if track.album else None,
        "album_id": track.album_id,
        "track_number": track.track_number,
        "disc_number": track.disc_number,
        "duration": track.duration_seconds,
        "file_path": track.file_path,
        "file_size": track.file_size,
        "format": track.format,
        "bitrate": track.bitrate,
        "sample_rate": track.sample_rate,
        "bit_depth": track.bit_depth,
        "genre": track.genre,
        "year": track.year,
        "play_count": track.play_count,
        "cover_art_path": track.cover_art_path,
        "analysis": {
            "bpm": track.analysis.bpm,
            "key": track.analysis.key,
            "scale": track.analysis.scale,
            "energy": track.analysis.energy,
            "danceability": track.analysis.danceability,
        } if track.analysis else None,
        "created_at": track.created_at.isoformat() if track.created_at else None,
    }


class TrackUpdateRequest(BaseModel):
    title: str | None = None
    genre: str | None = None
    year: int | None = None
    track_number: int | None = None


@router.put("/{track_id}")
async def update_track(track_id: str, req: TrackUpdateRequest, db: AsyncSession = Depends(get_db)):
    """Update track metadata in DB and write tags to file."""
    result = await db.execute(
        select(Track).options(selectinload(Track.artist), selectinload(Track.album))
        .where(Track.id == track_id)
    )
    track = result.scalar_one_or_none()
    if not track:
        raise HTTPException(404, "Track not found")

    if req.title is not None:
        track.title = req.title
    if req.genre is not None:
        track.genre = req.genre
    if req.year is not None:
        track.year = req.year
    if req.track_number is not None:
        track.track_number = req.track_number

    await db.commit()

    # Write tags to file
    try:
        from pathlib import Path
        from backend.config import get_settings
        import mutagen
        from mutagen.easyid3 import EasyID3

        settings = get_settings()
        file_path = Path(settings.library.music_dir) / track.file_path

        if file_path.exists():
            audio = mutagen.File(str(file_path), easy=True)
            if audio is not None:
                if req.title is not None:
                    audio["title"] = req.title
                if req.genre is not None:
                    audio["genre"] = req.genre
                if req.year is not None:
                    audio["date"] = str(req.year)
                if req.track_number is not None:
                    audio["tracknumber"] = str(req.track_number)
                audio.save()
    except Exception:
        pass  # DB updated even if tag write fails

    return {
        "ok": True,
        "track": {
            "id": track.id,
            "title": track.title,
            "genre": track.genre,
            "year": track.year,
            "track_number": track.track_number,
        },
    }


@router.delete("/{track_id}")
async def delete_track(track_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Track).where(Track.id == track_id))
    track = result.scalar_one_or_none()
    if not track:
        raise HTTPException(404, "Track not found")

    from pathlib import Path
    from backend.config import get_settings
    settings = get_settings()
    file_path = Path(settings.library.music_dir) / track.file_path
    if file_path.exists():
        file_path.unlink()

    await db.execute(delete(Track).where(Track.id == track_id))
    await db.commit()
    return {"ok": True}


class BulkDeleteRequest(BaseModel):
    track_ids: list[str]


@router.post("/bulk-delete")
async def bulk_delete_tracks(req: BulkDeleteRequest, db: AsyncSession = Depends(get_db)):
    """Delete multiple tracks and their files."""
    from pathlib import Path
    from backend.config import get_settings
    settings = get_settings()

    deleted = 0
    for track_id in req.track_ids:
        result = await db.execute(select(Track).where(Track.id == track_id))
        track = result.scalar_one_or_none()
        if track:
            file_path = Path(settings.library.music_dir) / track.file_path
            if file_path.exists():
                file_path.unlink()
            await db.delete(track)
            deleted += 1
    await db.commit()
    return {"deleted": deleted}


class BulkAnalyzeRequest(BaseModel):
    track_ids: list[str]


@router.post("/bulk-analyze")
async def bulk_analyze_tracks(req: BulkAnalyzeRequest, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """Queue specific tracks for audio analysis."""
    import uuid
    from datetime import datetime
    from backend.database import async_session
    from backend.models.analysis import TrackAnalysis
    from backend.models.job import Job

    job_id = str(uuid.uuid4())

    # Verify tracks exist and collect file paths
    track_info = []
    for track_id in req.track_ids:
        result = await db.execute(select(Track.id, Track.file_path).where(Track.id == track_id))
        row = result.one_or_none()
        if row:
            track_info.append((row[0], row[1]))

    if not track_info:
        return {"job_id": None, "queued": 0}

    async def run_analysis():
        from backend.services.analyzer import analyze_track_async

        async with async_session() as db_inner:
            job = Job(
                id=job_id, type="audio_analysis", card="an", status="running",
                total=len(track_info), started_at=datetime.utcnow(),
            )
            db_inner.add(job)
            await db_inner.commit()

            for i, (track_id, file_path) in enumerate(track_info):
                try:
                    analysis = await analyze_track_async(file_path)
                    if analysis:
                        ta = TrackAnalysis(
                            track_id=track_id,
                            bpm=analysis.get("bpm"),
                            key=analysis.get("key"),
                            scale=analysis.get("scale"),
                            energy=analysis.get("energy"),
                            danceability=analysis.get("danceability"),
                            loudness=analysis.get("loudness"),
                        )
                        await db_inner.merge(ta)

                    job.progress = i + 1
                    await db_inner.merge(job)
                    await db_inner.commit()
                except Exception:
                    pass

            job.status = "completed"
            job.finished_at = datetime.utcnow()
            await db_inner.merge(job)
            await db_inner.commit()

    background_tasks.add_task(run_analysis)
    return {"job_id": job_id, "queued": len(track_info)}
