"""Subsonic list endpoints: getAlbumList2, getRandomSongs, getStarred2, etc."""
from __future__ import annotations

import random

from fastapi import APIRouter, Request, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db
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
    size = min(int(request.query_params.get("size", 10)), 500)
    offset = int(request.query_params.get("offset", 0))

    query = select(Album).options(selectinload(Album.artist))

    if list_type == "alphabeticalByName":
        query = query.order_by(Album.title)
    elif list_type == "alphabeticalByArtist":
        query = query.join(Artist, Album.artist_id == Artist.id, isouter=True).order_by(Artist.name)
    elif list_type == "newest":
        query = query.order_by(Album.created_at.desc())
    elif list_type == "recent":
        query = query.order_by(Album.created_at.desc())
    elif list_type == "frequent":
        query = query.order_by(Album.created_at.desc())  # TODO: track play counts
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

    query = query.order_by(func.random()).limit(size)
    result = await db.execute(query)
    tracks = result.scalars().all()

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
