"""Subsonic media endpoints: stream, download, getCoverArt."""
from __future__ import annotations

import asyncio
import logging
import tempfile
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

# Concurrency limiter for ffmpeg processes
_transcode_semaphore: asyncio.Semaphore | None = None


def _get_transcode_semaphore() -> asyncio.Semaphore:
    global _transcode_semaphore
    if _transcode_semaphore is None:
        settings = get_settings()
        _transcode_semaphore = asyncio.Semaphore(settings.streaming.max_concurrent_transcodes)
    return _transcode_semaphore


def _get_format(request: Request) -> str:
    return request.query_params.get("f", "json")


# ---------------------------------------------------------------------------
# Transcode cache helpers
# ---------------------------------------------------------------------------

def _transcode_cache_path(track_id: str, fmt: str, bitrate: int) -> Path:
    """Return the cache file path for a transcoded track."""
    settings = get_settings()
    cache_dir = Path(settings.streaming.transcode_cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{track_id}_{fmt}_{bitrate}.{fmt}"


def _transcode_cache_hit(cache_path: Path, source_path: Path) -> bool:
    """Check if a valid cached transcode exists (newer than source)."""
    return (
        cache_path.exists()
        and cache_path.stat().st_size > 0
        and cache_path.stat().st_mtime >= source_path.stat().st_mtime
    )


def _evict_transcode_cache():
    """Delete oldest cached transcodes if total size exceeds limit."""
    settings = get_settings()
    cache_dir = Path(settings.streaming.transcode_cache_dir)
    if not cache_dir.exists():
        return
    max_bytes = settings.streaming.transcode_cache_max_mb * 1024 * 1024
    files = sorted(cache_dir.iterdir(), key=lambda f: f.stat().st_atime)
    total = sum(f.stat().st_size for f in files if f.is_file())
    for f in files:
        if total <= max_bytes:
            break
        if f.is_file():
            size = f.stat().st_size
            f.unlink(missing_ok=True)
            total -= size


# ---------------------------------------------------------------------------
# Cover art resize helper
# ---------------------------------------------------------------------------

def _get_resized_cover(source: Path, size: int) -> Path | None:
    """Resize cover art and cache the result. Returns cached path or None."""
    settings = get_settings()
    cache_dir = Path(settings.library.cover_cache_dir) / "resized"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"{source.stem}_{size}.jpg"
    if cached.exists() and cached.stat().st_mtime >= source.stat().st_mtime:
        return cached
    try:
        from PIL import Image
        img = Image.open(source)
        img.thumbnail((size, size), Image.Resampling.LANCZOS)
        img = img.convert("RGB")
        img.save(cached, "JPEG", quality=85, optimize=True)
        return cached
    except Exception as e:
        log.warning(f"Cover resize failed: {e}")
        # Delete corrupt source file so it gets re-fetched on next scan
        if source.exists() and "cannot identify image file" in str(e):
            try:
                source.unlink()
                log.info(f"Deleted corrupt cover cache: {source.name}")
            except OSError:
                pass
        return None


# ---------------------------------------------------------------------------
# Stream endpoint
# ---------------------------------------------------------------------------

@router.head("/stream")
@router.head("/stream.view")
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
    estimate = request.query_params.get("estimateContentLength", "false") == "true"
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

    # --- Transcoding path ---
    effective_bitrate = target_bitrate or 192
    content_type = TRANSCODE_CONTENT_TYPES.get(target_format, "audio/mpeg")

    # Check transcode cache (skip for timeOffset seeks)
    if time_offset == 0:
        cache_path = _transcode_cache_path(track.id, target_format, effective_bitrate)
        if _transcode_cache_hit(cache_path, file_path):
            return FileResponse(
                path=str(cache_path),
                media_type=content_type,
                filename=f"{file_path.stem}.{target_format}",
                content_disposition_type="inline",
                headers={"Cache-Control": "private, max-age=86400"},
            )

    # Build estimated content-length for HEAD or estimateContentLength
    estimated_bytes = None
    if track.duration_seconds and effective_bitrate:
        remaining = track.duration_seconds - time_offset if time_offset > 0 else track.duration_seconds
        if remaining > 0:
            estimated_bytes = int((remaining * effective_bitrate * 1000) / 8)

    # HEAD request — return headers only, no ffmpeg
    if request.method == "HEAD":
        headers: dict[str, str] = {
            "Cache-Control": "private, max-age=86400",
            "Accept-Ranges": "none",
        }
        if estimated_bytes:
            headers["Content-Length"] = str(estimated_bytes)
        return Response(media_type=content_type, headers=headers)

    # Build ffmpeg command (-y to overwrite temp files from mkstemp)
    cmd = ["ffmpeg", "-y", "-fflags", "+flush_packets", "-threads", "1"]
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

    cmd.extend(["-flush_packets", "1", "-vn"])

    # Transcode to cache file (no timeOffset) or stream directly
    if time_offset == 0:
        # Transcode to temp file → rename into cache → serve via FileResponse
        cache_path = _transcode_cache_path(track.id, target_format, effective_bitrate)
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        async with _get_transcode_semaphore():
            tmp_fd, tmp_path_str = tempfile.mkstemp(
                suffix=f".{target_format}", dir=str(cache_path.parent)
            )
            import os
            os.close(tmp_fd)
            tmp_path = Path(tmp_path_str)
            try:
                file_cmd = cmd + [str(tmp_path)]
                process = await asyncio.create_subprocess_exec(
                    *file_cmd,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr_data = await process.communicate()
                if process.returncode != 0 or not tmp_path.exists() or tmp_path.stat().st_size == 0:
                    log.warning(
                        f"ffmpeg exited {process.returncode} for {file_path.name}: "
                        f"{stderr_data.decode(errors='replace')[-500:]}"
                    )
                    tmp_path.unlink(missing_ok=True)
                    return error_response(0, "Transcoding failed", _get_format(request))
                tmp_path.rename(cache_path)
            except Exception:
                tmp_path.unlink(missing_ok=True)
                raise

        # Evict old cache entries in background
        _evict_transcode_cache()

        return FileResponse(
            path=str(cache_path),
            media_type=content_type,
            filename=f"{file_path.stem}.{target_format}",
            content_disposition_type="inline",
            headers={"Cache-Control": "private, max-age=86400"},
        )

    # timeOffset > 0: stream directly (can't cache partial seeks)
    stream_cmd = cmd + ["-"]

    response_headers: dict[str, str] = {
        "Cache-Control": "private, max-age=86400",
        "Accept-Ranges": "none",
    }
    if estimate and estimated_bytes:
        response_headers["Content-Length"] = str(estimated_bytes)

    async def generate():
        async with _get_transcode_semaphore():
            process = await asyncio.create_subprocess_exec(
                *stream_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
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
                if process.returncode and process.returncode != 0:
                    stderr_out = await process.stderr.read()
                    log.warning(
                        f"ffmpeg exited {process.returncode} for {file_path.name}: "
                        f"{stderr_out.decode(errors='replace')[-500:]}"
                    )

    return StreamingResponse(generate(), media_type=content_type, headers=response_headers)


# ---------------------------------------------------------------------------
# Download endpoint
# ---------------------------------------------------------------------------

@router.head("/download")
@router.head("/download.view")
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


# ---------------------------------------------------------------------------
# Cover art endpoint
# ---------------------------------------------------------------------------

@router.head("/getCoverArt")
@router.head("/getCoverArt.view")
@router.get("/getCoverArt")
@router.get("/getCoverArt.view")
async def get_cover_art(request: Request, db: AsyncSession = Depends(get_db)):
    cover_id = request.query_params.get("id")
    if not cover_id:
        return error_response(10, "Missing id parameter", _get_format(request))

    # Parse optional size parameter for resizing
    size_param = request.query_params.get("size")
    target_size = None
    if size_param:
        try:
            target_size = min(int(size_param), 1200)
            if target_size <= 0:
                target_size = None
        except (ValueError, TypeError):
            pass

    _cover_cache = {"Cache-Control": "public, max-age=604800"}

    def _serve_cover(source_path: Path) -> FileResponse:
        """Serve cover art, optionally resized."""
        if target_size:
            resized = _get_resized_cover(source_path, target_size)
            if resized:
                return FileResponse(path=str(resized), media_type="image/jpeg", headers=_cover_cache)
        media_type = "image/jpeg"
        if source_path.suffix.lower() == ".png":
            media_type = "image/png"
        return FileResponse(path=str(source_path), media_type=media_type, headers=_cover_cache)

    # cover_id might be a file path to cached cover art
    cover_path = Path(cover_id)
    if cover_path.exists():
        return _serve_cover(cover_path)

    # Try to find track/album cover
    result = await db.execute(select(Track).where(Track.id == cover_id))
    track = result.scalar_one_or_none()
    if track and track.cover_art_path:
        path = Path(track.cover_art_path)
        if path.exists():
            return _serve_cover(path)

    from backend.models.album import Album
    result = await db.execute(select(Album).where(Album.id == cover_id))
    album = result.scalar_one_or_none()
    if album and album.cover_art_path:
        path = Path(album.cover_art_path)
        if path.exists():
            return _serve_cover(path)

    # Return 1x1 transparent pixel as fallback
    return Response(
        content=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n\xb4\x00\x00\x00\x00IEND\xaeB`\x82",
        media_type="image/png",
        headers=_cover_cache,
    )
