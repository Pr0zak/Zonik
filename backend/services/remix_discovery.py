"""Remix discovery — find remixes, dubs, edits for library tracks."""
from __future__ import annotations

import logging
import re

from backend.services import lastfm

log = logging.getLogger(__name__)

# Regex patterns for version type detection
VERSION_PATTERNS = [
    (r"\b(remix)\b", "remix"),
    (r"\b(dub\s*mix|dub)\b", "dub"),
    (r"\b(edit|re-?edit)\b", "edit"),
    (r"\b(extended\s*(mix|version)?)\b", "extended"),
    (r"\b(radio\s*(mix|edit|version)?)\b", "radio"),
    (r"\b(club\s*mix)\b", "club"),
    (r"\b(acoustic|unplugged)\b", "acoustic"),
    (r"\b(live|concert)\b", "live"),
    (r"\b(instrumental)\b", "instrumental"),
    (r"\b(vip\s*mix|vip)\b", "vip"),
    (r"\b(bootleg)\b", "bootleg"),
    (r"\b(mashup|mash-up)\b", "mashup"),
    (r"\b(rework)\b", "rework"),
    (r"\b(remaster(ed)?)\b", "remaster"),
]

# Compiled patterns
_COMPILED = [(re.compile(p, re.IGNORECASE), vtype) for p, vtype in VERSION_PATTERNS]


def detect_version_type(title: str) -> str | None:
    """Detect if a track title contains a version/remix indicator."""
    for pattern, vtype in _COMPILED:
        if pattern.search(title):
            return vtype
    return None


def _clean_title(title: str) -> str:
    """Strip version info from title to get the base track name."""
    # Remove parenthetical content like "(Remix)", "(Extended Mix)"
    cleaned = re.sub(r"\s*[\(\[].+?[\)\]]", "", title).strip()
    # Remove trailing " - Remix" style
    cleaned = re.sub(r"\s*-\s*(remix|dub|edit|extended|radio|club|live|acoustic|instrumental|vip|bootleg|mashup|rework|remaster(ed)?).*$", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned if cleaned else title


async def find_remixes(
    artist: str,
    track: str,
    limit: int = 30,
) -> list[dict]:
    """Search Last.fm for remixes/versions of a track."""
    base_title = _clean_title(track)
    results = []
    seen = set()

    # Strategy 1: Search "artist track remix"
    search_queries = [
        f"{artist} {base_title} remix",
        f"{artist} {base_title} mix",
        f"{base_title} remix",
    ]

    for query in search_queries:
        try:
            tracks = await lastfm.search_tracks(query, limit=limit)
            for t in tracks:
                key = (t["artist"].lower(), t["name"].lower())
                if key in seen:
                    continue
                seen.add(key)

                version_type = detect_version_type(t["name"])
                if not version_type:
                    # Skip if it doesn't look like a remix/version
                    continue

                results.append({
                    "name": t["name"],
                    "artist": t["artist"],
                    "version_type": version_type,
                    "listeners": t.get("listeners", 0),
                })
        except Exception as e:
            log.debug("Remix search error for '%s': %s", query, e)

    # Sort by listeners descending
    results.sort(key=lambda x: x.get("listeners", 0), reverse=True)
    return results[:limit]
