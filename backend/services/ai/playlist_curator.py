"""AI playlist curator — rank discovered playlists by taste relevance."""
from __future__ import annotations

import logging

from backend.config import get_settings
from backend.services.ai.client import call_claude

_log = logging.getLogger(__name__)


async def rank_playlists(playlists: list[dict], taste_summary: str) -> list[dict]:
    """Use Claude to rank and annotate discovered playlists.

    Returns playlists with ai_score and ai_reason added.
    """
    settings = get_settings()
    if not settings.assistant.ai_playlist_curator or not settings.assistant.claude_api_key:
        return playlists

    if not playlists:
        return []

    # Format playlists for Claude
    pl_text = "\n".join(
        f"{i+1}. \"{p.get('name', '')}\" by {p.get('owner', '')} ({p.get('track_count', 0)} tracks, {p.get('source', '')})"
        for i, p in enumerate(playlists[:20])
    )

    prompt = f"""Given this user's music taste:
{taste_summary}

Rank these playlists by how well they match the user's taste.
Return JSON array with objects: {{"index": 1, "score": 0.85, "reason": "short reason"}}

Playlists:
{pl_text}

Return ONLY the JSON array, no other text."""

    result = await call_claude(prompt, max_tokens=2048)
    if "error" in result or not result.get("parsed"):
        return playlists

    try:
        rankings = result["parsed"]
        if not isinstance(rankings, list):
            return playlists

        score_map = {r["index"]: r for r in rankings if isinstance(r, dict) and "index" in r}

        for i, p in enumerate(playlists[:20]):
            rank = score_map.get(i + 1, {})
            p["ai_score"] = rank.get("score", 0.5)
            p["ai_reason"] = rank.get("reason", "")

        # Sort by AI score
        playlists.sort(key=lambda p: p.get("ai_score", 0), reverse=True)
    except Exception as e:
        _log.warning(f"Failed to parse playlist rankings: {e}")

    return playlists


async def review_import(tracks: list[dict], taste_summary: str) -> dict:
    """Review imported playlist tracks for taste compatibility.

    Returns summary with overall_score, highlights, and per-track annotations.
    """
    settings = get_settings()
    if not settings.assistant.ai_playlist_curator or not settings.assistant.claude_api_key:
        return {"overall_score": 0.5, "summary": "AI review disabled", "tracks": []}

    # Format tracks
    track_text = "\n".join(
        f"- {t.get('artist', '')} — {t.get('title', '')}"
        for t in tracks[:30]
    )

    prompt = f"""Given this user's music taste:
{taste_summary}

Review this playlist for taste compatibility. Score each track 0-1.
Return JSON: {{"overall_score": 0.8, "summary": "brief review", "highlights": ["good track 1", "good track 2"], "tracks": [{{"index": 0, "score": 0.9, "note": "why"}}]}}

Tracks:
{track_text}

Return ONLY the JSON, no other text."""

    result = await call_claude(prompt, max_tokens=4096)
    if "error" in result or not result.get("parsed"):
        return {"overall_score": 0.5, "summary": "Review unavailable", "tracks": []}

    return result["parsed"]
