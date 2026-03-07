"""Claude API integration for AI Music Assistant re-ranking."""
from __future__ import annotations

import json
import logging

import httpx

from backend.config import get_settings

log = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"


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


def parse_response(text: str) -> dict | None:
    """Parse Claude's response, handling code blocks and malformed JSON."""
    # Try to extract JSON from code blocks
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start)
        text = text[start:end].strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in text
    for i, ch in enumerate(text):
        if ch == '{':
            # Find matching closing brace
            depth = 0
            for j in range(i, len(text)):
                if text[j] == '{':
                    depth += 1
                elif text[j] == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[i:j+1])
                        except json.JSONDecodeError:
                            break
            break

    log.warning("Failed to parse Claude response as JSON")
    return None


async def rerank_with_claude(
    profile: dict,
    candidates: list[dict],
) -> dict:
    """Send candidates to Claude for re-ranking. Returns parsed response or error."""
    settings = get_settings()
    api_key = settings.assistant.claude_api_key
    model = settings.assistant.claude_model

    if not api_key:
        return {"error": "No Claude API key configured"}

    prompt = build_prompt(profile, candidates)

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            resp = await client.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 4096,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )

            if resp.status_code != 200:
                error_body = resp.text[:500]
                log.error(f"Claude API error {resp.status_code}: {error_body}")
                return {"error": f"Claude API returned {resp.status_code}"}

            data = resp.json()
            content = data.get("content", [])
            if not content:
                return {"error": "Empty response from Claude"}

            text = content[0].get("text", "")
            usage = data.get("usage", {})

            parsed = parse_response(text)
            if not parsed:
                return {"error": "Failed to parse Claude response", "raw": text[:500]}

            # Add usage info
            parsed["usage"] = {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
            }

            return parsed

        except httpx.TimeoutException:
            return {"error": "Claude API request timed out"}
        except Exception as e:
            log.error(f"Claude API error: {e}")
            return {"error": str(e)}
