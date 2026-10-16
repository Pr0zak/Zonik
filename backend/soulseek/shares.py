"""Shared file list — what we advertise to Soulseek peers, and what we serve.

The list is built from the library's `tracks` table (file path relative to the
music dir, size, bitrate, duration), so building it needs no walk of the music
dir; only an empty table falls back to a filesystem walk, run in a thread. The
virtual layout is the library layout with backslashes: folder `Artist\\Album`,
file `Artist\\Album\\01 - Song.flac`.

The same list answers browse requests (the cached SharedFileListResponse) and
upload requests (`resolve_shared_file`): a peer can only download a file that is
in it, by its exact virtual path.
"""
from __future__ import annotations

import asyncio
import logging
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from backend.soulseek.protocol.builder import MessageBuilder
from backend.soulseek.protocol.types import PeerMessageCode, FileAttribute

AUDIO_EXTENSIONS = {".flac", ".mp3", ".m4a", ".ogg", ".opus", ".wav", ".wma", ".aac"}

# Rough bitrates for files with no measured one (kbps).
_DEFAULT_BITRATES = {".flac": 1411, ".mp3": 320, ".opus": 128, ".ogg": 192}

log = logging.getLogger(__name__)


@dataclass
class ShareEntry:
    """One library file: path relative to the music dir (either separator)."""
    rel_path: str
    size: int | None = None
    bitrate: int | None = None     # bps or kbps; normalised to kbps
    duration: float | None = None  # seconds


@dataclass
class SharedFile:
    virtual: str  # Soulseek path, backslash-separated, relative to the music dir
    real: Path    # absolute path on disk
    size: int     # size when the list was built (re-checked when serving)
    attrs: dict[int, int] = field(default_factory=dict)


@dataclass
class ShareList:
    response: bytes | None
    index: dict[str, SharedFile]
    num_dirs: int
    num_files: int


# The installed list. Swapped as a whole, so readers never see a half-built one.
_current = ShareList(response=None, index={}, num_dirs=0, num_files=0)
_refresh_lock: asyncio.Lock | None = None


def get_share_counts() -> tuple[int, int]:
    """Return (num_dirs, num_files) of the installed list."""
    return _current.num_dirs, _current.num_files


def get_shared_file_list_response() -> bytes | None:
    """Return the cached zlib-compressed shared file list response message."""
    return _current.response


def _virtual(path: str) -> str:
    return path.replace("/", "\\")


def resolve_shared_file(virtual_path: str) -> SharedFile | None:
    """The shared file a peer asked for by virtual path, or None if it isn't shared.
    Only files in the installed list are ever served; nothing here joins the
    requested path onto the music dir, so a crafted path can't escape it."""
    if not virtual_path:
        return None
    return _current.index.get(_virtual(virtual_path))


def _kbps(bitrate: int | None) -> int | None:
    if not bitrate or bitrate <= 0:
        return None
    return bitrate // 1000 if bitrate >= 10000 else bitrate


def build_share_list(music_dir: str, entries: Iterable[ShareEntry]) -> ShareList:
    """Build the advertised list and the lookup index from library entries.
    Entries without a known size are stat'ed (blocking — call from a thread)."""
    root = Path(music_dir)
    dirs: dict[str, list[SharedFile]] = {}
    index: dict[str, SharedFile] = {}
    for e in entries:
        rel = e.rel_path.replace("\\", "/").lstrip("/")
        if not rel or ".." in rel.split("/"):
            continue
        suffix = Path(rel).suffix.lower()
        if suffix not in AUDIO_EXTENSIONS:
            continue
        virtual = _virtual(rel)
        if virtual in index:
            continue
        real = root / rel
        size = e.size
        if not size:
            try:
                size = real.stat().st_size
            except OSError:
                continue
        if not size:
            continue
        attrs: dict[int, int] = {}
        kbps = _kbps(e.bitrate) or _DEFAULT_BITRATES.get(suffix)
        if kbps:
            attrs[FileAttribute.BITRATE] = kbps
        if e.duration and e.duration > 0:
            attrs[FileAttribute.DURATION] = int(round(e.duration))
        parent = str(Path(rel).parent)
        dir_path = "" if parent == "." else _virtual(parent)
        sf = SharedFile(virtual=virtual, real=real, size=int(size), attrs=attrs)
        index[virtual] = sf
        dirs.setdefault(dir_path, []).append(sf)

    inner = MessageBuilder()
    inner.uint32(len(dirs))
    for dir_path, files in sorted(dirs.items()):
        inner.string(dir_path)
        inner.uint32(len(files))
        for f in files:
            inner.uint8(1)  # code
            inner.string(f.virtual)
            inner.uint64(f.size)
            inner.string(Path(f.virtual.replace("\\", "/")).suffix.lstrip("."))
            inner.uint32(len(f.attrs))
            for attr_type, attr_value in f.attrs.items():
                inner.uint32(attr_type)
                inner.uint32(attr_value)
    return ShareList(response=_wrap(inner), index=index, num_dirs=len(dirs), num_files=len(index))


def _wrap(inner: MessageBuilder) -> bytes:
    msg = MessageBuilder()
    msg.uint32(PeerMessageCode.SHARED_FILE_LIST_RESPONSE)
    msg.raw(zlib.compress(inner.build_no_prefix()))
    return msg.build()


def _empty_list() -> ShareList:
    inner = MessageBuilder()
    inner.uint32(0)  # 0 directories
    return ShareList(response=_wrap(inner), index={}, num_dirs=0, num_files=0)


def scan_filesystem_entries(music_dir: str) -> list[ShareEntry]:
    """Walk the music dir (blocking, slow on NFS — only the empty-DB fallback)."""
    music_path = Path(music_dir)
    if not music_path.exists():
        log.warning(f"[shares] Music directory not found: {music_dir}")
        return []
    out: list[ShareEntry] = []
    for f in music_path.rglob("*"):
        if f.suffix.lower() not in AUDIO_EXTENSIONS or not f.is_file():
            continue
        try:
            size = f.stat().st_size
        except OSError:
            continue
        out.append(ShareEntry(rel_path=str(f.relative_to(music_path)), size=size))
    return out


async def load_db_entries() -> list[ShareEntry]:
    """Every track in the library, as share entries (one query, no disk access)."""
    from sqlalchemy import select
    from backend.database import async_session
    from backend.models.track import Track

    async with async_session() as s:
        rows = await s.execute(
            select(Track.file_path, Track.file_size, Track.bitrate, Track.duration_seconds)
        )
        return [
            ShareEntry(rel_path=p, size=size, bitrate=br, duration=dur)
            for p, size, br, dur in rows.all() if p
        ]


def install(share_list: ShareList) -> None:
    global _current
    _current = share_list


_bg: set[asyncio.Task] = set()


def refresh_shares(music_dir: str, share_library: bool | None = None) -> tuple[int, int]:
    """Refresh the list from synchronous code (the library scan calls this when it
    finishes). share_library=None reads it from the settings.

    Inside a running event loop this never blocks: it schedules
    refresh_shares_async (which reports the new counts to the server when done)
    and returns the counts installed now. Without a loop it builds from a
    filesystem walk in place. Returns (num_dirs, num_files)."""
    if share_library is None:
        from backend.config import get_settings
        share_library = get_settings().soulseek.share_library
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _refresh_shares_blocking(music_dir, share_library)
    task = asyncio.create_task(_refresh_and_report(music_dir, share_library))
    _bg.add(task)
    task.add_done_callback(_bg.discard)
    return get_share_counts()


async def _refresh_and_report(music_dir: str, share_library: bool) -> None:
    try:
        await refresh_shares_async(music_dir, share_library)
        from backend.soulseek import get_client
        client = get_client()
        if client is not None and client.server.logged_in:
            await client._report_shares_to_server()
    except Exception as e:
        log.warning(f"[shares] Background refresh failed: {e}")


def _refresh_shares_blocking(music_dir: str, share_library: bool) -> tuple[int, int]:
    if not share_library:
        install(_empty_list())
        log.info("[shares] Library sharing disabled — reporting empty shares")
        return 0, 0
    install(build_share_list(music_dir, scan_filesystem_entries(music_dir)))
    log.info(f"[shares] Cached {_current.num_files} files in {_current.num_dirs} directories")
    return _current.num_dirs, _current.num_files


async def refresh_shares_async(
    music_dir: str,
    share_library: bool = True,
    *,
    load_entries=load_db_entries,
) -> tuple[int, int]:
    """Rebuild the list without blocking the event loop: the track table first,
    the filesystem walk (in a thread) only when the table is empty. The previous
    list stays installed until the new one is ready. Returns (num_dirs, num_files)."""
    global _refresh_lock
    if _refresh_lock is None:
        _refresh_lock = asyncio.Lock()
    async with _refresh_lock:
        if not share_library:
            install(_empty_list())
            log.info("[shares] Library sharing disabled — reporting empty shares")
            return 0, 0
        source = "database"
        try:
            entries = await load_entries()
        except Exception as e:
            log.warning(f"[shares] Could not read the track table: {e}")
            entries = []
        if not entries:
            source = "filesystem"
            entries = await asyncio.to_thread(scan_filesystem_entries, music_dir)
        share_list = await asyncio.to_thread(build_share_list, music_dir, entries)
        install(share_list)
        log.info(f"[shares] Cached {share_list.num_files} files in {share_list.num_dirs} "
                 f"directories (from the {source})")
        return share_list.num_dirs, share_list.num_files
