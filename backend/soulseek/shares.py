"""Shared file list — scans music library for Soulseek sharing."""
from __future__ import annotations

import logging
import zlib
from pathlib import Path

from backend.soulseek.protocol.builder import MessageBuilder
from backend.soulseek.protocol.types import PeerMessageCode, FileAttribute

AUDIO_EXTENSIONS = {".flac", ".mp3", ".m4a", ".ogg", ".opus", ".wav", ".wma", ".aac"}

log = logging.getLogger(__name__)

# Cached share data
_cached_response: bytes | None = None
_cached_dirs: int = 0
_cached_files: int = 0


def get_share_counts() -> tuple[int, int]:
    """Return (num_dirs, num_files) from cached scan."""
    return _cached_dirs, _cached_files


def get_shared_file_list_response() -> bytes | None:
    """Return the cached zlib-compressed shared file list response message."""
    return _cached_response


def refresh_shares(music_dir: str) -> tuple[int, int]:
    """Scan the music directory and cache the shared file list.

    Returns (num_dirs, num_files).
    """
    global _cached_response, _cached_dirs, _cached_files

    music_path = Path(music_dir)
    if not music_path.exists():
        log.warning(f"[shares] Music directory not found: {music_dir}")
        _cached_response = None
        _cached_dirs = 0
        _cached_files = 0
        return 0, 0

    # Group files by directory
    dirs: dict[str, list[dict]] = {}
    for f in music_path.rglob("*"):
        if not f.is_file() or f.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        rel = f.relative_to(music_path)
        # Soulseek uses backslash paths
        dir_path = str(rel.parent).replace("/", "\\")
        if dir_path == ".":
            dir_path = ""

        try:
            size = f.stat().st_size
        except OSError:
            continue
        if size == 0:
            continue

        # Get basic attributes from extension
        attrs = {}
        suffix = f.suffix.lower()
        if suffix == ".flac":
            attrs[FileAttribute.BITRATE] = 1411
        elif suffix == ".mp3":
            attrs[FileAttribute.BITRATE] = 320
        elif suffix == ".opus":
            attrs[FileAttribute.BITRATE] = 128
        elif suffix == ".ogg":
            attrs[FileAttribute.BITRATE] = 192

        filename = str(rel).replace("/", "\\")
        dirs.setdefault(dir_path, []).append({
            "filename": filename,
            "size": size,
            "attrs": attrs,
        })

    num_dirs = len(dirs)
    num_files = sum(len(files) for files in dirs.values())

    # Build the response payload (uncompressed first, then zlib)
    inner = MessageBuilder()
    inner.uint32(num_dirs)
    for dir_path, files in sorted(dirs.items()):
        inner.string(dir_path)
        inner.uint32(len(files))
        for f in files:
            inner.uint8(1)  # code
            inner.string(f["filename"])
            inner.uint64(f["size"])
            ext = Path(f["filename"]).suffix.lstrip(".")
            inner.string(ext)
            inner.uint32(len(f["attrs"]))
            for attr_type, attr_value in f["attrs"].items():
                inner.uint32(attr_type)
                inner.uint32(attr_value)

    compressed = zlib.compress(inner.build_no_prefix())

    # Build the full peer message: code + compressed data
    msg = MessageBuilder()
    msg.uint32(PeerMessageCode.SHARED_FILE_LIST_RESPONSE)
    msg.raw(compressed)
    _cached_response = msg.build()

    _cached_dirs = num_dirs
    _cached_files = num_files

    log.info(f"[shares] Cached {num_files} files in {num_dirs} directories")
    return num_dirs, num_files
