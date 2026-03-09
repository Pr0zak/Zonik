"""AI recommendation explainer — deep explanations for why a track was recommended."""
from __future__ import annotations

import logging

from backend.config import get_settings
from backend.services.ai.client import call_claude

log = logging.getLogger(__name__)


async def explain_recommendation(
    track_artist: str,
    track_title: str,
    score: float,
    source: str,
    profile_summary: dict,
) -> dict:
    """Generate a detailed explanation for why a track was recommended.

    Returns {"explanation": str, "factors": [...]} or {"error": str}
    """
    settings = get_settings()
    if not settings.assistant.ai_explanations:
        return {"error": "AI explanations are disabled"}

    genres = ", ".join(f"{g} ({int(p*100)}%)" for g, p in list(profile_summary.get("genre_distribution", {}).items())[:8])
    top_artists = ", ".join(a["name"] for a in profile_summary.get("top_artists", [])[:8])

    prompt = f"""You are a music recommendation expert. Explain why this track was recommended to this user.

Track: "{track_title}" by {track_artist}
Recommendation score: {score:.2f}
Source: {source}

User's taste profile:
- Top genres: {genres}
- Most played artists: {top_artists}
- Audio preferences: BPM {profile_summary.get('audio', {}).get('avg_bpm', 'N/A')}

Write a concise, engaging 2-3 sentence explanation of why this track fits the user's taste.
Then list 2-4 specific factors as bullet points.

Return JSON:
{{
  "explanation": "...",
  "factors": ["factor 1", "factor 2", ...]
}}"""

    result = await call_claude(prompt, max_tokens=512, temperature=0.5)
    if "error" in result:
        return result

    parsed = result.get("parsed")
    if parsed:
        return parsed

    # Fallback: return raw text
    return {"explanation": result.get("text", "Unable to generate explanation"), "factors": []}
