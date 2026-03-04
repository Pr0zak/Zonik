"""Subsonic browsing endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Request, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.models.artist import Artist
from backend.models.album import Album
from backend.models.track import Track
from backend.subsonic.responses import subsonic_response, error_response, format_artist, format_album, format_track

router = APIRouter()


def _get_format(request: Request) -> str:
    return request.query_params.get("f", "json")


@router.get("/getMusicFolders")
@router.get("/getMusicFolders.view")
async def get_music_folders(request: Request):
    return subsonic_response({
        "musicFolders": {
            "musicFolder": [{"id": "1", "name": "Music"}]
        }
    }, _get_format(request))


@router.get("/getIndexes")
@router.get("/getIndexes.view")
async def get_indexes(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Artist).order_by(Artist.name))
    artists = result.scalars().all()

    # Group by first letter
    index_map: dict[str, list] = {}
    for artist in artists:
        letter = artist.name[0].upper() if artist.name else "#"
        if not letter.isalpha():
            letter = "#"
        index_map.setdefault(letter, []).append({"id": artist.id, "name": artist.name})

    indexes = [{"name": letter, "artist": arts} for letter, arts in sorted(index_map.items())]

    return subsonic_response({
        "indexes": {
            "lastModified": "0",
            "ignoredArticles": "The El La Los Las Le Les",
            "index": indexes,
        }
    }, _get_format(request))


@router.get("/getMusicDirectory")
@router.get("/getMusicDirectory.view")
async def get_music_directory(request: Request, db: AsyncSession = Depends(get_db)):
    dir_id = request.query_params.get("id")
    if not dir_id:
        return error_response(10, "Missing id parameter", _get_format(request))

    # Check if it's an artist
    result = await db.execute(select(Artist).where(Artist.id == dir_id))
    artist = result.scalar_one_or_none()
    if artist:
        albums = (await db.execute(select(Album).where(Album.artist_id == artist.id))).scalars().all()
        children = [
            {"id": a.id, "parent": artist.id, "title": a.title, "isDir": "true",
             "artist": artist.name, "coverArt": a.cover_art_path, "year": a.year}
            for a in albums
        ]
        # Also include tracks without album
        tracks = (await db.execute(
            select(Track).options(selectinload(Track.artist), selectinload(Track.album), selectinload(Track.analysis))
            .where(Track.artist_id == artist.id, Track.album_id.is_(None))
        )).scalars().all()
        children.extend([format_track(t) for t in tracks])

        return subsonic_response({
            "directory": {
                "id": artist.id,
                "name": artist.name,
                "child": children,
            }
        }, _get_format(request))

    # Check if it's an album
    result = await db.execute(
        select(Album).options(selectinload(Album.artist)).where(Album.id == dir_id)
    )
    album = result.scalar_one_or_none()
    if album:
        tracks = (await db.execute(
            select(Track).options(selectinload(Track.artist), selectinload(Track.album), selectinload(Track.analysis))
            .where(Track.album_id == album.id)
            .order_by(Track.disc_number, Track.track_number)
        )).scalars().all()

        return subsonic_response({
            "directory": {
                "id": album.id,
                "parent": album.artist_id,
                "name": album.title,
                "child": [format_track(t) for t in tracks],
            }
        }, _get_format(request))

    return error_response(70, "Directory not found", _get_format(request))


@router.get("/getArtists")
@router.get("/getArtists.view")
async def get_artists(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Artist).order_by(Artist.name))
    artists = result.scalars().all()

    # Get album counts
    album_counts = {}
    count_result = await db.execute(
        select(Album.artist_id, func.count(Album.id)).group_by(Album.artist_id)
    )
    for artist_id, count in count_result.all():
        album_counts[artist_id] = count

    index_map: dict[str, list] = {}
    for artist in artists:
        letter = artist.name[0].upper() if artist.name else "#"
        if not letter.isalpha():
            letter = "#"
        index_map.setdefault(letter, []).append({
            "id": artist.id,
            "name": artist.name,
            "albumCount": album_counts.get(artist.id, 0),
            "coverArt": artist.image_url,
        })

    indexes = [{"name": letter, "artist": arts} for letter, arts in sorted(index_map.items())]

    return subsonic_response({
        "artists": {
            "ignoredArticles": "The El La Los Las Le Les",
            "index": indexes,
        }
    }, _get_format(request))


@router.get("/getArtist")
@router.get("/getArtist.view")
async def get_artist(request: Request, db: AsyncSession = Depends(get_db)):
    artist_id = request.query_params.get("id")
    if not artist_id:
        return error_response(10, "Missing id parameter", _get_format(request))

    result = await db.execute(select(Artist).where(Artist.id == artist_id))
    artist = result.scalar_one_or_none()
    if not artist:
        return error_response(70, "Artist not found", _get_format(request))

    albums = (await db.execute(
        select(Album).where(Album.artist_id == artist.id).order_by(Album.year.desc())
    )).scalars().all()

    return subsonic_response({
        "artist": format_artist(artist, albums)
    }, _get_format(request))


@router.get("/getAlbum")
@router.get("/getAlbum.view")
async def get_album(request: Request, db: AsyncSession = Depends(get_db)):
    album_id = request.query_params.get("id")
    if not album_id:
        return error_response(10, "Missing id parameter", _get_format(request))

    result = await db.execute(
        select(Album).options(selectinload(Album.artist)).where(Album.id == album_id)
    )
    album = result.scalar_one_or_none()
    if not album:
        return error_response(70, "Album not found", _get_format(request))

    tracks = (await db.execute(
        select(Track).options(selectinload(Track.artist), selectinload(Track.album), selectinload(Track.analysis))
        .where(Track.album_id == album.id)
        .order_by(Track.disc_number, Track.track_number)
    )).scalars().all()

    return subsonic_response({
        "album": format_album(album, tracks)
    }, _get_format(request))


@router.get("/getSong")
@router.get("/getSong.view")
async def get_song(request: Request, db: AsyncSession = Depends(get_db)):
    song_id = request.query_params.get("id")
    if not song_id:
        return error_response(10, "Missing id parameter", _get_format(request))

    result = await db.execute(
        select(Track).options(selectinload(Track.artist), selectinload(Track.album), selectinload(Track.analysis))
        .where(Track.id == song_id)
    )
    track = result.scalar_one_or_none()
    if not track:
        return error_response(70, "Song not found", _get_format(request))

    return subsonic_response({"song": format_track(track)}, _get_format(request))


@router.get("/getGenres")
@router.get("/getGenres.view")
async def get_genres(request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Track.genre, func.count(Track.id), func.count(func.distinct(Track.album_id)))
        .where(Track.genre.isnot(None))
        .group_by(Track.genre)
        .order_by(func.count(Track.id).desc())
    )
    genres = [
        {"songCount": count, "albumCount": album_count, "value": genre}
        for genre, count, album_count in result.all()
    ]
    return subsonic_response({"genres": {"genre": genres}}, _get_format(request))


@router.get("/getArtistInfo2")
@router.get("/getArtistInfo2.view")
async def get_artist_info2(request: Request, db: AsyncSession = Depends(get_db)):
    artist_id = request.query_params.get("id")
    result = await db.execute(select(Artist).where(Artist.id == artist_id))
    artist = result.scalar_one_or_none()
    if not artist:
        return error_response(70, "Artist not found", _get_format(request))
    return subsonic_response({
        "artistInfo2": {
            "biography": artist.biography or "",
            "musicBrainzId": artist.musicbrainz_id,
            "smallImageUrl": artist.image_url,
            "mediumImageUrl": artist.image_url,
            "largeImageUrl": artist.image_url,
        }
    }, _get_format(request))


@router.get("/getSimilarSongs2")
@router.get("/getSimilarSongs2.view")
async def get_similar_songs2(request: Request, db: AsyncSession = Depends(get_db)):
    song_id = request.query_params.get("id")
    count = min(int(request.query_params.get("count", 50)), 500)

    if not song_id:
        return error_response(10, "Missing id parameter", _get_format(request))

    # Try vibe similarity first (if embeddings exist)
    from backend.models.embedding import TrackEmbedding
    emb_result = await db.execute(select(TrackEmbedding).where(TrackEmbedding.track_id == song_id))
    seed_emb = emb_result.scalar_one_or_none()

    if seed_emb:
        from backend.services.similarity import echo_match
        similar = await echo_match(db, song_id, limit=count)
        track_ids = [s["track_id"] for s in similar]
        if track_ids:
            result = await db.execute(
                select(Track).options(
                    selectinload(Track.artist), selectinload(Track.album), selectinload(Track.analysis)
                ).where(Track.id.in_(track_ids))
            )
            tracks = {t.id: t for t in result.scalars().all()}
            songs = [format_track(tracks[tid]) for tid in track_ids if tid in tracks]
            return subsonic_response({"similarSongs2": {"song": songs}}, _get_format(request))

    # Fallback: random songs from same artist/genre
    result = await db.execute(select(Track).where(Track.id == song_id))
    seed_track = result.scalar_one_or_none()
    if not seed_track:
        return subsonic_response({"similarSongs2": {"song": []}}, _get_format(request))

    query = select(Track).options(
        selectinload(Track.artist), selectinload(Track.album), selectinload(Track.analysis)
    ).where(Track.id != song_id)

    if seed_track.artist_id:
        query = query.where(Track.artist_id == seed_track.artist_id)
    elif seed_track.genre:
        query = query.where(Track.genre == seed_track.genre)

    query = query.order_by(func.random()).limit(count)
    result = await db.execute(query)
    songs = [format_track(t) for t in result.scalars().all()]

    return subsonic_response({"similarSongs2": {"song": songs}}, _get_format(request))


@router.get("/getTopSongs")
@router.get("/getTopSongs.view")
async def get_top_songs(request: Request, db: AsyncSession = Depends(get_db)):
    artist_name = request.query_params.get("artist")
    count = min(int(request.query_params.get("count", 50)), 500)

    if not artist_name:
        return error_response(10, "Missing artist parameter", _get_format(request))

    result = await db.execute(
        select(Track).options(
            selectinload(Track.artist), selectinload(Track.album), selectinload(Track.analysis)
        ).join(Artist).where(Artist.name.ilike(f"%{artist_name}%"))
        .order_by(Track.play_count.desc()).limit(count)
    )
    songs = [format_track(t) for t in result.scalars().all()]

    return subsonic_response({"topSongs": {"song": songs}}, _get_format(request))
