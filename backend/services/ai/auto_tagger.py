"""AI auto-tagger — suggest genre tags for tracks using Claude."""
from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.config import get_settings
from backend.models.track import Track
from backend.models.artist import Artist
from backend.services.ai.client import call_claude

log = logging.getLogger(__name__)


async def suggest_tags(
    db: AsyncSession,
    track_ids: list[str],
) -> dict:
    """Suggest genre tags for a batch of tracks.

    Returns {"suggestions": [{track_id, title, artist, current_genre, suggested_genres: [...]}]}
    """
    settings = get_settings()
    if not settings.assistant.ai_auto_tagging:
        return {"error": "AI auto-tagging is disabled"}

    result = await db.execute(
        select(Track).options(selectinload(Track.artist))
        .where(Track.id.in_(track_ids))
    )
    tracks = result.scalars().all()
    if not tracks:
        return {"error": "No tracks found"}

    track_list = []
    for t in tracks:
        track_list.append({
            "id": t.id,
            "title": t.title,
            "artist": t.artist.name if t.artist else "Unknown",
            "current_genre": t.genre or "None",
            "format": t.format,
        })

    prompt = f"""You are a music genre classification expert. Suggest accurate genre tags for these tracks.

Tracks:
{json.dumps(track_list, indent=2)}

For each track, suggest 1-3 genre tags that accurately describe the music style.
Use standard genre names (Electronic, House, Techno, Ambient, Hip-Hop, Jazz, Rock, Pop, etc.)

Return JSON array:
[
  {{"id": "track_id", "suggested_genres": ["Genre1", "Genre2"]}},
  ...
]"""

    result = await call_claude(prompt, max_tokens=1024, temperature=0.3)
    if "error" in result:
        return result

    parsed = result.get("parsed")
    if not parsed:
        return {"error": "Failed to parse AI response"}

    # If parsed is a list, wrap it
    suggestions_list = parsed if isinstance(parsed, list) else parsed.get("suggestions", parsed.get("tracks", []))

    # Merge with track info
    track_map = {t["id"]: t for t in track_list}
    suggestions = []
    for s in suggestions_list:
        tid = s.get("id", "")
        if tid in track_map:
            info = track_map[tid]
            suggestions.append({
                **info,
                "suggested_genres": s.get("suggested_genres", []),
            })

    return {"suggestions": suggestions}


async def apply_tags(
    db: AsyncSession,
    tags: list[dict],
) -> dict:
    """Apply genre tags to tracks.

    tags: [{"track_id": str, "genre": str}]
    Returns {"applied": int}
    """
    applied = 0
    for tag in tags:
        track = await db.get(Track, tag["track_id"])
        if track:
            track.genre = tag["genre"]
            applied += 1

    if applied:
        await db.commit()

    return {"applied": applied}
