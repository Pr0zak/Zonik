"""Subsonic system endpoints: ping, getLicense, getOpenSubsonicExtensions, getLyrics."""
from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.models.track import Track
from backend.subsonic.responses import subsonic_response

router = APIRouter()


def _get_format(request: Request) -> str:
    return request.query_params.get("f", "json")


@router.get("/ping")
@router.get("/ping.view")
async def ping(request: Request):
    return subsonic_response({}, _get_format(request))


# Everything a client's full library sync downloads, as cheap column lists. Play and skip
# counts are left out on purpose, and so is tracks.updated_at, which a scrobble bumps: they
# change on every song, and folding them in would make the library look "changed" the whole
# time a client is playing, which defeats the check.
_LIBRARY_VERSION_QUERIES = (
    "SELECT id, title, artist_id, album_id, track_number, disc_number, duration_seconds,"
    " file_size, format, bitrate, genre, year, cover_art_path, rating"
    " FROM tracks ORDER BY id",
    "SELECT id, title, artist_id, year, genre, cover_art_path, track_count, is_compilation"
    " FROM albums ORDER BY id",
    "SELECT id, name, sort_name, image_url FROM artists ORDER BY id",
    "SELECT track_id, bpm FROM track_analysis ORDER BY track_id",
    "SELECT id, track_id, album_id, artist_id FROM favorites ORDER BY id",
    "SELECT id, name, comment, is_public, updated_at FROM playlists ORDER BY id",
    "SELECT playlist_id, track_id, position FROM playlist_tracks ORDER BY playlist_id, position",
)


@router.get("/getLibraryVersion")
@router.get("/getLibraryVersion.view")
async def get_library_version(request: Request, db: AsyncSession = Depends(get_db)):
    """Zonik extension: a fingerprint of the library a client syncs.

    It changes whenever anything a full sync would fetch changes (tracks, albums, artists,
    tempo, stars, playlists), so a client can compare it with the one from its last sync and
    skip the sync when they match. Hashing the ~30k narrow rows takes about a tenth of a
    second, against the ~20 s and dozens of requests a full sync costs.
    """
    digest = hashlib.sha1()
    for query in _LIBRARY_VERSION_QUERIES:
        result = await db.execute(text(query))
        for row in result:
            digest.update(repr(tuple(row)).encode())
        digest.update(b"|")
    return subsonic_response(
        {"libraryVersion": {"version": digest.hexdigest()}}, _get_format(request)
    )


@router.get("/getLicense")
@router.get("/getLicense.view")
async def get_license(request: Request):
    return subsonic_response({
        "license": {
            "valid": True,
            "email": "zonik@localhost",
        }
    }, _get_format(request))


@router.get("/getOpenSubsonicExtensions")
@router.get("/getOpenSubsonicExtensions.view")
async def get_open_subsonic_extensions(request: Request):
    # NOTE: songLyrics is intentionally omitted — Zonik does not store lyrics.
    # The /getLyrics and /getLyricsBySongId endpoints below are stubs so clients
    # that probe them get a well-formed empty response instead of a 404.
    return subsonic_response({
        "openSubsonicExtensions": [
            {"name": "transcodeOffset", "versions": [1]},
            {"name": "formPost", "versions": [1]},
            {"name": "mediaType", "versions": [1]},
        ]
    }, _get_format(request))


@router.get("/getLyrics")
@router.get("/getLyrics.view")
async def get_lyrics(request: Request, db: AsyncSession = Depends(get_db)):
    """Return empty lyrics — Zonik does not store lyrics. Spec: 1.2+."""
    artist = request.query_params.get("artist", "")
    title = request.query_params.get("title", "")
    return subsonic_response({
        "lyrics": {
            "artist": artist,
            "title": title,
            "value": "",
        }
    }, _get_format(request))


@router.get("/getLyricsBySongId")
@router.get("/getLyricsBySongId.view")
async def get_lyrics_by_song_id(request: Request, db: AsyncSession = Depends(get_db)):
    """OpenSubsonic structured lyrics endpoint — returns empty list. Zonik
    does not store lyrics; included so clients don't 404 if they probe it."""
    song_id = request.query_params.get("id", "")
    artist_name = ""
    title = ""
    if song_id:
        result = await db.execute(
            select(Track).options(selectinload(Track.artist)).where(Track.id == song_id)
        )
        track = result.scalar_one_or_none()
        if track:
            artist_name = track.artist.name if track.artist else ""
            title = track.title
    return subsonic_response({
        "lyricsList": {
            "structuredLyrics": [
                {
                    "displayArtist": artist_name,
                    "displayTitle": title,
                    "lang": "xxx",
                    "synced": False,
                    "line": [],
                }
            ]
        }
    }, _get_format(request))
