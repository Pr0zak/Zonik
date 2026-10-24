"""Subsonic playlist endpoints.

Per user (multi-user P2): getPlaylists lists the caller's own playlists plus everyone's
public ones; getPlaylist reads any of those; only the owner (or an admin) may change or
delete one. `owner` is the owner's username, `public` the is_public flag.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Request, Depends
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.models.playlist import Playlist, PlaylistTrack
from backend.models.track import Track
from backend.models.user import User
from backend.services.user_data import (
    caller_user, can_edit_playlist, can_read_playlist, visible_playlists_clause,
)
from backend.subsonic.personal import personal_view
from backend.subsonic.responses import subsonic_response, error_response, format_track

router = APIRouter()

_TRUE = ("true", "1", "yes")


def _get_format(request: Request) -> str:
    return request.query_params.get("f", "json")


async def _params(request: Request) -> dict:
    params = dict(request.query_params)
    if request.method == "POST":
        try:
            form = await request.form()
            params.update(form)
        except Exception:
            pass
    return params


def _song_ids(request: Request, params: dict, name: str) -> list[str]:
    values = [v for v in request.query_params.getlist(name) if v]
    if not values and params.get(name):
        values = [params[name]]
    return values


async def _usernames(db: AsyncSession, user_ids) -> dict[str, str]:
    ids = [u for u in set(user_ids) if u]
    if not ids:
        return {}
    rows = (await db.execute(select(User.id, User.username).where(User.id.in_(ids)))).all()
    return {r[0]: r[1] for r in rows}


def _dt(value) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S.000Z") if value else ""


def _not_allowed(request: Request):
    return error_response(50, "User is not authorized for the given operation", _get_format(request))


@router.get("/getPlaylists")
@router.get("/getPlaylists.view")
async def get_playlists(request: Request, db: AsyncSession = Depends(get_db)):
    me = await caller_user(request, db)
    result = await db.execute(
        select(Playlist).options(selectinload(Playlist.entries))
        .where(visible_playlists_clause(me))
        .order_by(Playlist.name)
    )
    playlists = result.scalars().all()
    owners = await _usernames(db, (p.user_id for p in playlists))

    # One query for every playlist's duration.
    total_durations: dict[str, int] = {}
    if playlists:
        rows = (await db.execute(
            select(PlaylistTrack.playlist_id, func.sum(Track.duration_seconds))
            .join(Track, Track.id == PlaylistTrack.track_id)
            .where(PlaylistTrack.playlist_id.in_([p.id for p in playlists]))
            .group_by(PlaylistTrack.playlist_id)
        )).all()
        total_durations = {pid: int(dur or 0) for pid, dur in rows}

    return subsonic_response({
        "playlists": {
            "playlist": [
                {
                    "id": p.id,
                    "name": p.name,
                    "comment": p.comment or "",
                    "owner": owners.get(p.user_id, ""),
                    "songCount": len(p.entries),
                    "duration": total_durations.get(p.id, 0),
                    "public": str(bool(p.is_public)).lower(),
                    "created": _dt(p.created_at),
                    "changed": _dt(p.updated_at),
                    "coverArt": "",
                }
                for p in playlists
            ]
        }
    }, _get_format(request))


@router.get("/getPlaylist")
@router.get("/getPlaylist.view")
async def get_playlist(request: Request, db: AsyncSession = Depends(get_db)):
    playlist_id = request.query_params.get("id")
    if not playlist_id:
        return error_response(10, "Missing id parameter", _get_format(request))

    result = await db.execute(
        select(Playlist).options(
            selectinload(Playlist.entries).selectinload(PlaylistTrack.track).selectinload(Track.artist),
            selectinload(Playlist.entries).selectinload(PlaylistTrack.track).selectinload(Track.album),
            selectinload(Playlist.entries).selectinload(PlaylistTrack.track).selectinload(Track.analysis),
        ).where(Playlist.id == playlist_id)
    )
    p = result.scalar_one_or_none()
    me = await caller_user(request, db)
    if not p or not can_read_playlist(me, p):
        return error_response(70, "Playlist not found", _get_format(request))

    tracks = [e.track for e in p.entries if e.track]
    personal = await personal_view(request, db, tracks=tracks, user_id=me.id if me else None)
    songs = [format_track(t, personal=personal) for t in tracks]
    total_dur = sum(int(s.get("duration", 0)) for s in songs)
    owners = await _usernames(db, [p.user_id])

    return subsonic_response({
        "playlist": {
            "id": p.id,
            "name": p.name,
            "comment": p.comment or "",
            "owner": owners.get(p.user_id, ""),
            "songCount": len(songs),
            "duration": total_dur,
            "public": str(bool(p.is_public)).lower(),
            "created": _dt(p.created_at),
            "changed": _dt(p.updated_at),
            "entry": songs,
        }
    }, _get_format(request))


@router.get("/createPlaylist")
@router.get("/createPlaylist.view")
@router.post("/createPlaylist")
@router.post("/createPlaylist.view")
async def create_playlist(request: Request, db: AsyncSession = Depends(get_db)):
    params = await _params(request)

    playlist_id = params.get("playlistId")
    name = params.get("name", "Untitled")
    me = await caller_user(request, db)
    song_ids = _song_ids(request, params, "songId")

    if playlist_id:
        # Update existing (owner or admin only)
        result = await db.execute(select(Playlist).where(Playlist.id == playlist_id))
        playlist = result.scalar_one_or_none()
        if playlist:
            if not can_read_playlist(me, playlist):
                return error_response(70, "Playlist not found", _get_format(request))
            if not can_edit_playlist(me, playlist):
                return _not_allowed(request)
            if name:
                playlist.name = name
            if song_ids:
                await db.execute(delete(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist_id))
                for i, sid in enumerate(song_ids):
                    db.add(PlaylistTrack(
                        id=str(uuid.uuid4()), playlist_id=playlist_id, track_id=sid, position=i
                    ))
            playlist.updated_at = datetime.utcnow()
    else:
        # Create new, owned by the caller
        playlist = Playlist(
            id=str(uuid.uuid4()),
            name=name,
            user_id=me.id if me else None,
        )
        db.add(playlist)
        await db.flush()
        for i, sid in enumerate(song_ids):
            db.add(PlaylistTrack(
                id=str(uuid.uuid4()), playlist_id=playlist.id, track_id=sid, position=i
            ))

    await db.commit()
    return subsonic_response({}, _get_format(request))


@router.get("/updatePlaylist")
@router.get("/updatePlaylist.view")
@router.post("/updatePlaylist")
@router.post("/updatePlaylist.view")
async def update_playlist(request: Request, db: AsyncSession = Depends(get_db)):
    params = await _params(request)
    playlist_id = params.get("playlistId")
    if not playlist_id:
        return error_response(10, "Missing playlistId", _get_format(request))

    result = await db.execute(select(Playlist).where(Playlist.id == playlist_id))
    playlist = result.scalar_one_or_none()
    me = await caller_user(request, db)
    if not playlist or not can_read_playlist(me, playlist):
        return error_response(70, "Playlist not found", _get_format(request))
    if not can_edit_playlist(me, playlist):
        return _not_allowed(request)

    if "name" in params:
        playlist.name = params["name"]
    if "comment" in params:
        playlist.comment = params["comment"]
    if "public" in params:
        playlist.is_public = str(params["public"]).strip().lower() in _TRUE

    # Handle songIdToAdd
    songs_to_add = _song_ids(request, params, "songIdToAdd")
    if songs_to_add:
        max_pos = 0
        for e in (await db.execute(
            select(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist_id)
        )).scalars().all():
            max_pos = max(max_pos, e.position + 1)
        for i, sid in enumerate(songs_to_add):
            db.add(PlaylistTrack(
                id=str(uuid.uuid4()), playlist_id=playlist_id, track_id=sid, position=max_pos + i
            ))

    # Handle songIndexToRemove
    idx_to_remove = params.get("songIndexToRemove")
    if idx_to_remove is not None:
        idx = int(idx_to_remove)
        entries = (await db.execute(
            select(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist_id)
            .order_by(PlaylistTrack.position)
        )).scalars().all()
        if 0 <= idx < len(entries):
            await db.delete(entries[idx])

    playlist.updated_at = datetime.utcnow()
    await db.commit()
    return subsonic_response({}, _get_format(request))


@router.get("/deletePlaylist")
@router.get("/deletePlaylist.view")
async def delete_playlist(request: Request, db: AsyncSession = Depends(get_db)):
    playlist_id = request.query_params.get("id")
    if not playlist_id:
        return error_response(10, "Missing id", _get_format(request))

    playlist = await db.get(Playlist, playlist_id)
    me = await caller_user(request, db)
    if playlist is not None:
        if not can_read_playlist(me, playlist):
            return error_response(70, "Playlist not found", _get_format(request))
        if not can_edit_playlist(me, playlist):
            return _not_allowed(request)

    await db.execute(delete(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist_id))
    await db.execute(delete(Playlist).where(Playlist.id == playlist_id))
    await db.commit()
    return subsonic_response({}, _get_format(request))
