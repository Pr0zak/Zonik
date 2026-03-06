"""Subsonic annotation endpoints: star, unstar, scrobble, setRating."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Request, Depends
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.favorite import Favorite
from backend.models.track import Track
from backend.models.user import User
from backend.subsonic.auth import authenticate_subsonic
from backend.subsonic.responses import subsonic_response, error_response

router = APIRouter()


def _get_format(request: Request) -> str:
    return request.query_params.get("f", "json")


async def _get_user_id(request: Request) -> str:
    """Get user ID from request params."""
    username = request.query_params.get("u", "admin")
    return username  # Simplified - use username as lookup key


@router.get("/star")
@router.get("/star.view")
@router.post("/star")
@router.post("/star.view")
async def star(request: Request, db: AsyncSession = Depends(get_db)):
    params = dict(request.query_params)
    if request.method == "POST":
        try:
            form = await request.form()
            params.update(form)
        except Exception:
            pass

    # Get the user
    username = params.get("u", "admin")
    user_result = await db.execute(select(User).where(User.username == username))
    user = user_result.scalar_one_or_none()
    if not user:
        return error_response(0, "User not found", _get_format(request))

    # Star can receive id, albumId, or artistId (can be multiple)
    song_ids = params.getlist("id") if hasattr(params, "getlist") else [params.get("id")] if params.get("id") else []
    album_ids = params.getlist("albumId") if hasattr(params, "getlist") else [params.get("albumId")] if params.get("albumId") else []
    artist_ids = params.getlist("artistId") if hasattr(params, "getlist") else [params.get("artistId")] if params.get("artistId") else []

    for sid in song_ids:
        if sid:
            existing = await db.execute(
                select(Favorite).where(Favorite.user_id == user.id, Favorite.track_id == sid)
            )
            if not existing.scalar_one_or_none():
                db.add(Favorite(
                    id=str(uuid.uuid4()), user_id=user.id, track_id=sid, starred_at=datetime.utcnow()
                ))

    for aid in album_ids:
        if aid:
            existing = await db.execute(
                select(Favorite).where(Favorite.user_id == user.id, Favorite.album_id == aid)
            )
            if not existing.scalar_one_or_none():
                db.add(Favorite(
                    id=str(uuid.uuid4()), user_id=user.id, album_id=aid, starred_at=datetime.utcnow()
                ))

    for aid in artist_ids:
        if aid:
            existing = await db.execute(
                select(Favorite).where(Favorite.user_id == user.id, Favorite.artist_id == aid)
            )
            if not existing.scalar_one_or_none():
                db.add(Favorite(
                    id=str(uuid.uuid4()), user_id=user.id, artist_id=aid, starred_at=datetime.utcnow()
                ))

    await db.commit()
    return subsonic_response({}, _get_format(request))


@router.get("/unstar")
@router.get("/unstar.view")
@router.post("/unstar")
@router.post("/unstar.view")
async def unstar(request: Request, db: AsyncSession = Depends(get_db)):
    params = dict(request.query_params)
    if request.method == "POST":
        try:
            form = await request.form()
            params.update(form)
        except Exception:
            pass

    username = params.get("u", "admin")
    user_result = await db.execute(select(User).where(User.username == username))
    user = user_result.scalar_one_or_none()
    if not user:
        return error_response(0, "User not found", _get_format(request))

    song_ids = params.getlist("id") if hasattr(params, "getlist") else [params.get("id")] if params.get("id") else []
    album_ids = params.getlist("albumId") if hasattr(params, "getlist") else [params.get("albumId")] if params.get("albumId") else []
    artist_ids = params.getlist("artistId") if hasattr(params, "getlist") else [params.get("artistId")] if params.get("artistId") else []

    for sid in song_ids:
        if sid:
            await db.execute(delete(Favorite).where(Favorite.user_id == user.id, Favorite.track_id == sid))
    for aid in album_ids:
        if aid:
            await db.execute(delete(Favorite).where(Favorite.user_id == user.id, Favorite.album_id == aid))
    for aid in artist_ids:
        if aid:
            await db.execute(delete(Favorite).where(Favorite.user_id == user.id, Favorite.artist_id == aid))

    await db.commit()
    return subsonic_response({}, _get_format(request))


@router.get("/scrobble")
@router.get("/scrobble.view")
@router.post("/scrobble")
@router.post("/scrobble.view")
async def scrobble(request: Request, db: AsyncSession = Depends(get_db)):
    params = dict(request.query_params)
    song_id = params.get("id")
    submission = params.get("submission", "true")

    if not song_id:
        return error_response(10, "Missing id parameter", _get_format(request))

    if submission == "true":
        # Update play count and record history
        result = await db.execute(select(Track).where(Track.id == song_id))
        track = result.scalar_one_or_none()
        if track:
            track.play_count = (track.play_count or 0) + 1
            track.last_played_at = datetime.utcnow()
            from backend.models.play_history import PlayHistory
            db.add(PlayHistory(track_id=song_id, played_at=datetime.utcnow(), source="subsonic"))
            await db.commit()

    return subsonic_response({}, _get_format(request))


@router.get("/setRating")
@router.get("/setRating.view")
@router.post("/setRating")
@router.post("/setRating.view")
async def set_rating(request: Request, db: AsyncSession = Depends(get_db)):
    params = dict(request.query_params)
    if request.method == "POST":
        try:
            form = await request.form()
            params.update(form)
        except Exception:
            pass

    song_id = params.get("id")
    rating_str = params.get("rating", "0")

    if not song_id:
        return error_response(10, "Missing id parameter", _get_format(request))

    try:
        rating = int(rating_str)
    except (ValueError, TypeError):
        return error_response(10, "Invalid rating", _get_format(request))

    if rating < 0 or rating > 5:
        return error_response(10, "Rating must be 0-5", _get_format(request))

    result = await db.execute(select(Track).where(Track.id == song_id))
    track = result.scalar_one_or_none()
    if not track:
        return error_response(70, "Song not found", _get_format(request))

    track.rating = rating if rating > 0 else None
    await db.commit()
    return subsonic_response({}, _get_format(request))
