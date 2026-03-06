"""Multi-strategy search + quality scoring — uses native SoulseekClient."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from backend.config import get_settings
from backend.services.soulseek import (
    normalize_text, words_match, strip_track_extras, clean_track_name,
    clean_artist_name, PREFERRED_EXTENSIONS,
)

if TYPE_CHECKING:
    from backend.soulseek.client import SoulseekClient

log = logging.getLogger(__name__)


async def pick_best_results_native(
    results: list,  # list of SearchResult
    artist: str,
    track: str,
    reputation=None,
) -> list[dict]:
    """Score and rank search results from native client. Returns flat file list."""
    settings = get_settings()
    min_size = settings.soulseek.min_file_size_mb * 1024 * 1024

    # Pre-filter: exclude blocked peers
    blocked_users: set[str] = set()
    if reputation:
        for search_result in results:
            if await reputation.is_blocked(search_result.username):
                blocked_users.add(search_result.username)

    scored = []
    for search_result in results:
        if search_result.username in blocked_users:
            continue
        for file_info in search_result.files:
            filename = file_info.filename
            size = file_info.size

            if size < min_size:
                continue

            ext = ""
            for e in PREFERRED_EXTENSIONS:
                if filename.lower().endswith(e):
                    ext = e
                    break
            if not ext:
                continue

            score = 0
            # Fuzzy artist match
            if words_match(artist, filename):
                score += 10
            # Fuzzy track match
            if words_match(track, filename):
                score += 10
            elif words_match(strip_track_extras(track), filename):
                score += 8

            # Format scoring
            if ext == ".flac":
                score += 20
            elif ext in (".wav", ".alac"):
                score += 18
            elif ext == ".mp3":
                score += 5
            elif ext in (".m4a", ".ogg", ".opus"):
                score += 3

            # Size scoring
            if size > 30 * 1024 * 1024:
                score += 8
            elif size > 15 * 1024 * 1024:
                score += 5
            elif size > 8 * 1024 * 1024:
                score += 3

            # Bitrate scoring
            bitrate = file_info.bitrate
            if bitrate >= 320:
                score += 5
            elif bitrate >= 256:
                score += 3

            # Peer quality (heavily weighted — available peers matter most)
            if search_result.slots_free:
                score += 10
            else:
                score -= 5  # penalize peers with no free slots
            if search_result.avg_speed > 1000000:  # >1MB/s
                score += 8
            elif search_result.avg_speed > 500000:  # >500KB/s
                score += 4

            # Reputation: boost successful sources, penalize unreliable ones
            if reputation:
                score += await reputation.get_score_adjustment(search_result.username)

            if score > 0:
                scored.append((score, {
                    "username": search_result.username,
                    "filename": filename,
                    "size": size,
                    "bitRate": bitrate,
                    "slots_free": search_result.slots_free,
                    "avg_speed": search_result.avg_speed,
                }))

    if not scored:
        return []

    scored.sort(key=lambda x: x[0], reverse=True)

    # Deduplicate by user (one result per peer)
    seen_users: set[str] = set()
    candidates = []
    for _score, r in scored:
        user = r["username"]
        if user not in seen_users:
            seen_users.add(user)
            candidates.append(r)
        if len(candidates) >= 5:
            break
    return candidates


async def search_multi_strategy_native(
    client: "SoulseekClient",
    artist: str,
    track: str,
) -> list[dict]:
    """Try multiple search strategies using native client. Returns best candidates."""
    queries = [f"{artist} {track}"]
    cleaned_track = strip_track_extras(track)
    cleaned_artist = clean_artist_name(artist)
    q2 = f"{cleaned_artist} {cleaned_track}"
    if q2 != queries[0]:
        queries.append(q2)
    if len(cleaned_track.split()) >= 2:
        queries.append(cleaned_track)
    first_artist = artist.split()[0] if artist.split() else artist
    if first_artist.lower() != cleaned_artist.lower():
        queries.append(f"{first_artist} {cleaned_track}")

    seen: set[str] = set()
    for q in queries:
        if q in seen:
            continue
        seen.add(q)
        log.info(f"[native] Search strategy: '{q}'")
        results = await client.search(q)
        if results:
            candidates = await pick_best_results_native(results, artist, track, reputation=client.reputation)
            if candidates:
                return candidates

    return []


async def search_and_download_native(
    client: "SoulseekClient",
    artist: str,
    track: str,
) -> dict:
    """Search and download best result using native client."""
    candidates = await search_multi_strategy_native(client, artist, track)
    if not candidates:
        return {"status": "not_found", "message": f"No results for {artist} - {track}"}

    last_error = "Download failed"

    for i, candidate in enumerate(candidates):
        username = candidate["username"]
        filename = candidate["filename"]

        log.info(f"[native] Download attempt {i+1}/{len(candidates)}: {username} - {filename}")
        try:
            transfer = await client.download(username, filename)
            return {
                "status": "downloading",
                "username": username,
                "filename": filename,
                "size": candidate.get("size", 0),
                "attempt": i + 1,
            }
        except Exception as e:
            last_error = str(e)
            log.warning(f"[native] Download attempt {i+1} failed ({username}): {last_error}")
            await client.reputation.record_failure(username)

    return {"status": "failed", "message": f"All {len(candidates)} candidates failed: {last_error}"}
