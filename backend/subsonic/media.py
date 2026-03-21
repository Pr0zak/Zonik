"""Subsonic media endpoints: stream, download, getCoverArt."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Request, Depends
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import get_db
from backend.models.track import Track
from backend.subsonic.responses import error_response

router = APIRouter()
log = logging.getLogger(__name__)

# Formats that don't need transcoding
PASSTHROUGH_FORMATS = {"mp3", "ogg", "opus", "aac", "m4a"}

TRANSCODE_CONTENT_TYPES = {
    "mp3": "audio/mpeg",
    "ogg": "audio/ogg",
    "opus": "audio/ogg",
    "aac": "audio/aac",
    "raw": "application/octet-stream",
}


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

    # Check if transcoding is requested
    max_bitrate = request.query_params.get("maxBitRate")
    transcode_format = request.query_params.get("format")
    try:
        time_offset = max(0, int(request.query_params.get("timeOffset", 0)))
    except (ValueError, TypeError):
        time_offset = 0

    # Determine if we need to transcode
    needs_transcode = False
    target_format = "mp3"  # default transcode target
    target_bitrate = None

    if transcode_format and transcode_format != "raw":
        target_format = transcode_format
        needs_transcode = True

    if max_bitrate:
        try:
            target_bitrate = int(max_bitrate)
        except (ValueError, TypeError):
            target_bitrate = None
        if not target_bitrate or target_bitrate <= 0:
            target_bitrate = None
        track_kbps = (track.bitrate // 1000) if track.bitrate else 0
        if target_bitrate and track_kbps > target_bitrate:
            needs_transcode = True

    if time_offset > 0:
        needs_transcode = True

    # For lossless formats, always transcode if client requests it
    if track.suffix in ("flac", "wav", "alac", "aiff") and not needs_transcode:
        # Direct serve lossless - client can handle it
        pass

    if not needs_transcode:
        return FileResponse(
            path=str(file_path),
            media_type=track.mime_type or "audio/mpeg",
            filename=file_path.name,
            content_disposition_type="inline",
            headers={"Cache-Control": "private, max-age=86400"},
        )

    # Transcode with ffmpeg (flush flags for low-latency streaming)
    cmd = ["ffmpeg", "-fflags", "+flush_packets"]
    if time_offset > 0:
        cmd.extend(["-ss", str(time_offset)])
    cmd.extend(["-i", str(file_path)])

    if target_format == "mp3":
        cmd.extend(["-f", "mp3", "-c:a", "libmp3lame"])
        if target_bitrate:
            cmd.extend(["-b:a", f"{target_bitrate}k"])
        else:
            cmd.extend(["-b:a", "192k"])
    elif target_format == "ogg":
        cmd.extend(["-f", "ogg", "-c:a", "libvorbis"])
        if target_bitrate:
            cmd.extend(["-b:a", f"{target_bitrate}k"])
    elif target_format == "opus":
        cmd.extend(["-f", "ogg", "-c:a", "libopus"])
        if target_bitrate:
            cmd.extend(["-b:a", f"{target_bitrate}k"])
    elif target_format == "aac":
        cmd.extend(["-f", "adts", "-c:a", "aac"])
        if target_bitrate:
            cmd.extend(["-b:a", f"{target_bitrate}k"])
    else:
        cmd.extend(["-f", "mp3", "-c:a", "libmp3lame", "-b:a", "192k"])

    cmd.extend(["-flush_packets", "1", "-vn", "-"])  # Low-latency, no video, stdout

    content_type = TRANSCODE_CONTENT_TYPES.get(target_format, "audio/mpeg")

    async def generate():
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            while True:
                chunk = await process.stdout.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            if process.returncode is None:
                process.kill()
            await process.wait()

    return StreamingResponse(
        generate(),
        media_type=content_type,
        headers={
            "Cache-Control": "private, max-age=86400",
            "Accept-Ranges": "none",
        },
    )


@router.get("/download")
@router.get("/download.view")
async def download(request: Request, db: AsyncSession = Depends(get_db)):
    """Download always serves original file (no transcoding)."""
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
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.get("/getCoverArt")
@router.get("/getCoverArt.view")
async def get_cover_art(request: Request, db: AsyncSession = Depends(get_db)):
    cover_id = request.query_params.get("id")
    if not cover_id:
        return error_response(10, "Missing id parameter", _get_format(request))

    _cover_cache = {"Cache-Control": "public, max-age=604800"}

    # cover_id might be a file path to cached cover art
    cover_path = Path(cover_id)
    if cover_path.exists():
        media_type = "image/jpeg"
        if cover_path.suffix.lower() == ".png":
            media_type = "image/png"
        return FileResponse(path=str(cover_path), media_type=media_type, headers=_cover_cache)

    # Try to find track/album cover
    result = await db.execute(select(Track).where(Track.id == cover_id))
    track = result.scalar_one_or_none()
    if track and track.cover_art_path:
        path = Path(track.cover_art_path)
        if path.exists():
            return FileResponse(path=str(path), media_type="image/jpeg", headers=_cover_cache)

    from backend.models.album import Album
    result = await db.execute(select(Album).where(Album.id == cover_id))
    album = result.scalar_one_or_none()
    if album and album.cover_art_path:
        path = Path(album.cover_art_path)
        if path.exists():
            return FileResponse(path=str(path), media_type="image/jpeg", headers=_cover_cache)

    # Return 1x1 transparent pixel as fallback
    return Response(
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n\xb4\x00\x00\x00\x00IEND\xaeB`\x82",
        media_type="image/png",
        headers=_cover_cache,
    )
