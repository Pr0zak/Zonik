"""Subsonic list endpoints: getAlbumList2, getRandomSongs, getStarred2, etc."""
from __future__ import annotations

import random as _random

from fastapi import APIRouter, Request, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.config import get_settings
from backend.models.track import Track
from backend.models.album import Album
from backend.models.artist import Artist
from backend.models.favorite import Favorite
from backend.subsonic.responses import subsonic_response, error_response, format_track, format_album, format_artist

router = APIRouter()


def _get_format(request: Request) -> str:
    return request.query_params.get("f", "json")


@router.get("/getAlbumList2")
@router.get("/getAlbumList2.view")
async def get_album_list2(request: Request, db: AsyncSession = Depends(get_db)):
    list_type = request.query_params.get("type", "alphabeticalByName")
    size = max(1, min(int(request.query_params.get("size", 10)), 500))
    offset = max(0, int(request.query_params.get("offset", 0)))

    query = select(Album).options(selectinload(Album.artist))

    if list_type == "alphabeticalByName":
        query = query.order_by(Album.title)
    elif list_type == "alphabeticalByArtist":
        query = query.join(Artist, Album.artist_id == Artist.id, isouter=True).order_by(Artist.name)
    elif list_type == "newest":
        query = query.order_by(Album.created_at.desc())
    elif list_type == "recent":
        # "recent" = recently played (per Subsonic spec). Order by max(last_played_at)
        # of any track in the album. Albums with no plays fall through to created_at.
        last_played_subq = (
            select(
                Track.album_id.label("album_id"),
                func.max(Track.last_played_at).label("last_played"),
            )
            .where(Track.album_id.isnot(None))
            .group_by(Track.album_id)
            .subquery()
        )
        query = (
            query.join(last_played_subq, Album.id == last_played_subq.c.album_id)
            .where(last_played_subq.c.last_played.isnot(None))
            .order_by(last_played_subq.c.last_played.desc())
        )
    elif list_type == "frequent":
        # "frequent" = most played. Aggregate play_count across each album's tracks
        # so albums with many high-play tracks float to the top. Albums with zero
        # total plays are excluded (spec: "albums sorted by play count").
        play_count_subq = (
            select(
                Track.album_id.label("album_id"),
                func.coalesce(func.sum(Track.play_count), 0).label("total_plays"),
            )
            .where(Track.album_id.isnot(None))
            .group_by(Track.album_id)
            .subquery()
        )
        query = (
            query.join(play_count_subq, Album.id == play_count_subq.c.album_id)
            .where(play_count_subq.c.total_plays > 0)
            .order_by(play_count_subq.c.total_plays.desc())
        )
    elif list_type == "random":
        query = query.order_by(func.random())
    elif list_type == "byYear":
        from_year = int(request.query_params.get("fromYear", 0))
        to_year = int(request.query_params.get("toYear", 9999))
        query = query.where(Album.year >= from_year, Album.year <= to_year).order_by(Album.year)
    elif list_type == "byGenre":
        genre = request.query_params.get("genre")
        if genre:
            query = query.where(Album.genre == genre)
    elif list_type == "starred":
        query = query.join(Favorite, Favorite.album_id == Album.id).order_by(Favorite.starred_at.desc())
    else:
        query = query.order_by(Album.title)

    query = query.offset(offset).limit(size)
    result = await db.execute(query)
    albums = result.scalars().all()

    return subsonic_response({
        "albumList2": {
            "album": [format_album(a) for a in albums]
        }
    }, _get_format(request))


def _artist_key(t: Track) -> str:
    return t.artist_id or f"track:{t.id}"


def _album_key(t: Track) -> str:
    return t.album_id or f"track:{t.id}"


def _cap_artists_albums(candidates: list, size: int) -> list:
    """Take `size` tracks from `candidates` (already in random order), allowing at
    most one track per album and a couple per artist, so one prolific artist can't
    fill the mix. If the library is too small to honour the caps, the remainder is
    filled from what was passed over rather than returning a short list."""
    per_artist = max(2, -(-size // 50))
    artist_n: dict[str, int] = {}
    albums: set[str] = set()
    picked: list = []
    passed: list = []
    for t in candidates:
        if len(picked) >= size:
            break
        a, al = _artist_key(t), _album_key(t)
        if artist_n.get(a, 0) >= per_artist or al in albums:
            passed.append(t)
            continue
        artist_n[a] = artist_n.get(a, 0) + 1
        albums.add(al)
        picked.append(t)
    if len(picked) < size:
        picked.extend(passed[: size - len(picked)])
    return picked


def _space_artists(tracks: list, gap: int = 5) -> list:
    """Shuffle, then reorder so the same artist doesn't come back within `gap`
    tracks. Greedy: at each slot take the first remaining track whose artist isn't
    in the recent window; if every remaining track clashes, take the first one."""
    remaining = list(tracks)
    _random.shuffle(remaining)
    gap = min(gap, max(0, len({_artist_key(t) for t in remaining}) - 1))
    out: list = []
    while remaining:
        recent = {_artist_key(t) for t in out[-gap:]} if gap else set()
        idx = next((i for i, t in enumerate(remaining) if _artist_key(t) not in recent), 0)
        out.append(remaining.pop(idx))
    return out


@router.get("/getRandomSongs")
@router.get("/getRandomSongs.view")
async def get_random_songs(request: Request, db: AsyncSession = Depends(get_db)):
    size = min(int(request.query_params.get("size", 10)), 500)
    genre = request.query_params.get("genre")
    from_year = request.query_params.get("fromYear")
    to_year = request.query_params.get("toYear")

    query = select(Track).options(
        selectinload(Track.artist), selectinload(Track.album), selectinload(Track.analysis)
    )
    if genre:
        query = query.where(Track.genre == genre)
    if from_year:
        query = query.where(Track.year >= int(from_year))
    if to_year:
        query = query.where(Track.year <= int(to_year))

    cfg = get_settings().subsonic

    # Uniform random order, except that tracks you keep skipping are pushed back:
    # each skip multiplies the sort key, so a track skipped once is about half as
    # likely to make the cut, three times about a quarter. Completed plays pay the
    # count back down (see scrobble), so a track is not buried for good.
    def _random_order(q):
        return q.order_by((func.abs(func.random()) * (1.0 + func.coalesce(Track.skip_count, 0))).asc())

    # New-arrivals quota: pull a guaranteed slice of the mix from tracks ADDED in the
    # last N days (by created_at), so fresh downloads always surface.
    new_tracks: list = []
    new_pct = cfg.shuffle_new_arrival_percent or 0
    if new_pct > 0:
        new_count = min(size, round(size * new_pct / 100.0))
        if new_count > 0:
            ndays = max(1, cfg.shuffle_new_arrival_days or 1)
            nq = _random_order(
                query.where(Track.created_at >= func.datetime("now", f"-{ndays} days"))
            ).limit(new_count)
            new_tracks = list((await db.execute(nq)).scalars().all())

    # Over-fetch so the artist/album caps below have something to choose from.
    pool_q = query
    if new_tracks:
        pool_q = pool_q.where(Track.id.notin_([t.id for t in new_tracks]))
    pool_q = _random_order(pool_q).limit(min(size * 4, 2000))
    pool = list((await db.execute(pool_q)).scalars().all())

    tracks = _space_artists(_cap_artists_albums(new_tracks + pool, size))

    return subsonic_response({
        "randomSongs": {
            "song": [format_track(t) for t in tracks]
        }
    }, _get_format(request))


@router.get("/getSongsByGenre")
@router.get("/getSongsByGenre.view")
async def get_songs_by_genre(request: Request, db: AsyncSession = Depends(get_db)):
    genre = request.query_params.get("genre")
    count = min(int(request.query_params.get("count", 10)), 500)
    offset = int(request.query_params.get("offset", 0))

    if not genre:
        return error_response(10, "Missing genre parameter", _get_format(request))

    result = await db.execute(
        select(Track).options(
            selectinload(Track.artist), selectinload(Track.album), selectinload(Track.analysis)
        ).where(Track.genre == genre).offset(offset).limit(count)
    )
    tracks = result.scalars().all()

    return subsonic_response({
        "songsByGenre": {
            "song": [format_track(t) for t in tracks]
        }
    }, _get_format(request))


@router.get("/getStarred2")
@router.get("/getStarred2.view")
async def get_starred2(request: Request, db: AsyncSession = Depends(get_db)):
    # Starred artists
    artist_result = await db.execute(
        select(Artist).join(Favorite, Favorite.artist_id == Artist.id)
    )
    starred_artists = [format_artist(a, starred=True) for a in artist_result.scalars().all()]

    # Starred albums
    album_result = await db.execute(
        select(Album).options(selectinload(Album.artist))
        .join(Favorite, Favorite.album_id == Album.id)
    )
    starred_albums = [format_album(a, starred=True) for a in album_result.scalars().all()]

    # Starred tracks
    track_result = await db.execute(
        select(Track).options(
            selectinload(Track.artist), selectinload(Track.album), selectinload(Track.analysis)
        ).join(Favorite, Favorite.track_id == Track.id)
    )
    starred_songs = [format_track(t, starred=True) for t in track_result.scalars().all()]

    return subsonic_response({
        "starred2": {
            "artist": starred_artists,
            "album": starred_albums,
            "song": starred_songs,
        }
    }, _get_format(request))
