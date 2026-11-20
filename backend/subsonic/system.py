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
# time a client is playing, which defeats the check. Ratings, stars and playlists are the
# caller's own (:uid), so one user's changes don't trigger another user's resync.
_LIBRARY_VERSION_QUERIES = (
    "SELECT id, title, artist_id, album_id, track_number, disc_number, duration_seconds,"
    " file_size, format, bitrate, genre, year, cover_art_path"
    " FROM tracks ORDER BY id",
    "SELECT track_id, rating FROM user_track_stats"
    " WHERE user_id = :uid AND rating IS NOT NULL ORDER BY track_id",
    "SELECT id, title, artist_id, year, genre, cover_art_path, track_count, is_compilation"
    " FROM albums ORDER BY id",
    "SELECT id, name, sort_name, image_url FROM artists ORDER BY id",
    "SELECT track_id, bpm FROM track_analysis ORDER BY track_id",
    "SELECT id, track_id, album_id, artist_id FROM favorites WHERE user_id = :uid ORDER BY id",
    "SELECT id, name, comment, is_public, updated_at, user_id FROM playlists"
    " WHERE user_id = :uid OR is_public = 1 OR user_id IS NULL ORDER BY id",
    "SELECT pt.playlist_id, pt.track_id, pt.position FROM playlist_tracks pt"
    " JOIN playlists p ON p.id = pt.playlist_id"
    " WHERE p.user_id = :uid OR p.is_public = 1 OR p.user_id IS NULL"
    " ORDER BY pt.playlist_id, pt.position",
)


@router.get("/getLibraryVersion")
@router.get("/getLibraryVersion.view")
async def get_library_version(request: Request, db: AsyncSession = Depends(get_db)):
    """Zonik extension: a fingerprint of the library a client syncs.

    It changes whenever anything a full sync would fetch changes (tracks, albums, artists,
    tempo, the caller's ratings and stars, the playlists they see), so a client can compare
    it with the one from its last sync and skip the sync when they match. Hashing the ~30k
    narrow rows takes about a tenth of a second, against the ~20 s and dozens of requests a
    full sync costs.
    """
    from backend.services.user_data import caller_id
    params = {"uid": await caller_id(request, db) or ""}
    digest = hashlib.sha1()
    for query in _LIBRARY_VERSION_QUERIES:
        result = await db.execute(text(query), params)
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
    # songLyrics: lyrics come from the Lyrics section's store (backend/services/lyrics.py).
    return subsonic_response({
        "openSubsonicExtensions": [
            {"name": "songLyrics", "versions": [1]},
            {"name": "transcodeOffset", "versions": [1]},
            {"name": "formPost", "versions": [1]},
            {"name": "mediaType", "versions": [1]},
        ]
    }, _get_format(request))


async def _stored_lyrics(db: AsyncSession, track_id: str) -> tuple[bool, list]:
    """(synced, [[ms, text]]) for a track from the Lyrics section's store; looked up now
    (file, then LRCLIB if allowed) when it never was."""
    from backend.api.lyrics import online_allowed
    from backend.services.lyrics import get_or_find
    p = await get_or_find(db, track_id, await online_allowed(db))
    if p.get("status") != "found":
        return False, []
    return bool(p.get("synced")), [[ln["ms"], ln["text"]] for ln in p.get("lines", [])]


@router.get("/getLyrics")
@router.get("/getLyrics.view")
async def get_lyrics(request: Request, db: AsyncSession = Depends(get_db)):
    """Plain lyrics by artist and title (Subsonic 1.2+), from the stored lyrics of the first
    matching track."""
    from backend.models.artist import Artist
    artist = request.query_params.get("artist", "")
    title = request.query_params.get("title", "")
    value = ""
    if title:
        q = select(Track.id).where(Track.title.ilike(title))
        if artist:
            q = q.join(Artist, Artist.id == Track.artist_id).where(Artist.name.ilike(artist))
        track_id = (await db.execute(q.limit(1))).scalar_one_or_none()
        if track_id:
            _, lines = await _stored_lyrics(db, track_id)
            value = "\n".join(t for _, t in lines)
    return subsonic_response({
        "lyrics": {
            "artist": artist,
            "title": title,
            "value": value,
        }
    }, _get_format(request))


@router.get("/getLyricsBySongId")
@router.get("/getLyricsBySongId.view")
async def get_lyrics_by_song_id(request: Request, db: AsyncSession = Depends(get_db)):
    """OpenSubsonic structured lyrics (songLyrics extension): timed lines when the stored
    lyrics have them."""
    song_id = request.query_params.get("id", "")
    artist_name = ""
    title = ""
    synced = False
    lines: list = []
    if song_id:
        result = await db.execute(
            select(Track).options(selectinload(Track.artist)).where(Track.id == song_id)
        )
        track = result.scalar_one_or_none()
        if track:
            artist_name = track.artist.name if track.artist else ""
            title = track.title
            synced, lines = await _stored_lyrics(db, song_id)
    line = [({"start": ms, "value": t} if synced else {"value": t}) for ms, t in lines]
    return subsonic_response({
        "lyricsList": {
            "structuredLyrics": [
                {
                    "displayArtist": artist_name,
                    "displayTitle": title,
                    "lang": "xxx",
                    "synced": synced,
                    "line": line,
                }
            ] if line else []
        }
    }, _get_format(request))
