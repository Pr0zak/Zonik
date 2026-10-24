"""Live activity endpoints — connected clients, now-playing, recent plays."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
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
from backend.models.user_track_stats import UserTrackStats
from backend.subsonic.activity import get_active_clients
from backend.subsonic.annotation import _now_playing
from backend.services.user_data import caller, caller_id, stats_for
from backend.services.user_scope import caller_is_admin, usernames

router = APIRouter()


def _session_is_users(key: str, info: dict, user: User | None) -> bool:
    """Whether a now-playing session belongs to `user`: by the resolved user id when the
    scrobble recorded one, else by the session's username."""
    if user is None:
        return False
    if info.get("user_id"):
        return info["user_id"] == user.id
    return (info.get("username") or key) == user.username


def _visible_sessions(request: Request, sessions: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
    """Admins see every listener's sessions; a regular user only their own."""
    if caller_is_admin(request):
        return sessions
    user = caller(request)
    return [(k, info) for k, info in sessions if _session_is_users(k, info, user)]


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
async def list_clients(request: Request) -> dict:
    """Connected WS clients + recently-active Subsonic API clients. Regular users see only
    their own API clients and no WS client list."""
    admin = caller_is_admin(request)
    me = caller(request)
    return {
        "ws_clients": get_ws_clients() if admin else [],
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
            if admin or (me is not None and e.get("username") == me.username)
        ],
    }


@router.get("/now-playing")
async def now_playing(request: Request, db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Currently-playing tracks reported via Subsonic scrobble submission=false. Admins
    see every listener (each item carries `username`); a regular user sees only their own.
    `starred` is the caller's own star."""
    cutoff = datetime.utcnow() - timedelta(minutes=10)
    # Snapshot keys so we can mutate during iteration.
    live = []
    for key, info in list(_now_playing.items()):
        started = info.get("started_at")
        if not started or started < cutoff:
            _now_playing.pop(key, None)
            continue
        live.append((key, info))
    items = []
    for key, info in _visible_sessions(request, live):
        track_id = info.get("track_id") or (info["track"].id if info.get("track") else None)
        if not track_id:
            continue
        items.append((info.get("username") or key, track_id, info))

    if not items:
        return []

    track_ids = [t[1] for t in items]
    result = await db.execute(
        select(Track)
        .options(selectinload(Track.artist), selectinload(Track.album))
        .where(Track.id.in_(track_ids))
    )
    tracks = {t.id: t for t in result.scalars().all()}

    user_id = await caller_id(request, db)
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
async def history(request: Request, limit: int = 50, all_users: bool = False,
                  db: AsyncSession = Depends(get_db)) -> list[dict]:
    """The caller's last N plays from play_history with track/artist/album info + star flag
    (the caller's star). all_users=true (admins only) lists everyone's plays; each item
    carries the listener's `username` either way."""
    limit = max(1, min(limit, 200))
    user_id = await caller_id(request, db)
    query = (
        select(PlayHistory, Track, Artist, Album)
        .join(Track, PlayHistory.track_id == Track.id)
        .outerjoin(Artist, Track.artist_id == Artist.id)
        .outerjoin(Album, Track.album_id == Album.id)
    )
    if not (all_users and caller_is_admin(request)):
        query = query.where(PlayHistory.user_id == user_id)
    result = await db.execute(query.order_by(PlayHistory.played_at.desc()).limit(limit))
    rows = result.all()
    names = await usernames(db)

    starred = await _favorited_track_ids(db, user_id)

    out: list[dict] = []
    for ph, track, artist, album in rows:
        cover = track.id if (track.cover_art_path or (album and album.cover_art_path)) else None
        out.append({
            "id": ph.id,
            "track_id": ph.track_id,
            "played_at": ph.played_at.isoformat() if ph.played_at else None,
            "source": ph.source,
            "username": names.get(ph.user_id),
            "title": track.title,
            "artist": artist.name if artist else None,
            "album": album.title if album else None,
            "cover_art": cover,
            "duration": track.duration_seconds,
            "starred": track.id in starred,
        })
    return out


@router.get("/skips")
async def skips(request: Request, sort: str = "recent", limit: int = 50,
                db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Tracks the caller skipped (inferred from scrobbles), newest skip first or
    most-skipped first. skip_count can be back at 0 once full listens paid it off.
    play_count / skip_count / rating / last_* are the caller's own."""
    limit = max(1, min(limit, 500))
    user_id = await caller_id(request, db)
    uts = UserTrackStats
    query = (
        select(Track, Artist, Album, uts)
        .join(uts, (uts.track_id == Track.id) & (uts.user_id == user_id))
        .outerjoin(Artist, Track.artist_id == Artist.id)
        .outerjoin(Album, Track.album_id == Album.id)
        .where(uts.last_skipped_at.is_not(None))
    )
    if sort == "most":
        query = query.where(uts.skip_count > 0).order_by(uts.skip_count.desc(), uts.last_skipped_at.desc())
    else:
        query = query.order_by(uts.last_skipped_at.desc())
    rows = (await db.execute(query.limit(limit))).all()

    starred = await _favorited_track_ids(db, user_id)

    return [
        {
            "track_id": track.id,
            "title": track.title,
            "artist": artist.name if artist else None,
            "album": album.title if album else None,
            "cover_art": track.id if (track.cover_art_path or (album and album.cover_art_path)) else None,
            "duration": track.duration_seconds,
            "skip_count": st.skip_count or 0,
            "play_count": st.play_count or 0,
            "last_skipped_at": st.last_skipped_at.isoformat() if st.last_skipped_at else None,
            "last_played_at": st.last_played_at.isoformat() if st.last_played_at else None,
            "genre": track.genre,
            "year": track.year,
            "format": track.format,
            "bitrate": track.bitrate,
            "rating": st.rating,
            "starred": track.id in starred,
        }
        for track, artist, album, st in rows
    ]


@router.post("/skips/{track_id}/reset")
async def reset_skips(track_id: str, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """Forget the caller's skips of a track, e.g. one counted when a new queue cut it off.
    The global counter (library maintenance) loses the same number of skips."""
    track = await db.get(Track, track_id)
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")
    user_id = await caller_id(request, db)
    st = (await stats_for(db, user_id, [track_id])).get(track_id)
    if st is not None:
        track.skip_count = max(0, (track.skip_count or 0) - (st.skip_count or 0))
        if not track.skip_count:
            track.last_skipped_at = None
        st.skip_count = 0
        st.last_skipped_at = None
    elif user_id is None:
        track.skip_count = 0
        track.last_skipped_at = None
    await db.commit()
    return {"ok": True}


@router.get("/skips/summary")
async def skips_summary(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """The caller's headline skip numbers for the Stats page, plus their most-skipped artists."""
    user_id = await caller_id(request, db)
    uts = UserTrackStats
    tracks_with_skips, active_skips = (await db.execute(
        select(func.count(uts.track_id), func.coalesce(func.sum(uts.skip_count), 0))
        .where(uts.user_id == user_id, uts.skip_count > 0)
    )).one()
    week_ago = datetime.utcnow() - timedelta(days=7)
    skipped_7d = (await db.execute(
        select(func.count(uts.track_id)).where(uts.user_id == user_id, uts.last_skipped_at >= week_ago)
    )).scalar_one()
    top_artists = (await db.execute(
        select(Artist.name, func.sum(uts.skip_count).label("skips"), func.count(uts.track_id).label("tracks"))
        .join(Track, Track.id == uts.track_id)
        .join(Artist, Track.artist_id == Artist.id)
        .where(uts.user_id == user_id, uts.skip_count > 0)
        .group_by(Artist.id)
        .order_by(func.sum(uts.skip_count).desc())
        .limit(10)
    )).all()
    return {
        "tracks_with_skips": tracks_with_skips,
        "active_skips": int(active_skips),
        "skipped_7d": skipped_7d,
        "top_artists": [{"name": n, "skips": int(sk), "tracks": t} for n, sk, t in top_artists],
    }
