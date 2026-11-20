"""The Lyrics section: how many tracks have lyrics, a searchable list, each track's lyrics,
looking one up again, and lyrics typed or pasted in by hand (see backend/services/lyrics.py)."""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.models.artist import Artist
from backend.models.lyrics import TrackLyrics
from backend.models.track import Track
from backend.services import lyrics as lyrics_service

router = APIRouter()


async def online_allowed(db: AsyncSession) -> bool:
    """Whether looking lyrics up on LRCLIB is allowed (the `lyrics_online` setting)."""
    from backend.api.tv_visualizer import _load, _payload
    return bool(_payload(await _load(db))["config"].get("lyrics_online", True))


@router.get("/stats")
async def stats(db: AsyncSession = Depends(get_db)):
    total = (await db.execute(select(func.count(Track.id)))).scalar() or 0
    rows = (await db.execute(
        select(TrackLyrics.status, TrackLyrics.synced, TrackLyrics.source, func.count())
        .group_by(TrackLyrics.status, TrackLyrics.synced, TrackLyrics.source)
    )).all()
    found = timed = none = 0
    by_source: dict[str, int] = {}
    for status, synced, source, n in rows:
        if status == "found":
            found += n
            timed += n if synced else 0
            by_source[source or "unknown"] = by_source.get(source or "unknown", 0) + n
        else:
            none += n
    return {
        "tracks": total, "found": found, "timed": timed, "plain": found - timed,
        "none": none, "unchecked": max(total - found - none, 0), "by_source": by_source,
        "online": await online_allowed(db),
    }


@router.get("/tracks")
async def tracks(q: str = "", status: str = "all", limit: int = 50, offset: int = 0,
                 db: AsyncSession = Depends(get_db)):
    """Tracks with their lyrics status. status: all, timed, plain, none, unchecked."""
    query = (select(Track, TrackLyrics)
             .options(selectinload(Track.artist), selectinload(Track.album))
             .outerjoin(TrackLyrics, TrackLyrics.track_id == Track.id))
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.outerjoin(Artist, Artist.id == Track.artist_id).where(or_(Track.title.ilike(like), Artist.name.ilike(like)))
    if status == "timed":
        query = query.where(TrackLyrics.status == "found", TrackLyrics.synced.is_(True))
    elif status == "plain":
        query = query.where(TrackLyrics.status == "found", TrackLyrics.synced.is_(False))
    elif status == "none":
        query = query.where(TrackLyrics.status == "none")
    elif status == "unchecked":
        query = query.where(TrackLyrics.track_id.is_(None))
    count = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    rows = (await db.execute(
        query.order_by(Track.last_played_at.desc().nullslast(), Track.title).limit(min(limit, 200)).offset(offset)
    )).all()
    items = []
    for t, ly in rows:
        items.append({
            "id": t.id, "title": t.title,
            "artist": t.artist.name if t.artist else None,
            "album": t.album.name if t.album else None,
            "album_id": t.album_id,
            "status": ly.status if ly else "unchecked",
            "synced": bool(ly.synced) if ly else False,
            "source": ly.source if ly else None,
            "checked_at": ly.checked_at.isoformat() if ly and ly.checked_at else None,
        })
    return {"total": count, "items": items}


@router.get("/track/{track_id}")
async def track_lyrics(track_id: str, db: AsyncSession = Depends(get_db)):
    """A track's lyrics as stored (not looked up)."""
    t = (await db.execute(
        select(Track).options(selectinload(Track.artist), selectinload(Track.album)).where(Track.id == track_id)
    )).scalar_one_or_none()
    if t is None:
        raise HTTPException(404, "Unknown track")
    row = await db.get(TrackLyrics, track_id)
    out = lyrics_service.payload(row) if row else {"status": "unchecked", "synced": False, "lines": []}
    out.update({"id": t.id, "title": t.title, "artist": t.artist.name if t.artist else None,
                "album": t.album.name if t.album else None, "duration": t.duration_seconds,
                "checked_at": row.checked_at.isoformat() if row and row.checked_at else None})
    return out


@router.post("/track/{track_id}/fetch")
async def fetch(track_id: str, db: AsyncSession = Depends(get_db)):
    """Looks the track's lyrics up again now (file first, then LRCLIB if allowed)."""
    t = (await db.execute(
        select(Track).options(selectinload(Track.artist), selectinload(Track.album)).where(Track.id == track_id)
    )).scalar_one_or_none()
    if t is None:
        raise HTTPException(404, "Unknown track")
    try:
        row = await lyrics_service.find(db, t, await online_allowed(db))
    except Exception as e:
        raise HTTPException(502, f"Lookup failed: {e}") from e
    return lyrics_service.payload(row)


class LyricsEdit(BaseModel):
    # Plain lines, or LRC with [mm:ss.xx] timestamps; empty clears the lyrics.
    text: str


@router.put("/track/{track_id}")
async def edit(track_id: str, body: LyricsEdit, db: AsyncSession = Depends(get_db)):
    """Lyrics typed or pasted in by hand (source `manual`)."""
    if await db.get(Track, track_id) is None:
        raise HTTPException(404, "Unknown track")
    row = await db.get(TrackLyrics, track_id) or TrackLyrics(track_id=track_id, status="none")
    lines, synced = lyrics_service.to_lines(body.text) if body.text.strip() else ([], False)
    row.status = "found" if lines else "none"
    row.synced = synced
    row.lines = json.dumps(lines) if lines else None
    row.source = "manual" if lines else None
    row.checked_at = datetime.utcnow()
    db.add(row)
    await db.commit()
    return lyrics_service.payload(row)
