"""AI listening insights — weekly summary on Dashboard."""
from __future__ import annotations

import json
import logging
import time

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.models.track import Track
from backend.models.artist import Artist
from backend.models.play_history import PlayHistory
from backend.services.ai.client import call_claude

log = logging.getLogger(__name__)

# In-memory cache (24h TTL)
_insights_cache: dict | None = None
_insights_cache_time: float = 0
_INSIGHTS_CACHE_TTL = 86400  # 24 hours


async def generate_insights(db: AsyncSession) -> dict:
    """Generate AI listening insights based on recent play history.

    Returns {"summary": str, "highlights": [...], "trends": [...]} or {"error": str}
    """
    global _insights_cache, _insights_cache_time

    settings = get_settings()
    if not settings.assistant.ai_insights:
        return {"error": "AI insights are disabled"}

    # Check cache
    now = time.time()
    if _insights_cache and now - _insights_cache_time < _INSIGHTS_CACHE_TTL:
        return _insights_cache

    from datetime import datetime, timedelta, timezone
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    # Get recent play data
    play_result = await db.execute(
        select(
            Track.title,
            Artist.name.label("artist"),
            Track.genre,
            func.count(PlayHistory.id).label("plays"),
        )
        .join(Track, PlayHistory.track_id == Track.id)
        .join(Artist, Track.artist_id == Artist.id, isouter=True)
        .where(PlayHistory.played_at >= week_ago)
        .group_by(Track.id, Track.title, Artist.name, Track.genre)
        .order_by(func.count(PlayHistory.id).desc())
        .limit(20)
    )
    recent_plays = [
        {"title": r.title, "artist": r.artist or "Unknown", "genre": r.genre, "plays": r.plays}
        for r in play_result.all()
    ]

    total_plays = await db.execute(
        select(func.count(PlayHistory.id)).where(PlayHistory.played_at >= week_ago)
    )
    play_count = total_plays.scalar() or 0

    if play_count == 0:
        return {"summary": "No listening activity this week.", "highlights": [], "trends": []}

    # Genre breakdown
    genre_result = await db.execute(
        select(Track.genre, func.count(PlayHistory.id).label("plays"))
        .join(Track, PlayHistory.track_id == Track.id)
        .where(PlayHistory.played_at >= week_ago, Track.genre.isnot(None))
        .group_by(Track.genre)
        .order_by(func.count(PlayHistory.id).desc())
        .limit(10)
    )
    genres = [{"genre": r.genre, "plays": r.plays} for r in genre_result.all()]

    prompt = f"""You are a music listening analyst. Summarize this user's listening week.

This week's stats:
- Total plays: {play_count}
- Top tracks: {json.dumps(recent_plays[:10])}
- Genre breakdown: {json.dumps(genres)}

Write a brief, engaging summary (2-3 sentences) of their listening patterns.
Include 3-4 highlights and any notable trends.

Return JSON:
{{
  "summary": "...",
  "highlights": ["highlight 1", "highlight 2", ...],
  "trends": ["trend 1", ...]
}}"""

    result = await call_claude(prompt, max_tokens=512, temperature=0.6)
    if "error" in result:
        return result

    parsed = result.get("parsed", {})
    if not parsed:
        parsed = {"summary": "Unable to generate insights.", "highlights": [], "trends": []}

    parsed["play_count"] = play_count
    parsed["top_genre"] = genres[0]["genre"] if genres else None

    # Cache result
    _insights_cache = parsed
    _insights_cache_time = now

    return parsed
