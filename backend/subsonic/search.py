"""Subsonic search3 endpoint with empty query fast-sync support for Subsonic clients."""
from __future__ import annotations

from fastapi import APIRouter, Request, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.models.track import Track
from backend.models.album import Album
from backend.models.artist import Artist
from backend.subsonic.personal import personal_view
from backend.subsonic.responses import subsonic_response, format_track, format_album, format_artist

router = APIRouter()


def _get_format(request: Request) -> str:
    return request.query_params.get("f", "json")


@router.get("/search3")
@router.get("/search3.view")
async def search3(request: Request, db: AsyncSession = Depends(get_db)):
    query = request.query_params.get("query", "")
    artist_count = min(int(request.query_params.get("artistCount", 20)), 500)
    artist_offset = int(request.query_params.get("artistOffset", 0))
    album_count = min(int(request.query_params.get("albumCount", 20)), 500)
    album_offset = int(request.query_params.get("albumOffset", 0))
    song_count = min(int(request.query_params.get("songCount", 20)), 500)
    song_offset = int(request.query_params.get("songOffset", 0))

    if query == "" or query == '""':
        # Empty query = fast sync - return all items paginated
        # This is critical for Subsonic client fast sync support
        artists_result = await db.execute(
            select(Artist).order_by(Artist.name).offset(artist_offset).limit(artist_count)
        )
        albums_result = await db.execute(
            select(Album).options(selectinload(Album.artist))
            .order_by(Album.title).offset(album_offset).limit(album_count)
        )
        songs_result = await db.execute(
            select(Track).options(
                selectinload(Track.artist), selectinload(Track.album), selectinload(Track.analysis)
            ).order_by(Track.title).offset(song_offset).limit(song_count)
        )
    else:
        # Normal search
        search_term = f"%{query}%"

        artists_result = await db.execute(
            select(Artist).where(Artist.name.ilike(search_term))
            .order_by(Artist.name).offset(artist_offset).limit(artist_count)
        )
        albums_result = await db.execute(
            select(Album).options(selectinload(Album.artist))
            .where(Album.title.ilike(search_term))
            .order_by(Album.title).offset(album_offset).limit(album_count)
        )
        songs_result = await db.execute(
            select(Track).options(
                selectinload(Track.artist), selectinload(Track.album), selectinload(Track.analysis)
            ).where(
                Track.title.ilike(search_term) | Track.file_path.ilike(search_term)
            ).order_by(Track.title).offset(song_offset).limit(song_count)
        )

    artist_rows = artists_result.scalars().all()
    album_rows = albums_result.scalars().all()
    song_rows = songs_result.scalars().all()
    personal = await personal_view(request, db, tracks=song_rows, albums=album_rows, artists=artist_rows)
    artists = [format_artist(a, personal=personal) for a in artist_rows]
    albums = [format_album(a, personal=personal) for a in album_rows]
    songs = [format_track(t, personal=personal) for t in song_rows]

    return subsonic_response({
        "searchResult3": {
            "artist": artists,
            "album": albums,
            "song": songs,
        }
    }, _get_format(request))
