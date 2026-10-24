"""Subsonic annotation endpoints: star, unstar, scrobble, setRating, getNowPlaying."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Request, Depends
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.models.favorite import Favorite
from backend.models.track import Track
from backend.services.user_data import caller_user, is_admin, record_play, record_skip
from backend.services.user_data import set_rating as store_rating
from backend.subsonic.personal import personal_view
from backend.subsonic.responses import subsonic_response, error_response, format_track

router = APIRouter()

# In-memory now-playing state: {username: {track, track_id, user_id, playerId, started_at}}
_now_playing: dict[str, dict] = {}

# Skip inference, keyed per (user id, client) so the phone and the watch don't
# overwrite each other: {key: {track_id, started_at, duration, submitted}}.
# Clients post a now-playing notice when a track starts and a submission once it
# passes 50%. A now-playing for a *different* track while the previous one was
# never submitted, and too little wall-clock time passed for it to have reached
# the halfway mark, means the listener skipped it. Paused-then-skipped tracks
# fail the time check and go uncounted, which errs on the side of not penalising.
_skip_watch: dict[tuple[str, str], dict] = {}


def _get_format(request: Request) -> str:
    return request.query_params.get("f", "json")


def _ids(request: Request, params: dict, name: str) -> list[str]:
    """Every value of a repeatable param (query string first, then a POSTed form)."""
    values = [v for v in request.query_params.getlist(name) if v]
    if not values and params.get(name):
        values = [params[name]]
    return values


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

    # Always the caller's stars (the owner for anonymous grace-mode calls), never `u=`.
    user = await caller_user(request, db)
    if not user:
        return error_response(0, "User not found", _get_format(request))

    # Star can receive id, albumId, or artistId (can be multiple)
    song_ids = _ids(request, params, "id")
    album_ids = _ids(request, params, "albumId")
    artist_ids = _ids(request, params, "artistId")

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

    user = await caller_user(request, db)
    if not user:
        return error_response(0, "User not found", _get_format(request))

    song_ids = _ids(request, params, "id")
    album_ids = _ids(request, params, "albumId")
    artist_ids = _ids(request, params, "artistId")

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
    if request.method == "POST":
        try:
            form = await request.form()
            params.update(form)
        except Exception:
            pass

    song_id = params.get("id")
    # submission=true (the default per Subsonic spec) means "completed play".
    # submission=false means "now-playing notification". Accept common truthy
    # spellings defensively — some clients send "1" / "True".
    submission_raw = str(params.get("submission", "true")).strip().lower()
    is_submission = submission_raw in ("true", "1", "yes")

    # Optional `time` parameter — ms since epoch, when the play occurred.
    # Subsonic clients use this to backfill scrobbles that were queued offline.
    time_param = params.get("time")
    played_at = datetime.utcnow()
    if time_param:
        try:
            played_at = datetime.utcfromtimestamp(int(time_param) / 1000)
        except (ValueError, TypeError):
            played_at = datetime.utcnow()

    if not song_id:
        return error_response(10, "Missing id parameter", _get_format(request))

    # Relations loaded up front: getNowPlaying formats this instance after the session ends.
    result = await db.execute(
        select(Track).options(
            selectinload(Track.artist), selectinload(Track.album), selectinload(Track.analysis)
        ).where(Track.id == song_id)
    )
    track = result.scalar_one_or_none()
    if not track:
        # Track unknown — return success (clients shouldn't error out the queue)
        return subsonic_response({}, _get_format(request))

    # The caller's plays and skips (the owner for anonymous grace-mode calls).
    user = await caller_user(request, db)
    user_id = user.id if user else None
    username = user.username if user else params.get("u", "admin")
    client = (params.get("c") or "").strip()
    watch_key = (user_id or username, client)

    if is_submission:
        # Global totals + the caller's stats + history. A completed listen pays one skip
        # back, so a track isn't buried for good (record_play does that for both).
        watched = _skip_watch.get(watch_key)
        if watched and watched["track_id"] == song_id:
            watched["submitted"] = True
        # Record the originating client (c= param: ZonikApp/ZonikWear/DSub/…) as the
        # source so "Recently Played" can show which device the play came from.
        await record_play(db, user_id, track, played_at, source=client or "subsonic")
        await db.commit()
    else:
        # Now-playing notification
        now = datetime.utcnow()
        prev = _skip_watch.get(watch_key)
        if prev and prev["track_id"] != song_id and not prev["submitted"] and prev["duration"]:
            elapsed = (now - prev["started_at"]).total_seconds()
            if elapsed < prev["duration"] / 2:
                skipped = await db.get(Track, prev["track_id"])
                if skipped:
                    await record_skip(db, user_id, skipped, now)
                    await db.commit()
        if not prev or prev["track_id"] != song_id:
            _skip_watch[watch_key] = {
                "track_id": song_id,
                "started_at": now,
                "duration": track.duration_seconds or 0,
                "submitted": False,
            }
        _now_playing[username] = {
            "track": track,
            "track_id": song_id,
            "user_id": user_id,
            "playerId": params.get("c", ""),
            "started_at": datetime.utcnow(),
        }

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

    # The caller's rating; an admin's also sets the library-wide tracks.rating.
    await store_rating(db, await caller_user(request, db), track, rating)
    await db.commit()
    return subsonic_response({}, _get_format(request))


@router.get("/getNowPlaying")
@router.get("/getNowPlaying.view")
async def get_now_playing(request: Request, db: AsyncSession = Depends(get_db)):
    """Return tracks currently being played (reported via scrobble submission=false).
    Admins see everyone's; a regular user sees only their own."""
    me = await caller_user(request, db)
    everyone = me is None or is_admin(me)
    live = []
    cutoff = datetime.utcnow() - timedelta(minutes=10)
    for username, info in list(_now_playing.items()):
        if info["started_at"] < cutoff:
            _now_playing.pop(username, None)
            continue
        if not everyone and info.get("user_id") != me.id and username != me.username:
            continue
        live.append((username, info))
    # The caller's own counts/stars on every entry, loaded once.
    personal = await personal_view(request, db, tracks=[info["track"] for _, info in live],
                                   user_id=me.id if me else None)
    entries = []
    for username, info in live:
        track = info["track"]
        entry = format_track(track, personal=personal)
        entry["username"] = username
        entry["minutesAgo"] = int((datetime.utcnow() - info["started_at"]).total_seconds() / 60)
        entry["playerId"] = info.get("playerId", "")
        entries.append(entry)
    return subsonic_response({"nowPlaying": {"entry": entries}}, _get_format(request))
