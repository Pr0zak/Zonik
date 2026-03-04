from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.models.favorite import Favorite
from backend.models.track import Track

router = APIRouter()


class StarRequest(BaseModel):
    track_id: str | None = None
    album_id: str | None = None
    artist_id: str | None = None


@router.get("")
async def list_favorites(user_id: str = "admin", db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Favorite)
        .options(selectinload(Favorite.track), selectinload(Favorite.album), selectinload(Favorite.artist))
        .where(Favorite.user_id == user_id)
        .order_by(Favorite.starred_at.desc())
    )
    favs = result.scalars().all()
    return [
        {
            "id": f.id,
            "track_id": f.track_id,
            "album_id": f.album_id,
            "artist_id": f.artist_id,
            "track_title": f.track.title if f.track else None,
            "starred_at": f.starred_at.isoformat() if f.starred_at else None,
        }
        for f in favs
    ]


@router.post("/star")
async def star(req: StarRequest, user_id: str = "admin", db: AsyncSession = Depends(get_db)):
    fav = Favorite(
        id=str(uuid.uuid4()),
        user_id=user_id,
        track_id=req.track_id,
        album_id=req.album_id,
        artist_id=req.artist_id,
        starred_at=datetime.utcnow(),
    )
    db.add(fav)
    await db.commit()
    return {"ok": True}


@router.post("/unstar")
async def unstar(req: StarRequest, user_id: str = "admin", db: AsyncSession = Depends(get_db)):
    query = delete(Favorite).where(Favorite.user_id == user_id)
    if req.track_id:
        query = query.where(Favorite.track_id == req.track_id)
    if req.album_id:
        query = query.where(Favorite.album_id == req.album_id)
    if req.artist_id:
        query = query.where(Favorite.artist_id == req.artist_id)
    await db.execute(query)
    await db.commit()
    return {"ok": True}
