"""Subsonic bookmarks and play queue endpoints."""
from __future__ import annotations

import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Request, Depends
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.models.bookmark import Bookmark
from backend.models.play_queue import PlayQueue
from backend.models.track import Track
from backend.models.user import User
from backend.subsonic.responses import subsonic_response, error_response, format_track

router = APIRouter()


def _get_format(request: Request) -> str:
    return request.query_params.get("f", "json")


@router.get("/getBookmarks")
@router.get("/getBookmarks.view")
async def get_bookmarks(request: Request, db: AsyncSession = Depends(get_db)):
    username = request.query_params.get("u", "admin")
    user_result = await db.execute(select(User).where(User.username == username))
    user = user_result.scalar_one_or_none()
    if not user:
        return subsonic_response({"bookmarks": {}}, _get_format(request))

    result = await db.execute(
        select(Bookmark).options(
            selectinload(Bookmark.track).selectinload(Track.artist),
            selectinload(Bookmark.track).selectinload(Track.album),
        ).where(Bookmark.user_id == user.id)
    )
    bookmarks = result.scalars().all()

    return subsonic_response({
        "bookmarks": {
            "bookmark": [
                {
                    "position": b.position_ms,
                    "username": username,
                    "comment": b.comment or "",
                    "created": b.created_at.strftime("%Y-%m-%dT%H:%M:%S.000Z") if b.created_at else "",
                    "changed": b.updated_at.strftime("%Y-%m-%dT%H:%M:%S.000Z") if b.updated_at else "",
                    "entry": format_track(b.track) if b.track else {},
                }
                for b in bookmarks
            ]
        }
    }, _get_format(request))


@router.get("/createBookmark")
@router.get("/createBookmark.view")
@router.post("/createBookmark")
@router.post("/createBookmark.view")
async def create_bookmark(request: Request, db: AsyncSession = Depends(get_db)):
    params = dict(request.query_params)
    song_id = params.get("id")
    position = int(params.get("position", 0))
    comment = params.get("comment")

    username = params.get("u", "admin")
    user_result = await db.execute(select(User).where(User.username == username))
    user = user_result.scalar_one_or_none()
    if not user or not song_id:
        return error_response(10, "Missing parameters", _get_format(request))

    # Upsert bookmark
    result = await db.execute(
        select(Bookmark).where(Bookmark.user_id == user.id, Bookmark.track_id == song_id)
    )
    bookmark = result.scalar_one_or_none()
    if bookmark:
        bookmark.position_ms = position
        bookmark.comment = comment
        bookmark.updated_at = datetime.utcnow()
    else:
        db.add(Bookmark(
            id=str(uuid.uuid4()), user_id=user.id, track_id=song_id,
            position_ms=position, comment=comment,
        ))
    await db.commit()
    return subsonic_response({}, _get_format(request))


@router.get("/deleteBookmark")
@router.get("/deleteBookmark.view")
async def delete_bookmark(request: Request, db: AsyncSession = Depends(get_db)):
    song_id = request.query_params.get("id")
    username = request.query_params.get("u", "admin")
    user_result = await db.execute(select(User).where(User.username == username))
    user = user_result.scalar_one_or_none()
    if user and song_id:
        await db.execute(
            delete(Bookmark).where(Bookmark.user_id == user.id, Bookmark.track_id == song_id)
        )
        await db.commit()
    return subsonic_response({}, _get_format(request))


@router.get("/getPlayQueue")
@router.get("/getPlayQueue.view")
async def get_play_queue(request: Request, db: AsyncSession = Depends(get_db)):
    username = request.query_params.get("u", "admin")
    user_result = await db.execute(select(User).where(User.username == username))
    user = user_result.scalar_one_or_none()
    if not user:
        return subsonic_response({"playQueue": {}}, _get_format(request))

    result = await db.execute(select(PlayQueue).where(PlayQueue.user_id == user.id))
    pq = result.scalar_one_or_none()
    if not pq or not pq.track_ids:
        return subsonic_response({"playQueue": {}}, _get_format(request))

    track_ids = json.loads(pq.track_ids) if pq.track_ids else []
    tracks_result = await db.execute(
        select(Track).options(
            selectinload(Track.artist), selectinload(Track.album), selectinload(Track.analysis)
        ).where(Track.id.in_(track_ids))
    )
    tracks = {t.id: t for t in tracks_result.scalars().all()}

    entries = [format_track(tracks[tid]) for tid in track_ids if tid in tracks]

    return subsonic_response({
        "playQueue": {
            "entry": entries,
            "current": pq.current_track_id,
            "position": pq.position_ms,
            "username": username,
            "changed": pq.updated_at.strftime("%Y-%m-%dT%H:%M:%S.000Z") if pq.updated_at else "",
        }
    }, _get_format(request))


@router.get("/savePlayQueue")
@router.get("/savePlayQueue.view")
@router.post("/savePlayQueue")
@router.post("/savePlayQueue.view")
async def save_play_queue(request: Request, db: AsyncSession = Depends(get_db)):
    params = dict(request.query_params)
    username = params.get("u", "admin")
    current = params.get("current")
    position = int(params.get("position", 0))

    # Get song IDs
    song_ids = []
    if hasattr(request.query_params, "getlist"):
        song_ids = request.query_params.getlist("id")
    elif "id" in params:
        song_ids = [params["id"]]

    user_result = await db.execute(select(User).where(User.username == username))
    user = user_result.scalar_one_or_none()
    if not user:
        return error_response(0, "User not found", _get_format(request))

    result = await db.execute(select(PlayQueue).where(PlayQueue.user_id == user.id))
    pq = result.scalar_one_or_none()
    if pq:
        pq.track_ids = json.dumps(song_ids)
        pq.current_track_id = current
        pq.position_ms = position
        pq.updated_at = datetime.utcnow()
    else:
        db.add(PlayQueue(
            user_id=user.id,
            track_ids=json.dumps(song_ids),
            current_track_id=current,
            position_ms=position,
        ))
    await db.commit()
    return subsonic_response({}, _get_format(request))
