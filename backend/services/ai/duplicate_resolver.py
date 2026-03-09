"""AI duplicate resolver — recommend which duplicate to keep."""
from __future__ import annotations

import json
import logging

from backend.config import get_settings
from backend.services.ai.client import call_claude

log = logging.getLogger(__name__)


async def resolve_duplicates(groups: list[dict]) -> dict:
    """Analyze duplicate groups and recommend which tracks to keep.

    groups: list of group dicts with tracks (from find_duplicates_enriched)
    Returns {"recommendations": [{group_key, keep_id, remove_ids, reason}]}
    """
    settings = get_settings()
    if not settings.assistant.ai_duplicate_resolver:
        return {"error": "AI duplicate resolver is disabled"}

    # Format groups for Claude
    formatted = []
    for g in groups[:20]:  # Limit to 20 groups per call
        tracks_info = []
        for t in g.get("tracks", []):
            tracks_info.append({
                "id": t.get("id"),
                "format": t.get("format"),
                "bitrate": t.get("bitrate"),
                "file_size": t.get("file_size"),
                "quality_score": t.get("quality_score"),
                "play_count": t.get("play_count", 0),
                "rating": t.get("rating"),
                "is_favorite": t.get("is_favorite", False),
                "is_best": t.get("is_best", False),
            })
        formatted.append({
            "artist": g.get("artist"),
            "title": g.get("title"),
            "count": g.get("count"),
            "tracks": tracks_info,
        })

    prompt = f"""You are a music library curator. For each duplicate group, recommend which track to keep.

Consider: audio quality (format, bitrate), file size, play count, rating, favorites.
FLAC > WAV > ALAC > AIFF > M4A > OGG/OPUS > MP3 > AAC > WMA

Duplicate groups:
{json.dumps(formatted, indent=2)}

For each group, recommend which track ID to keep and which to remove.

Return JSON:
[
  {{
    "artist": "...",
    "title": "...",
    "keep_id": "track_id_to_keep",
    "remove_ids": ["id1", "id2"],
    "reason": "brief reason"
  }},
  ...
]"""

    result = await call_claude(prompt, max_tokens=2048, temperature=0.2)
    if "error" in result:
        return result

    parsed = result.get("parsed")
    if not parsed:
        return {"error": "Failed to parse AI response"}

    recommendations = parsed if isinstance(parsed, list) else parsed.get("recommendations", [])
    return {"recommendations": recommendations}
