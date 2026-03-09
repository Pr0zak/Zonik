"""Natural language search — interpret plain English queries into structured filters."""
from __future__ import annotations

import json
import logging
import re

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.config import get_settings
from backend.models.track import Track
from backend.models.artist import Artist
from backend.models.album import Album
from backend.models.analysis import TrackAnalysis
from backend.services.ai.client import call_claude

log = logging.getLogger(__name__)

# Simple heuristic patterns that suggest natural language (not a title/artist search)
NL_PATTERNS = [
    r"\b(find|show|get|give|play)\b.*\b(me|some|all)\b",
    r"\b(chill|upbeat|energetic|mellow|dark|happy|sad|relaxing|ambient)\b.*\b(track|song|music)\b",
    r"\bfrom\s+(last|this)\s+(week|month|year)\b",
    r"\b(similar|like)\s+\w+",
    r"\b(high|low)\s+(quality|bitrate|energy|bpm)\b",
    r"\b(more|less)\s+than\s+\d+",
    r"\b(recently|never)\s+(added|played)\b",
    r"\b(top|best|most)\s+(played|rated|popular)\b",
]


def detect_nl_query(query: str) -> bool:
    """Return True if the query looks like natural language rather than title/artist search."""
    q = query.strip().lower()
    if len(q) < 8:
        return False
    for pattern in NL_PATTERNS:
        if re.search(pattern, q, re.IGNORECASE):
            return True
    # If it has more than 4 words and doesn't look like "Artist - Title"
    if len(q.split()) > 4 and " - " not in q:
        return True
    return False


async def interpret_query(query: str) -> dict:
    """Use Claude to interpret a natural language query into structured filters.

    Returns dict with keys like:
      genre, artist, min_bpm, max_bpm, min_bitrate, format, sort_by, limit,
      mood, time_period, query_type ("filter" or "semantic")
    """
    settings = get_settings()
    if not settings.assistant.ai_search:
        return {"error": "AI search is disabled"}

    prompt = f"""Interpret this music library search query into structured filters.

Query: "{query}"

Return valid JSON with applicable fields (omit fields that don't apply):
{{
  "genre": "genre name or null",
  "artist": "artist name or null",
  "mood": "mood keyword or null",
  "min_bpm": number or null,
  "max_bpm": number or null,
  "min_bitrate": number or null (in kbps),
  "format": "flac/mp3/etc or null",
  "sort_by": "play_count/rating/created_at/title or null",
  "sort_dir": "asc/desc",
  "limit": number (default 50),
  "time_period": "7d/30d/90d/all or null",
  "search_text": "fallback text search if no structured filters apply"
}}

Be precise. Only include fields that the query clearly implies."""

    result = await call_claude(
        prompt,
        max_tokens=512,
        temperature=0.1,
    )

    if "error" in result:
        return result

    parsed = result.get("parsed")
    if not parsed:
        return {"search_text": query}

    return parsed


async def search_with_filters(db: AsyncSession, filters: dict, limit: int = 50) -> list[dict]:
    """Execute a structured search against the library using interpreted filters."""
    query = select(Track).options(selectinload(Track.artist), selectinload(Track.album))
    conditions = []

    if filters.get("genre"):
        conditions.append(func.lower(Track.genre) == filters["genre"].lower())

    if filters.get("artist"):
        query = query.join(Artist, Track.artist_id == Artist.id, isouter=True)
        conditions.append(func.lower(Artist.name).contains(filters["artist"].lower()))

    if filters.get("min_bpm") or filters.get("max_bpm"):
        query = query.outerjoin(TrackAnalysis, Track.id == TrackAnalysis.track_id)
        if filters.get("min_bpm"):
            conditions.append(TrackAnalysis.bpm >= filters["min_bpm"])
        if filters.get("max_bpm"):
            conditions.append(TrackAnalysis.bpm <= filters["max_bpm"])

    if filters.get("min_bitrate"):
        conditions.append(Track.bitrate >= filters["min_bitrate"] * 1000)

    if filters.get("format"):
        conditions.append(func.lower(Track.format) == filters["format"].lower())

    if filters.get("time_period"):
        from datetime import datetime, timedelta, timezone
        period_map = {"7d": 7, "30d": 30, "90d": 90}
        days = period_map.get(filters["time_period"])
        if days:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            conditions.append(Track.created_at >= cutoff)

    if conditions:
        query = query.where(and_(*conditions))

    # Sort
    sort_by = filters.get("sort_by", "created_at")
    sort_dir = filters.get("sort_dir", "desc")
    sort_col = getattr(Track, sort_by, Track.created_at)
    if sort_dir == "asc":
        query = query.order_by(sort_col.asc())
    else:
        query = query.order_by(sort_col.desc())

    # Fallback text search
    if not conditions and filters.get("search_text"):
        text = filters["search_text"]
        query = query.where(
            or_(
                Track.title.ilike(f"%{text}%"),
                Track.genre.ilike(f"%{text}%"),
            )
        )

    use_limit = min(filters.get("limit", limit), 200)
    query = query.limit(use_limit)

    result = await db.execute(query)
    tracks = result.scalars().all()

    return [
        {
            "id": t.id,
            "title": t.title,
            "artist": t.artist.name if t.artist else None,
            "album": t.album.title if t.album else None,
            "genre": t.genre,
            "format": t.format,
            "bitrate": t.bitrate,
            "duration": t.duration_seconds,
            "play_count": t.play_count,
            "rating": t.rating,
            "file_path": t.file_path,
            "cover_art": t.album_id or t.id,
        }
        for t in tracks
    ]
