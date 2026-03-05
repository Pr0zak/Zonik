from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.models.playlist import Playlist, PlaylistTrack

router = APIRouter()


class SmartPlaylistRequest(BaseModel):
    name: str
    rule: str  # "genre", "bpm_range", "recent", "top_played", "random"
    value: str | None = None  # e.g. genre name, "120-140" for BPM range
    limit: int = 50


class PlaylistCreate(BaseModel):
    name: str
    comment: str | None = None
    track_ids: list[str] = []


class PlaylistUpdate(BaseModel):
    name: str | None = None
    comment: str | None = None
    track_ids: list[str] | None = None


@router.get("")
async def list_playlists(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Playlist).options(selectinload(Playlist.entries)).order_by(Playlist.updated_at.desc())
    )
    playlists = result.scalars().all()
    return [
        {
            "id": p.id,
            "name": p.name,
            "comment": p.comment,
            "track_count": len(p.entries),
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        }
        for p in playlists
    ]


@router.post("")
async def create_playlist(req: PlaylistCreate, user_id: str = "admin", db: AsyncSession = Depends(get_db)):
    playlist = Playlist(
        id=str(uuid.uuid4()),
        name=req.name,
        user_id=user_id,
        comment=req.comment,
    )
    db.add(playlist)
    for i, tid in enumerate(req.track_ids):
        db.add(PlaylistTrack(id=str(uuid.uuid4()), playlist_id=playlist.id, track_id=tid, position=i))
    await db.commit()
    return {"id": playlist.id, "name": playlist.name}


@router.post("/generate")
async def generate_smart_playlist(req: SmartPlaylistRequest, db: AsyncSession = Depends(get_db)):
    """Generate a smart playlist based on rules."""
    from backend.models.track import Track
    from backend.models.analysis import TrackAnalysis

    query = select(Track)

    if req.rule == "genre":
        query = query.where(Track.genre.ilike(f"%{req.value}%"))
    elif req.rule == "bpm_range" and req.value:
        parts = req.value.split("-")
        if len(parts) == 2:
            low, high = float(parts[0]), float(parts[1])
            query = query.join(TrackAnalysis).where(
                TrackAnalysis.bpm >= low, TrackAnalysis.bpm <= high
            )
    elif req.rule == "recent":
        query = query.order_by(Track.created_at.desc())
    elif req.rule == "top_played":
        query = query.where(Track.play_count > 0).order_by(Track.play_count.desc())
    elif req.rule == "random":
        query = query.order_by(func.random())
    else:
        return {"error": f"Unknown rule: {req.rule}"}

    query = query.limit(req.limit)
    result = await db.execute(query)
    tracks = result.scalars().all()

    if not tracks:
        return {"error": "No tracks match the criteria"}

    playlist = Playlist(
        id=str(uuid.uuid4()),
        name=req.name,
        user_id="admin",
        comment=f"Auto-generated: {req.rule}" + (f" ({req.value})" if req.value else ""),
    )
    db.add(playlist)
    for i, t in enumerate(tracks):
        db.add(PlaylistTrack(id=str(uuid.uuid4()), playlist_id=playlist.id, track_id=t.id, position=i))
    await db.commit()

    return {"id": playlist.id, "name": playlist.name, "track_count": len(tracks)}


@router.get("/{playlist_id}")
async def get_playlist(playlist_id: str, db: AsyncSession = Depends(get_db)):
    from backend.models.track import Track
    from backend.models.artist import Artist
    from backend.models.album import Album

    result = await db.execute(
        select(Playlist).options(
            selectinload(Playlist.entries).selectinload(
                PlaylistTrack.track
            ).selectinload(Track.artist),
            selectinload(Playlist.entries).selectinload(
                PlaylistTrack.track
            ).selectinload(Track.album),
        ).where(Playlist.id == playlist_id)
    )
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "Playlist not found")
    entries = sorted([e for e in p.entries if e.track], key=lambda e: e.position)
    return {
        "id": p.id,
        "name": p.name,
        "comment": p.comment,
        "tracks": [
            {
                "id": e.track.id,
                "title": e.track.title,
                "artist": e.track.artist.name if e.track.artist else None,
                "album": e.track.album.title if e.track.album else None,
                "cover_art": e.track.album_id or e.track.id,
                "position": e.position,
                "duration": e.track.duration_seconds,
            }
            for e in entries
        ],
    }


@router.put("/{playlist_id}")
async def update_playlist(playlist_id: str, req: PlaylistUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Playlist).where(Playlist.id == playlist_id))
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "Playlist not found")

    if req.name is not None:
        p.name = req.name
    if req.comment is not None:
        p.comment = req.comment
    if req.track_ids is not None:
        await db.execute(delete(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist_id))
        for i, tid in enumerate(req.track_ids):
            db.add(PlaylistTrack(id=str(uuid.uuid4()), playlist_id=playlist_id, track_id=tid, position=i))
    p.updated_at = datetime.utcnow()
    await db.commit()
    return {"ok": True}


@router.delete("/{playlist_id}")
async def delete_playlist(playlist_id: str, db: AsyncSession = Depends(get_db)):
    await db.execute(delete(Playlist).where(Playlist.id == playlist_id))
    await db.commit()
    return {"ok": True}
