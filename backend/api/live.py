"""Live activity endpoints — connected clients, now-playing, recent plays."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.api.websocket import get_ws_clients
from backend.database import get_db
from backend.models.album import Album
from backend.models.artist import Artist
from backend.models.favorite import Favorite
from backend.models.play_history import PlayHistory
from backend.models.track import Track
from backend.models.user import User
from backend.subsonic.activity import get_active_clients
from backend.subsonic.annotation import _now_playing

router = APIRouter()


async def _admin_user_id(db: AsyncSession) -> str | None:
    """Resolve the admin user — single-user install assumption."""
    result = await db.execute(
        select(User).where(User.is_admin == True).order_by(User.created_at).limit(1)
    )
    user = result.scalar_one_or_none()
    if user:
        return user.id
    # Fallback to first user
    result = await db.execute(select(User).order_by(User.created_at).limit(1))
    user = result.scalar_one_or_none()
    return user.id if user else None


async def _favorited_track_ids(db: AsyncSession, user_id: str | None) -> set[str]:
    if not user_id:
        return set()
    result = await db.execute(
        select(Favorite.track_id)
        .where(Favorite.user_id == user_id, Favorite.track_id.is_not(None))
    )
    return {row[0] for row in result.all() if row[0]}


def _cover_id(track: Track) -> str | None:
    if track.cover_art_path:
        return track.id
    if track.album and track.album.cover_art_path:
        return track.id
    return track.album_id or None


@router.get("/clients")
async def list_clients() -> dict:
    """Connected WS clients + recently-active Subsonic API clients."""
    return {
        "ws_clients": get_ws_clients(),
        "api_clients": [
            {
                "username": e["username"],
                "client_name": e["client_name"],
                "user_agent": e.get("user_agent"),
                "ip": e.get("ip"),
                "last_seen": e["last_seen"].isoformat() if e.get("last_seen") else None,
                "first_seen": e["first_seen"].isoformat() if e.get("first_seen") else None,
                "endpoint_count": e.get("endpoint_count", 0),
            }
            for e in get_active_clients()
        ],
    }


@router.get("/now-playing")
async def now_playing(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Currently-playing tracks reported via Subsonic scrobble submission=false."""
    cutoff = datetime.utcnow() - timedelta(minutes=10)
    # Snapshot keys so we can mutate during iteration.
    items = []
    for username, info in list(_now_playing.items()):
        started = info.get("started_at")
        if not started or started < cutoff:
            _now_playing.pop(username, None)
            continue
        track_id = info.get("track_id") or (info["track"].id if info.get("track") else None)
        if not track_id:
            continue
        items.append((username, track_id, info))

    if not items:
        return []

    track_ids = [t[1] for t in items]
    result = await db.execute(
        select(Track)
        .options(selectinload(Track.artist), selectinload(Track.album))
        .where(Track.id.in_(track_ids))
    )
    tracks = {t.id: t for t in result.scalars().all()}

    user_id = await _admin_user_id(db)
    starred = await _favorited_track_ids(db, user_id)

    out: list[dict] = []
    for username, track_id, info in items:
        track = tracks.get(track_id)
        if not track:
            continue
        out.append({
            "username": username,
            "client": info.get("playerId") or "",
            "started_at": info["started_at"].isoformat(),
            "track_id": track.id,
            "title": track.title,
            "artist": track.artist.name if track.artist else None,
            "album": track.album.title if track.album else None,
            "cover_art": _cover_id(track),
            "duration": track.duration_seconds,
            "starred": track.id in starred,
        })
    out.sort(key=lambda r: r["started_at"], reverse=True)
    return out


@router.get("/history")
async def history(limit: int = 50, db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Last N plays from play_history with track/artist/album info + star flag."""
    limit = max(1, min(limit, 200))
    result = await db.execute(
        select(PlayHistory, Track, Artist, Album)
        .join(Track, PlayHistory.track_id == Track.id)
        .outerjoin(Artist, Track.artist_id == Artist.id)
        .outerjoin(Album, Track.album_id == Album.id)
        .order_by(PlayHistory.played_at.desc())
        .limit(limit)
    )
    rows = result.all()

    user_id = await _admin_user_id(db)
    starred = await _favorited_track_ids(db, user_id)

    out: list[dict] = []
    for ph, track, artist, album in rows:
        cover = track.id if (track.cover_art_path or (album and album.cover_art_path)) else None
        out.append({
            "id": ph.id,
            "track_id": ph.track_id,
            "played_at": ph.played_at.isoformat() if ph.played_at else None,
            "source": ph.source,
            "title": track.title,
            "artist": artist.name if artist else None,
            "album": album.title if album else None,
            "cover_art": cover,
            "duration": track.duration_seconds,
            "starred": track.id in starred,
        })
    return out
