"""Per-user listening data (multi-user P2): who is asking, and their plays, skips and ratings.

The rule: the global columns on `tracks` (play_count, skip_count, last_played_at, rating)
remain "anyone" totals that library maintenance reads (graph, soundscape, cleanup, tidy,
download ledger). Anything a person sees as *theirs* reads `user_track_stats` /
`play_history.user_id` through the helpers here. Write paths go through record_play /
record_skip / set_rating so both stay in step.

`tracks.rating` doubles as the library's deletion flag (rating 1 = "flagged for deletion"
from the phone app), so only admins' ratings are mirrored onto it; a regular user's rating
stays personal.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import HTTPConnection

from backend.models.play_history import PlayHistory
from backend.models.track import Track
from backend.models.user import User
from backend.models.user_track_stats import UserTrackStats


async def owner_id(db: AsyncSession) -> str | None:
    """The owner: first enabled admin by created_at. Grace-mode anonymous callers, the
    scheduler's single-user fallbacks and pre-multi-user data all map here."""
    return (await db.execute(
        select(User.id)
        .where(User.role == "admin", User.disabled.is_(False))
        .order_by(User.created_at)
        .limit(1)
    )).scalar_one_or_none()


def caller(conn: HTTPConnection) -> User | None:
    """The resolved caller from the auth gate (P1), or None (anonymous /rest in grace mode)."""
    return getattr(conn.state, "user", None)


async def caller_id(conn: HTTPConnection, db: AsyncSession) -> str | None:
    """The caller's user id; falls back to the owner for anonymous grace-mode requests so
    single-user behaviour is unchanged. None only on a server with no admin at all."""
    user = caller(conn)
    if user is not None:
        return user.id
    return await owner_id(db)


async def _stats_row(db: AsyncSession, user_id: str, track_id: str) -> UserTrackStats:
    row = await db.get(UserTrackStats, (user_id, track_id))
    if row is None:
        row = UserTrackStats(user_id=user_id, track_id=track_id, play_count=0, skip_count=0)
        db.add(row)
    return row


async def record_play(db: AsyncSession, user_id: str | None, track: Track,
                      played_at: datetime | None = None, source: str = "web") -> None:
    """A completed play: global totals, the user's stats and a play_history row. A play
    forgives one earlier skip (same rule as before multi-user). Caller commits."""
    played_at = played_at or datetime.utcnow()
    track.play_count = (track.play_count or 0) + 1
    track.last_played_at = played_at
    if track.skip_count:
        track.skip_count -= 1
    if user_id:
        row = await _stats_row(db, user_id, track.id)
        row.play_count = (row.play_count or 0) + 1
        row.last_played_at = played_at
        if row.skip_count:
            row.skip_count -= 1
    db.add(PlayHistory(track_id=track.id, played_at=played_at, source=source, user_id=user_id))


async def record_skip(db: AsyncSession, user_id: str | None, track: Track,
                      at: datetime | None = None) -> None:
    at = at or datetime.utcnow()
    track.skip_count = (track.skip_count or 0) + 1
    track.last_skipped_at = at
    if user_id:
        row = await _stats_row(db, user_id, track.id)
        row.skip_count = (row.skip_count or 0) + 1
        row.last_skipped_at = at


async def set_rating(db: AsyncSession, user: User | None, track: Track, rating: int) -> int | None:
    """0 clears. Returns the stored value. Admin ratings also update tracks.rating (the
    library-wide value that drives the deletion flag); a regular user's stay personal."""
    value = rating if rating > 0 else None
    if user is not None:
        row = await _stats_row(db, user.id, track.id)
        row.rating = value
    if user is None or user.role == "admin":
        track.rating = value
    return value


async def stats_for(db: AsyncSession, user_id: str | None, track_ids) -> dict[str, UserTrackStats]:
    """{track_id: stats} for the given tracks (missing = never played/rated by this user)."""
    ids = [t for t in dict.fromkeys(track_ids) if t]
    if not user_id or not ids:
        return {}
    out: dict[str, UserTrackStats] = {}
    for i in range(0, len(ids), 500):  # stay under SQLite's variable limit
        rows = (await db.execute(
            select(UserTrackStats).where(
                UserTrackStats.user_id == user_id, UserTrackStats.track_id.in_(ids[i:i + 500])
            )
        )).scalars().all()
        out.update({r.track_id: r for r in rows})
    return out


async def active_user_ids(db: AsyncSession, min_plays: int = 1) -> list[str]:
    """Enabled users with at least min_plays plays — the scheduler computes per-user taste
    and recommendations only for these."""
    from sqlalchemy import func
    rows = (await db.execute(
        select(PlayHistory.user_id)
        .join(User, User.id == PlayHistory.user_id)
        .where(User.disabled.is_(False))
        .group_by(PlayHistory.user_id)
        .having(func.count() >= min_plays)
    )).scalars().all()
    return [r for r in rows if r]


async def caller_user(conn: HTTPConnection, db: AsyncSession) -> User | None:
    """The caller as a User; the owner for anonymous grace-mode requests (like caller_id).
    None only on a server with no admin at all."""
    user = caller(conn)
    if user is not None:
        return user
    oid = await owner_id(db)
    return await db.get(User, oid) if oid else None


def is_admin(user: User | None) -> bool:
    return user is not None and user.role == "admin"


# --- playlists: own + public; owners mutate their own, admins any ----------------------
# user None means a server with no users at all (nothing to keep apart), so it may do
# anything. Playlists without an owner (pre-migration) read as public, admin-editable.

def can_read_playlist(user: User | None, playlist) -> bool:
    if user is None or playlist.is_public or playlist.user_id is None:
        return True
    return playlist.user_id == user.id or is_admin(user)


def can_edit_playlist(user: User | None, playlist) -> bool:
    if user is None:
        return True
    return playlist.user_id == user.id or is_admin(user)


def visible_playlists_clause(user: User | None):
    """WHERE clause for playlist lists: the caller's own plus everyone's public ones."""
    from sqlalchemy import or_, true
    from backend.models.playlist import Playlist
    if user is None:
        return true()
    return or_(Playlist.user_id == user.id, Playlist.is_public.is_(True), Playlist.user_id.is_(None))
