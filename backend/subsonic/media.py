"""Subsonic media endpoints: stream, download, getCoverArt."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request, Depends
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import get_db
from backend.models.track import Track
from backend.subsonic.responses import error_response

router = APIRouter()


def _get_format(request: Request) -> str:
    return request.query_params.get("f", "json")


@router.get("/stream")
@router.get("/stream.view")
async def stream(request: Request, db: AsyncSession = Depends(get_db)):
    song_id = request.query_params.get("id")
    if not song_id:
        return error_response(10, "Missing id parameter", _get_format(request))

    result = await db.execute(select(Track).where(Track.id == song_id))
    track = result.scalar_one_or_none()
    if not track:
        return error_response(70, "Song not found", _get_format(request))

    settings = get_settings()
    file_path = Path(settings.library.music_dir) / track.file_path

    if not file_path.exists():
        return error_response(70, "File not found", _get_format(request))

    return FileResponse(
        path=str(file_path),
        media_type=track.mime_type or "audio/mpeg",
        filename=file_path.name,
    )


@router.get("/download")
@router.get("/download.view")
async def download(request: Request, db: AsyncSession = Depends(get_db)):
    # Same as stream for now
    return await stream(request, db)


@router.get("/getCoverArt")
@router.get("/getCoverArt.view")
async def get_cover_art(request: Request, db: AsyncSession = Depends(get_db)):
    cover_id = request.query_params.get("id")
    if not cover_id:
        return error_response(10, "Missing id parameter", _get_format(request))

    # cover_id might be a file path to cached cover art
    cover_path = Path(cover_id)
    if cover_path.exists():
        media_type = "image/jpeg"
        if cover_path.suffix.lower() == ".png":
            media_type = "image/png"
        return FileResponse(path=str(cover_path), media_type=media_type)

    # Try to find track/album cover
    result = await db.execute(select(Track).where(Track.id == cover_id))
    track = result.scalar_one_or_none()
    if track and track.cover_art_path:
        path = Path(track.cover_art_path)
        if path.exists():
            return FileResponse(path=str(path), media_type="image/jpeg")

    from backend.models.album import Album
    result = await db.execute(select(Album).where(Album.id == cover_id))
    album = result.scalar_one_or_none()
    if album and album.cover_art_path:
        path = Path(album.cover_art_path)
        if path.exists():
            return FileResponse(path=str(path), media_type="image/jpeg")

    # Return 1x1 transparent pixel as fallback
    return Response(
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n\xb4\x00\x00\x00\x00IEND\xaeB`\x82",
        media_type="image/png",
    )
