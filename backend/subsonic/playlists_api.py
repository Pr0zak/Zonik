"""Subsonic playlist endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Request, Depends
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.models.playlist import Playlist, PlaylistTrack
from backend.models.track import Track
from backend.models.user import User
from backend.subsonic.responses import subsonic_response, error_response, format_track

router = APIRouter()


def _get_format(request: Request) -> str:
    return request.query_params.get("f", "json")


@router.get("/getPlaylists")
@router.get("/getPlaylists.view")
async def get_playlists(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Playlist).options(selectinload(Playlist.entries)).order_by(Playlist.name)
    )
    playlists = result.scalars().all()

    total_durations = {}
    for p in playlists:
        track_ids = [e.track_id for e in p.entries]
        if track_ids:
            from sqlalchemy import func
            dur = (await db.execute(
                select(func.sum(Track.duration_seconds)).where(Track.id.in_(track_ids))
            )).scalar() or 0
            total_durations[p.id] = int(dur)

    return subsonic_response({
        "playlists": {
            "playlist": [
                {
                    "id": p.id,
                    "name": p.name,
                    "comment": p.comment or "",
                    "songCount": len(p.entries),
                    "duration": total_durations.get(p.id, 0),
                    "public": str(p.is_public).lower(),
                    "created": p.created_at.strftime("%Y-%m-%dT%H:%M:%S.000Z") if p.created_at else "",
                    "changed": p.updated_at.strftime("%Y-%m-%dT%H:%M:%S.000Z") if p.updated_at else "",
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
    if not p:
        return error_response(70, "Playlist not found", _get_format(request))

    songs = [format_track(e.track) for e in p.entries if e.track]
    total_dur = sum(int(s.get("duration", 0)) for s in songs)

    return subsonic_response({
        "playlist": {
            "id": p.id,
            "name": p.name,
            "comment": p.comment or "",
            "songCount": len(songs),
            "duration": total_dur,
            "public": str(p.is_public).lower(),
            "created": p.created_at.strftime("%Y-%m-%dT%H:%M:%S.000Z") if p.created_at else "",
            "changed": p.updated_at.strftime("%Y-%m-%dT%H:%M:%S.000Z") if p.updated_at else "",
            "entry": songs,
        }
    }, _get_format(request))


@router.get("/createPlaylist")
@router.get("/createPlaylist.view")
@router.post("/createPlaylist")
@router.post("/createPlaylist.view")
async def create_playlist(request: Request, db: AsyncSession = Depends(get_db)):
    params = dict(request.query_params)
    if request.method == "POST":
        try:
            form = await request.form()
            params.update(form)
        except Exception:
            pass

    playlist_id = params.get("playlistId")
    name = params.get("name", "Untitled")

    username = params.get("u", "admin")
    user_result = await db.execute(select(User).where(User.username == username))
    user = user_result.scalar_one_or_none()

    # Get song IDs
    song_ids = []
    if hasattr(request.query_params, "getlist"):
        song_ids = request.query_params.getlist("songId")
    elif "songId" in params:
        song_ids = [params["songId"]]

    if playlist_id:
        # Update existing
        result = await db.execute(select(Playlist).where(Playlist.id == playlist_id))
        playlist = result.scalar_one_or_none()
        if playlist:
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
        # Create new
        playlist = Playlist(
            id=str(uuid.uuid4()),
            name=name,
            user_id=user.id if user else None,
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
    params = dict(request.query_params)
    playlist_id = params.get("playlistId")
    if not playlist_id:
        return error_response(10, "Missing playlistId", _get_format(request))

    result = await db.execute(select(Playlist).where(Playlist.id == playlist_id))
    playlist = result.scalar_one_or_none()
    if not playlist:
        return error_response(70, "Playlist not found", _get_format(request))

    if "name" in params:
        playlist.name = params["name"]
    if "comment" in params:
        playlist.comment = params["comment"]

    # Handle songIdToAdd
    song_to_add = params.get("songIdToAdd")
    if song_to_add:
        max_pos = 0
        for e in (await db.execute(
            select(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist_id)
        )).scalars().all():
            max_pos = max(max_pos, e.position + 1)
        db.add(PlaylistTrack(
            id=str(uuid.uuid4()), playlist_id=playlist_id, track_id=song_to_add, position=max_pos
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

    await db.execute(delete(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist_id))
    await db.execute(delete(Playlist).where(Playlist.id == playlist_id))
    await db.commit()
    return subsonic_response({}, _get_format(request))
