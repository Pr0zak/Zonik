"""Subsonic system endpoints: ping, getLicense, getOpenSubsonicExtensions, getLyrics."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
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
