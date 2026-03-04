from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.models.playlist import Playlist, PlaylistTrack

router = APIRouter()


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


@router.get("/{playlist_id}")
async def get_playlist(playlist_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Playlist).options(
            selectinload(Playlist.entries).selectinload(PlaylistTrack.track)
        ).where(Playlist.id == playlist_id)
    )
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(404, "Playlist not found")
    return {
        "id": p.id,
        "name": p.name,
        "comment": p.comment,
        "tracks": [
            {
                "id": e.track.id,
                "title": e.track.title,
                "position": e.position,
                "duration": e.track.duration_seconds,
            }
            for e in p.entries if e.track
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
