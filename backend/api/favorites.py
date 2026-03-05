from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.models.favorite import Favorite
from backend.models.track import Track
from backend.models.artist import Artist
from backend.models.album import Album

from backend.models.user import User

router = APIRouter()


async def _resolve_user_id(username: str, db: AsyncSession) -> str:
    """Resolve username to user ID."""
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    return user.id if user else username


class StarRequest(BaseModel):
    track_id: str | None = None
    album_id: str | None = None
    artist_id: str | None = None


@router.get("")
async def list_favorites(
    user_id: str = "admin",
    offset: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    user_id = await _resolve_user_id(user_id, db)
    total = (await db.execute(
        select(func.count()).select_from(Favorite).where(Favorite.user_id == user_id)
    )).scalar()
    result = await db.execute(
        select(Favorite)
        .options(
            selectinload(Favorite.track).selectinload(Track.artist),
            selectinload(Favorite.track).selectinload(Track.album),
            selectinload(Favorite.album),
            selectinload(Favorite.artist),
        )
        .where(Favorite.user_id == user_id)
        .order_by(Favorite.starred_at.desc())
        .offset(offset)
        .limit(limit)
    )
    favs = result.scalars().all()
    out = []
    for f in favs:
        item = {
            "id": f.id,
            "track_id": f.track_id,
            "album_id": f.album_id,
            "artist_id": f.artist_id,
            "starred_at": f.starred_at.isoformat() if f.starred_at else None,
        }
        if f.track:
            item["title"] = f.track.title
            item["artist"] = f.track.artist.name if f.track.artist else None
            item["album"] = f.track.album.title if f.track.album else None
            item["cover_art"] = f.track.album_id or f.track.id
            item["duration"] = f.track.duration_seconds
        elif f.album:
            item["title"] = f.album.title
            item["cover_art"] = f.album.id
        elif f.artist:
            item["title"] = f.artist.name
            item["cover_art"] = f.artist.id
        out.append(item)
    return {"items": out, "total": total}


@router.get("/ids")
async def favorite_ids(user_id: str = "admin", db: AsyncSession = Depends(get_db)):
    """Return sets of favorited track/album/artist IDs for quick lookup."""
    user_id = await _resolve_user_id(user_id, db)
    result = await db.execute(
        select(Favorite.track_id, Favorite.album_id, Favorite.artist_id)
        .where(Favorite.user_id == user_id)
    )
    rows = result.all()
    return {
        "track_ids": [r[0] for r in rows if r[0]],
        "album_ids": [r[1] for r in rows if r[1]],
        "artist_ids": [r[2] for r in rows if r[2]],
    }


@router.post("/star")
async def star(req: StarRequest, user_id: str = "admin", db: AsyncSession = Depends(get_db)):
    user_id = await _resolve_user_id(user_id, db)
    # Check for existing favorite to avoid duplicate
    query = select(Favorite).where(Favorite.user_id == user_id)
    if req.track_id:
        query = query.where(Favorite.track_id == req.track_id)
    elif req.album_id:
        query = query.where(Favorite.album_id == req.album_id)
    elif req.artist_id:
        query = query.where(Favorite.artist_id == req.artist_id)
    existing = (await db.execute(query)).scalar_one_or_none()
    if existing:
        return {"ok": True, "already_starred": True}

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
    user_id = await _resolve_user_id(user_id, db)
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


class ImportRequest(BaseModel):
    tracks: list[dict]  # [{title, artist, file_path?}]


@router.post("/import")
async def import_favorites(req: ImportRequest, user_id: str = "admin", db: AsyncSession = Depends(get_db)):
    """Import favorites from external source (e.g. KimaHub).

    Matches tracks by file_path (relative) or by title+artist.
    """
    user_id = await _resolve_user_id(user_id, db)
    imported = 0
    skipped = 0
    not_found = 0

    for item in req.tracks:
        track = None

        # Try file_path match first (most reliable)
        if item.get("file_path"):
            file_path = item["file_path"]
            # Generate the same MD5 ID that Zonik uses
            track_id = hashlib.md5(file_path.encode()).hexdigest()
            track = await db.get(Track, track_id)

        # Fallback: title + artist match
        if not track and item.get("title") and item.get("artist"):
            result = await db.execute(
                select(Track).join(Artist, Track.artist_id == Artist.id).where(
                    Track.title == item["title"],
                    Artist.name == item["artist"],
                ).limit(1)
            )
            track = result.scalar_one_or_none()

        if not track:
            not_found += 1
            continue

        # Check if already favorited
        existing = (await db.execute(
            select(Favorite).where(
                Favorite.user_id == user_id,
                Favorite.track_id == track.id,
            )
        )).scalar_one_or_none()

        if existing:
            skipped += 1
            continue

        fav = Favorite(
            id=str(uuid.uuid4()),
            user_id=user_id,
            track_id=track.id,
            starred_at=datetime.utcnow(),
        )
        db.add(fav)
        imported += 1

    await db.commit()
    return {"imported": imported, "skipped": skipped, "not_found": not_found, "total": len(req.tracks)}
