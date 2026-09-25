"""Turn a vague description into specific songs, then find them in the catalog.

"the song from the Drive soundtrack", "that one that goes 'take me home
tonight'", "sea shanties like Wellerman" — a catalog search can't answer
these; Claude can name candidate songs, and the catalog then supplies clean
metadata, cover art and a preview for each. Uses the fast model: this sits on
the search path, and naming a handful of songs doesn't need a large one.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict

from backend.config import get_settings
from backend.services.ai.client import call_claude

log = logging.getLogger(__name__)

_SYSTEM = (
    "You identify songs for a music search. Given what someone typed or said, "
    "name the real, released songs they most likely mean — or, for a mood or "
    "style request, songs that fit it well. Only name songs you are confident "
    "exist, with the artist as credited on the release. Put the most likely "
    "match first. If nothing plausible comes to mind, return an empty list."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "artist": {"type": "string"},
                    "title": {"type": "string"},
                    "why": {"type": "string", "description": "A few words on why it matches"},
                },
                "required": ["artist", "title", "why"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["candidates"],
    "additionalProperties": False,
}

_CACHE_TTL_S = 3600.0
_CACHE_MAX = 128
_cache: OrderedDict[tuple[str, int], tuple[float, list[dict]]] = OrderedDict()


def enabled() -> bool:
    a = get_settings().assistant
    return bool(a.enabled and a.ai_track_resolver and a.claude_api_key)


async def candidates(query: str, limit: int = 5) -> list[dict]:
    """[{artist, title, why}] from Claude, cached for an hour. [] on any failure."""
    q = " ".join(query.split())
    key = (q.lower(), limit)
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < _CACHE_TTL_S:
        return hit[1]

    settings = get_settings().assistant
    result = await call_claude(
        f"Search: {q}\n\nName up to {limit} songs.",
        system=_SYSTEM,
        max_tokens=600,
        model=settings.claude_fast_model,
        feature="track_resolver",
        output_schema=_SCHEMA,
    )
    if "error" in result:
        log.info("Track resolver failed for %r: %s", q, result["error"])
        return []
    parsed = result.get("parsed")
    raw = parsed.get("candidates", []) if isinstance(parsed, dict) else []
    out = [
        {"artist": c["artist"].strip(), "title": c["title"].strip(), "why": (c.get("why") or "").strip()}
        for c in raw
        if isinstance(c, dict) and str(c.get("artist", "")).strip() and str(c.get("title", "")).strip()
    ][:limit]
    _cache[key] = (time.monotonic(), out)
    _cache.move_to_end(key)
    while len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)
    return out


async def resolve(query: str, limit: int = 5) -> list[dict]:
    """Catalog tracks for Claude's candidates, marked suggested_by="ai".

    Each candidate is looked up in the catalog; a hit with the same title and a
    shared credited artist supplies album, cover and preview. Candidates the
    catalog can't confirm are dropped — small models do invent songs — unless
    the catalog itself is unreachable.
    """
    from backend.services.catalog import _deezer_search
    from backend.services.library_match import artists_overlap, norm_artist, norm_title

    cands = await candidates(query, limit)

    async def lookup(c: dict) -> dict | None:
        base = {
            "title": c["title"], "artist": c["artist"], "album": None, "duration": None,
            "cover_url": None, "preview_url": None, "explicit": False,
            "source": "ai", "source_id": None,
        }
        try:
            hits = await _deezer_search(f"{c['artist']} {c['title']}", 5)
        except Exception as e:
            # Catalog unreachable: can't verify, so pass the suggestion through.
            log.debug("Resolver lookup failed for %s - %s: %s", c["artist"], c["title"], e)
            return {**base, "suggested_by": "ai", "reason": c["why"]}
        # Same title and a shared credited artist. Anything else means the
        # model named a song the catalog doesn't know — usually an invented
        # one — so it is dropped rather than offered for download.
        want_title = norm_title(c["title"])
        match = next(
            (h for h in hits if norm_title(h["title"]) == want_title and artists_overlap(h["artist"], c["artist"])),
            None,
        )
        if not match:
            log.info("Resolver: dropped unverified %s - %s", c["artist"], c["title"])
            return None
        return {**base, **match, "suggested_by": "ai", "reason": c["why"]}

    found = [t for t in await asyncio.gather(*(lookup(c) for c in cands)) if t]
    # Two candidates can land on the same catalog song.
    seen: set[tuple[str, str]] = set()
    out = []
    for t in found:
        key = (norm_artist(t["artist"]), norm_title(t["title"]))
        if key not in seen:
            seen.add(key)
            out.append(t)
    return out
