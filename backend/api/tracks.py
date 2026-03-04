from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db
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

    if search:
        query = query.where(Track.title.ilike(f"%{search}%"))
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
        count_q = count_q.where(Track.title.ilike(f"%{search}%"))
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
