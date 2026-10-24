from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.models.playlist import Playlist, PlaylistTrack
from backend.models.user import User
from backend.services.user_data import (
    caller_user, can_edit_playlist, can_read_playlist, visible_playlists_clause,
)

router = APIRouter()

# Per user (multi-user P2): the list is the caller's own playlists plus everyone's public
# ones; any of those can be read; only the owner (or an admin) may change or delete one.
# New playlists — plain, smart, AI and imported — belong to the caller.


async def _owners(db: AsyncSession, user_ids) -> dict[str, dict]:
    ids = [u for u in set(user_ids) if u]
    if not ids:
        return {}
    rows = (await db.execute(
        select(User.id, User.username, User.display_name).where(User.id.in_(ids))
    )).all()
    return {r[0]: {"id": r[0], "username": r[1], "display_name": r[2]} for r in rows}


def _access(p: Playlist, me, owners: dict) -> dict:
    """The ownership fields every playlist item carries."""
    return {
        "owner": owners.get(p.user_id),
        "is_public": bool(p.is_public),
        "can_edit": can_edit_playlist(me, p),
    }


async def _editable(db: AsyncSession, request: Request, playlist_id: str) -> Playlist:
    """The playlist if the caller may change it: 404 if they can't see it, 403 if they can't edit."""
    p = (await db.execute(select(Playlist).where(Playlist.id == playlist_id))).scalar_one_or_none()
    me = await caller_user(request, db)
    if not p or not can_read_playlist(me, p):
        raise HTTPException(404, "Playlist not found")
    if not can_edit_playlist(me, p):
        raise HTTPException(403, "Only the playlist's owner can change it")
    return p


class SmartPlaylistRequest(BaseModel):
    name: str
    rule: str  # "genre", "bpm_range", "recent", "top_played", "random"
    value: str | None = None  # e.g. genre name, "120-140" for BPM range
    limit: int = 50


class PlaylistCreate(BaseModel):
    name: str
    comment: str | None = None
    track_ids: list[str] = []
    is_public: bool = False


class PlaylistUpdate(BaseModel):
    name: str | None = None
    comment: str | None = None
    track_ids: list[str] | None = None
    is_public: bool | None = None


@router.get("")
async def list_playlists(request: Request, db: AsyncSession = Depends(get_db)):
    me = await caller_user(request, db)
    result = await db.execute(
        select(Playlist).options(selectinload(Playlist.entries))
        .where(visible_playlists_clause(me))
        .order_by(Playlist.updated_at.desc())
    )
    playlists = result.scalars().all()
    owners = await _owners(db, (p.user_id for p in playlists))
    return [
        {
            "id": p.id,
            "name": p.name,
            "comment": p.comment,
            "track_count": len(p.entries),
            # First track's art stands in for the playlist cover (getCoverArt accepts a track id).
            "cover_art": p.entries[0].track_id if p.entries else None,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
            **_access(p, me, owners),
        }
        for p in playlists
    ]


@router.post("")
async def create_playlist(req: PlaylistCreate, request: Request, db: AsyncSession = Depends(get_db)):
    # Owned by the caller (the owner for anonymous grace-mode requests); never a param.
    me = await caller_user(request, db)
    playlist = Playlist(
        id=str(uuid.uuid4()),
        name=req.name,
        user_id=me.id if me else None,
        comment=req.comment,
        is_public=req.is_public,
    )
    db.add(playlist)
    for i, tid in enumerate(req.track_ids):
        db.add(PlaylistTrack(id=str(uuid.uuid4()), playlist_id=playlist.id, track_id=tid, position=i))
    await db.commit()
    return {"id": playlist.id, "name": playlist.name}


@router.post("/generate")
async def generate_smart_playlist(req: SmartPlaylistRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Generate a smart playlist based on rules ("top_played" = the caller's most played)."""
    from backend.models.track import Track
    from backend.models.analysis import TrackAnalysis
    from backend.models.user_track_stats import UserTrackStats

    me = await caller_user(request, db)
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
        query = (
            query.join(UserTrackStats, UserTrackStats.track_id == Track.id)
            .where(UserTrackStats.user_id == (me.id if me else None), UserTrackStats.play_count > 0)
            .order_by(UserTrackStats.play_count.desc())
        )
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
        user_id=me.id if me else None,
        comment=f"Auto-generated: {req.rule}" + (f" ({req.value})" if req.value else ""),
    )
    db.add(playlist)
    for i, t in enumerate(tracks):
        db.add(PlaylistTrack(id=str(uuid.uuid4()), playlist_id=playlist.id, track_id=t.id, position=i))
    await db.commit()

    return {"id": playlist.id, "name": playlist.name, "track_count": len(tracks)}


class AIPlaylistRequest(BaseModel):
    prompt: str
    name: str | None = None
    limit: int = 30


@router.post("/ai-generate")
async def ai_generate_playlist(req: AIPlaylistRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Generate a playlist from a natural language prompt using AI."""
    from backend.services.ai.playlist_gen import generate_playlist
    from backend.services.user_data import caller_id
    # Steered by, sorted by and saved for whoever asked.
    return await generate_playlist(db, req.prompt, name=req.name, limit=req.limit,
                                   user_id=await caller_id(request, db))


@router.get("/{playlist_id}")
async def get_playlist(playlist_id: str, request: Request, db: AsyncSession = Depends(get_db)):
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
    me = await caller_user(request, db)
    if not p or not can_read_playlist(me, p):
        raise HTTPException(404, "Playlist not found")
    entries = sorted([e for e in p.entries if e.track], key=lambda e: e.position)
    owners = await _owners(db, [p.user_id])
    return {
        "id": p.id,
        "name": p.name,
        "comment": p.comment,
        **_access(p, me, owners),
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
async def update_playlist(playlist_id: str, req: PlaylistUpdate, request: Request, db: AsyncSession = Depends(get_db)):
    p = await _editable(db, request, playlist_id)

    if req.name is not None:
        p.name = req.name
    if req.comment is not None:
        p.comment = req.comment
    if req.is_public is not None:
        p.is_public = req.is_public
    if req.track_ids is not None:
        await db.execute(delete(PlaylistTrack).where(PlaylistTrack.playlist_id == playlist_id))
        for i, tid in enumerate(req.track_ids):
            db.add(PlaylistTrack(id=str(uuid.uuid4()), playlist_id=playlist_id, track_id=tid, position=i))
    p.updated_at = datetime.utcnow()
    await db.commit()
    return {"ok": True}


@router.delete("/{playlist_id}")
async def delete_playlist(playlist_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    if await db.get(Playlist, playlist_id) is None:
        return {"ok": True}  # already gone, as before
    await _editable(db, request, playlist_id)
    await db.execute(delete(Playlist).where(Playlist.id == playlist_id))
    await db.commit()
    return {"ok": True}
