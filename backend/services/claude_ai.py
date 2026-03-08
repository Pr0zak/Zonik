"""Claude API integration for AI Music Assistant re-ranking."""
from __future__ import annotations

import json
import logging

from backend.config import get_settings
from backend.services.ai.client import call_claude

log = logging.getLogger(__name__)


def build_prompt(profile: dict, candidates: list[dict]) -> str:
    """Build the Claude prompt from taste profile and pre-scored candidates."""
    genre_dist = profile.get("genre_distribution", {})
    top_genres = ", ".join(f"{g} ({int(p*100)}%)" for g, p in list(genre_dist.items())[:10])

    top_artists = ", ".join(a["name"] for a in profile.get("top_artists", [])[:10])
    fav_artists = ", ".join(profile.get("favorite_artists", [])[:10])

    audio = profile.get("audio", {})
    audio_str = ""
    if audio.get("avg_bpm"):
        audio_str += f"BPM: {audio['avg_bpm']}"
        if audio.get("bpm_std"):
            audio_str += f" +/- {audio['bpm_std']}"
    if audio.get("avg_energy") is not None:
        audio_str += f", Energy: {audio['avg_energy']:.0%}"
    if audio.get("avg_danceability") is not None:
        audio_str += f", Danceability: {audio['avg_danceability']:.0%}"

    # Format candidates as compact JSON
    candidate_list = []
    for c in candidates:
        candidate_list.append({
            "artist": c["artist"],
            "track": c["track"],
            "score": c.get("score", 0),
            "source": c.get("source", ""),
            "listeners": c.get("lastfm_listeners", 0),
        })

    return f"""You are a music recommendation expert. Analyze this user's taste profile and re-rank the candidate tracks.

Music taste profile:
- Top genres: {top_genres}
- Most played artists: {top_artists}
- Favorite artists: {fav_artists}
- Audio preferences: {audio_str or 'No analysis data'}

Current candidates (pre-scored by rule engine):
{json.dumps(candidate_list, indent=2)}

Instructions:
1. Re-rank the top 20 candidates by how well they fit this user's taste
2. Write a 1-sentence explanation for each pick
3. Suggest up to 5 additional tracks NOT in the candidates that would fit this profile perfectly
4. Flag any candidates that are poor fits (explain why)

Return valid JSON with this exact structure:
{{
  "ranked": [
    {{"artist": "...", "track": "...", "score": 0.0-1.0, "explanation": "..."}},
    ...
  ],
  "additional": [
    {{"artist": "...", "track": "...", "score": 0.0-1.0, "explanation": "..."}},
    ...
  ],
  "flagged": [
    {{"artist": "...", "track": "...", "reason": "..."}},
    ...
  ]
}}"""


async def rerank_with_claude(
    profile: dict,
    candidates: list[dict],
) -> dict:
    """Send candidates to Claude for re-ranking. Returns parsed response or error."""
    settings = get_settings()
    if not settings.assistant.ai_reranking:
        return {"error": "AI re-ranking is disabled"}

    prompt = build_prompt(profile, candidates)
    result = await call_claude(prompt, max_tokens=4096)

    if "error" in result:
        return result

    parsed = result.get("parsed")
    if not parsed:
        return {"error": "Failed to parse Claude response", "raw": result.get("text", "")[:500]}

    # Add usage info
    parsed["usage"] = result.get("usage", {})
    return parsed
