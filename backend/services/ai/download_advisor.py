"""AI download advisor — rank Soulseek search results for best quality pick."""
from __future__ import annotations

import json
import logging

from backend.config import get_settings
from backend.services.ai.client import call_claude

log = logging.getLogger(__name__)


async def rank_search_results(
    artist: str,
    track: str,
    results: list[dict],
) -> dict:
    """Rank Soulseek search results by quality and relevance.

    results: list of search result dicts with filename, size, bitrate, etc.
    Returns {"ranked": [{...result, ai_score, ai_reason}]} or {"error": str}
    """
    settings = get_settings()
    if not settings.assistant.ai_download_advisor:
        return {"error": "AI download advisor is disabled"}

    if not results:
        return {"ranked": []}

    # Format results for Claude (limit to top 15)
    formatted = []
    for i, r in enumerate(results[:15]):
        formatted.append({
            "index": i,
            "filename": r.get("filename", ""),
            "size_mb": round(r.get("size", 0) / 1024 / 1024, 1),
            "bitrate": r.get("bitrate"),
            "format": r.get("format", ""),
            "username": r.get("username", ""),
            "speed": r.get("speed", 0),
            "queue_length": r.get("queue_length", 0),
        })

    prompt = f"""You are a music download expert. Rank these Soulseek search results for "{track}" by {artist}.

Consider:
1. File quality (FLAC > WAV > MP3 320kbps > MP3 VBR > lower bitrates)
2. Filename relevance (does it match the requested track?)
3. File size (suspicious if too small or too large)
4. Source reliability (short queue, decent speed)

Results:
{json.dumps(formatted, indent=2)}

Return JSON array of indices ranked best to worst, with a score (0-1) and brief reason:
[
  {{"index": 0, "score": 0.95, "reason": "FLAC, exact match, good source"}},
  ...
]"""

    result = await call_claude(prompt, max_tokens=1024, temperature=0.2)
    if "error" in result:
        return result

    parsed = result.get("parsed")
    if not parsed:
        return {"ranked": results}  # Fallback: return unranked

    rankings = parsed if isinstance(parsed, list) else parsed.get("ranked", [])

    # Merge AI scores back into results
    ranked = []
    for r in rankings:
        idx = r.get("index", 0)
        if 0 <= idx < len(results):
            entry = {**results[idx]}
            entry["ai_score"] = r.get("score", 0.5)
            entry["ai_reason"] = r.get("reason", "")
            entry["ai_pick"] = idx == rankings[0].get("index") if rankings else False
            ranked.append(entry)

    # Add any results not ranked by AI
    ranked_indices = {r.get("index") for r in rankings}
    for i, r in enumerate(results[:15]):
        if i not in ranked_indices:
            ranked.append({**r, "ai_score": 0, "ai_reason": "Not evaluated"})

    return {"ranked": ranked}
