"""Lyrics for each track, for the TV visualizer's flying words and the Subsonic lyrics calls.

Looked for in order: embedded in the file's tags (ID3 USLT, Vorbis/FLAC LYRICS or
UNSYNCEDLYRICS, MP4 ©lyr), a `.lrc` file beside the track, and, when allowed, LRCLIB
(https://lrclib.net, free, no key), which mostly has lyrics timed line by line. The result
is kept in `track_lyrics`, a miss included; a miss is looked for again after RETRY_DAYS.

Only the track's artist, title, album and duration are sent to LRCLIB, with a generic
User-Agent.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.config import get_settings
from backend.models.lyrics import TrackLyrics
from backend.models.track import Track

log = logging.getLogger(__name__)

LRCLIB_URL = "https://lrclib.net/api/get"
USER_AGENT = "lyrics-client/1.0"
RETRY_DAYS = 30
_LRC_LINE = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")


def parse_lrc(text: str) -> list[list]:
    """Timed lines from LRC text, as [ms, text] sorted by time; [] if it has no timestamps.

    A line may carry several timestamps (a repeated chorus); each becomes its own entry.
    """
    out: list[list] = []
    for raw in text.splitlines():
        stamps = list(_LRC_LINE.finditer(raw))
        if not stamps:
            continue
        words = _LRC_LINE.sub("", raw).strip()
        for m in stamps:
            frac = m.group(3) or "0"
            ms = int(m.group(1)) * 60_000 + int(m.group(2)) * 1000 + int(frac.ljust(3, "0")[:3])
            out.append([ms, words])
    out.sort(key=lambda x: x[0])
    return out


def plain_lines(text: str) -> list[list]:
    """Untimed lyrics as [-1, line], blank lines and [section] markers dropped."""
    return [[-1, ln.strip()] for ln in text.splitlines()
            if ln.strip() and not re.fullmatch(r"\[.*\]", ln.strip())]


def to_lines(text: str) -> tuple[list[list], bool]:
    """Lines from text that may be LRC or plain, and whether they are timed."""
    timed = parse_lrc(text)
    if len(timed) >= 3:
        return timed, True
    return plain_lines(text), False


def from_file(abs_path: Path) -> tuple[str, str] | None:
    """(text, source) from the file's tags or a .lrc beside it, or None."""
    lrc = abs_path.with_suffix(".lrc")
    if lrc.is_file():
        try:
            return lrc.read_text(encoding="utf-8", errors="replace"), "lrc"
        except OSError:
            pass
    try:
        import mutagen
        f = mutagen.File(abs_path)
    except Exception as e:  # unreadable or unknown format
        log.debug("lyrics: cannot read tags of %s: %s", abs_path, e)
        return None
    if f is None or f.tags is None:
        return None
    tags = f.tags
    try:
        # ID3 (MP3): USLT frames.
        if hasattr(tags, "getall"):
            for frame in tags.getall("USLT"):
                if str(frame.text).strip():
                    return str(frame.text), "tags"
        # MP4 (M4A/ALAC).
        if "\xa9lyr" in tags:
            v = tags["\xa9lyr"]
            text = v[0] if isinstance(v, list) else v
            if str(text).strip():
                return str(text), "tags"
        # Vorbis comments (FLAC, Ogg, Opus).
        for key in ("LYRICS", "lyrics", "UNSYNCEDLYRICS", "unsyncedlyrics"):
            if key in tags:
                v = tags[key]
                text = v[0] if isinstance(v, list) else v
                if str(text).strip():
                    return str(text), "tags"
    except Exception as e:
        log.debug("lyrics: tag read failed for %s: %s", abs_path, e)
    return None


async def from_lrclib(client: httpx.AsyncClient, artist: str, title: str, album: str | None,
                      duration: float | None) -> str | None:
    """Lyrics text from LRCLIB (timed when it has them), or None for none found."""
    params = {"artist_name": artist, "track_name": title}
    if album:
        params["album_name"] = album
    if duration:
        params["duration"] = str(round(duration))
    r = await client.get(LRCLIB_URL, params=params)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json()
    if data.get("instrumental"):
        return None
    return data.get("syncedLyrics") or data.get("plainLyrics") or None


def payload(row: TrackLyrics | None) -> dict:
    """The API's view of a row: {status, synced, source, lines: [{ms, text}]}."""
    if row is None:
        return {"status": "none", "synced": False, "lines": []}
    lines = json.loads(row.lines) if row.lines else []
    return {
        "status": row.status,
        "synced": bool(row.synced),
        "source": row.source,
        "lines": [{"ms": ms, "text": t} for ms, t in lines],
    }


def _stale(row: TrackLyrics) -> bool:
    return row.status != "found" and (row.checked_at or datetime.min) < datetime.utcnow() - timedelta(days=RETRY_DAYS)


async def find(db: AsyncSession, track: Track, online: bool, client: httpx.AsyncClient | None = None) -> TrackLyrics:
    """Looks a track's lyrics up (file first, then LRCLIB when [online]) and stores the result.

    A network error is not stored as a miss, so the next try asks again.
    """
    text: str | None = None
    source: str | None = None
    abs_path = Path(get_settings().library.music_dir) / track.file_path
    if abs_path.exists():
        found = await asyncio.to_thread(from_file, abs_path)
        if found:
            text, source = found
    if text is None and online and track.title and track.artist:
        own = client is None
        c = client or httpx.AsyncClient(timeout=10, headers={"User-Agent": USER_AGENT})
        try:
            text = await from_lrclib(c, track.artist.name, track.title,
                                     track.album.name if track.album else None, track.duration_seconds)
            source = "lrclib" if text else None
        finally:
            if own:
                await c.aclose()
    row = await db.get(TrackLyrics, track.id) or TrackLyrics(track_id=track.id, status="none")
    if text:
        lines, synced = to_lines(text)
        row.status = "found" if lines else "none"
        row.synced = synced
        row.lines = json.dumps(lines)
        row.source = source
    else:
        row.status = "none"
        row.synced = False
        row.lines = None
        row.source = None
    row.checked_at = datetime.utcnow()
    db.add(row)
    await db.commit()
    return row


async def get_or_find(db: AsyncSession, track_id: str, online: bool) -> dict:
    """The track's lyrics, looked up now if they never were (or a miss has gone stale)."""
    row = await db.get(TrackLyrics, track_id)
    if row is not None and not _stale(row):
        return payload(row)
    track = (await db.execute(
        select(Track).options(selectinload(Track.artist), selectinload(Track.album)).where(Track.id == track_id)
    )).scalar_one_or_none()
    if track is None:
        return {"status": "failed", "error": "unknown track", "synced": False, "lines": []}
    try:
        row = await find(db, track, online)
    except Exception as e:
        log.warning("lyrics lookup for %s failed: %s", track_id, e)
        return {"status": "failed", "error": str(e)[:200], "synced": False, "lines": []}
    return payload(row)


async def fetch_batch(db: AsyncSession, limit: int, online: bool) -> dict:
    """The scheduled task: looks up lyrics for up to [limit] tracks that have none on record
    (or a stale miss), most recently played first, pacing the LRCLIB calls."""
    checked = select(TrackLyrics.track_id).where(
        (TrackLyrics.status == "found") | (TrackLyrics.checked_at >= datetime.utcnow() - timedelta(days=RETRY_DAYS))
    )
    tracks = (await db.execute(
        select(Track).options(selectinload(Track.artist), selectinload(Track.album))
        .where(Track.id.notin_(checked))
        .order_by(Track.last_played_at.desc().nullslast(), Track.created_at.desc())
        .limit(limit)
    )).scalars().all()
    found = timed = missing = failed = 0
    errors: list[str] = []
    async with httpx.AsyncClient(timeout=10, headers={"User-Agent": USER_AGENT}) as client:
        for t in tracks:
            try:
                row = await find(db, t, online, client)
                if row.status == "found":
                    found += 1
                    timed += 1 if row.synced else 0
                else:
                    missing += 1
            except Exception as e:
                failed += 1
                errors.append(f"{t.title}: {e}"[:120])
                await db.rollback()
                if failed >= 15 and found == 0:
                    log.warning("lyrics: stopping after %d failures in a row", failed)
                    break
            if online:
                # Gentle on a free service.
                await asyncio.sleep(0.4)
    return {"checked": len(tracks), "found": found, "timed": timed, "none": missing,
            "failed": failed, "errors": errors[:5]}
