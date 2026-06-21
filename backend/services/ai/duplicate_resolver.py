"""AI duplicate resolver — recommend which duplicate to keep."""
from __future__ import annotations

import asyncio
import json
import logging

from backend.config import get_settings
from backend.services.ai.client import call_claude

log = logging.getLogger(__name__)

# Groups per Claude call. Output is ~1 small JSON object per group, so this stays
# well under max_tokens (the old code sent 20 groups at max_tokens=2048 and the
# response truncated → unparseable → "Failed to parse AI response").
_CHUNK = 30
# Safety cap on total groups resolved in one request (~ _MAX_GROUPS / _CHUNK calls).
_MAX_GROUPS = 600


def _format_group(g: dict) -> dict:
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
    return {
        "artist": g.get("artist"),
        "title": g.get("title"),
        "count": g.get("count"),
        "tracks": tracks_info,
    }


async def _resolve_chunk(groups: list[dict]) -> list[dict]:
    """Resolve one chunk of duplicate groups. Returns [] on any failure so a
    single bad chunk never sinks the whole request."""
    formatted = [_format_group(g) for g in groups]
    prompt = f"""For each duplicate group, recommend which track to keep and which to remove.

Consider audio quality (format, bitrate), file size, play count, rating, favorites.
Quality order: FLAC > WAV > ALAC > AIFF > M4A > OGG/OPUS > MP3 > AAC > WMA.
Prefer keeping a favorited or frequently-played copy when quality is comparable.

Duplicate groups:
{json.dumps(formatted)}

Return ONLY a JSON array (no prose, no markdown):
[{{"artist":"...","title":"...","keep_id":"id","remove_ids":["id"],"reason":"brief"}}]"""

    result = await call_claude(
        prompt,
        system="You are a music library curator. Respond with ONLY a valid JSON array — no prose, no markdown code fences.",
        max_tokens=8192,
        temperature=0.2,
    )
    if "error" in result:
        log.warning("[dup-resolve] chunk failed: %s", result["error"])
        return []
    parsed = result.get("parsed")
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        return parsed.get("recommendations", []) or []
    log.warning(
        "[dup-resolve] chunk unparseable (out_tokens=%s)",
        result.get("usage", {}).get("output_tokens"),
    )
    return []


async def resolve_duplicates(groups: list[dict]) -> dict:
    """Analyze duplicate groups and recommend which tracks to keep.

    groups: list of group dicts with tracks (from find_duplicates_enriched)
    Returns {"recommendations": [{artist, title, keep_id, remove_ids, reason}]}.
    Processes all groups in bounded, concurrent chunks (call_claude's own
    semaphore caps real concurrency) so large libraries don't truncate.
    """
    settings = get_settings()
    if not settings.assistant.ai_duplicate_resolver:
        return {"error": "AI duplicate resolver is disabled"}
    if not groups:
        return {"recommendations": []}

    work = groups[:_MAX_GROUPS]
    chunks = [work[i:i + _CHUNK] for i in range(0, len(work), _CHUNK)]

    chunk_results = await asyncio.gather(*[_resolve_chunk(c) for c in chunks])
    recommendations = [rec for chunk in chunk_results for rec in chunk]

    out: dict = {"recommendations": recommendations}
    if len(groups) > _MAX_GROUPS:
        out["note"] = f"Resolved the first {_MAX_GROUPS} of {len(groups)} groups."
    if not recommendations:
        return {"error": "The AI couldn't produce recommendations — try again."}
    log.info("[dup-resolve] %d groups -> %d recommendations", len(work), len(recommendations))
    return out
