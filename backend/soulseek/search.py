"""Multi-strategy search + quality scoring — uses native SoulseekClient."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from backend.config import get_settings
from backend.soulseek.protocol.types import SearchResult
from backend.services.soulseek import (
    normalize_text, words_match, strip_track_extras, clean_track_name,
    clean_artist_name, title_matches, PREFERRED_EXTENSIONS,
)

if TYPE_CHECKING:
    from backend.soulseek.client import SoulseekClient

log = logging.getLogger(__name__)

MAX_QUERY_VARIANTS = 4
DURATION_TOLERANCE = 3  # seconds a candidate's reported duration may differ from the target


def beats_quality(ext: str, size: int, current: tuple[str, int]) -> bool:
    """Would a file with this extension and size be an upgrade over `current`
    (format, file_size)? Same ranking the importer applies after download: a
    better format wins; the same format needs to be clearly larger (higher bitrate)."""
    from backend.services.scanner import FORMAT_QUALITY
    cur_fmt, cur_size = current
    new_rank = FORMAT_QUALITY.get(ext.lstrip(".").lower(), 0)
    cur_rank = FORMAT_QUALITY.get((cur_fmt or "").lower(), 0)
    if new_rank != cur_rank:
        return new_rank > cur_rank
    return size > (cur_size or 0) * 1.1


async def pick_best_results_native(
    results: list,  # list of SearchResult
    artist: str,
    track: str,
    reputation=None,
    better_than: tuple[str, int] | None = None,
    target_duration: int | None = None,
) -> list[dict]:
    """Score and rank search results from native client. Returns flat file list.

    better_than=(format, file_size) keeps only files that would upgrade that copy,
    so an upgrade never downloads something the importer will throw away.

    target_duration (seconds) rejects files whose reported duration is more than
    DURATION_TOLERANCE off — a different song that shares enough title words to
    pass the title gate. Files that report no duration are kept; a matching
    duration earns a bonus."""
    settings = get_settings()
    min_size = settings.soulseek.min_file_size_mb * 1024 * 1024

    scored = []
    rejected_title = 0
    rejected_quality = 0
    rejected_duration = 0
    want_duration = int(target_duration) if target_duration and target_duration > 0 else None
    for search_result in results:
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

            if better_than is not None and not beats_quality(ext, size, better_than):
                rejected_quality += 1
                continue

            # HARD GATE: the candidate filename must actually contain the target
            # track title, else skip it — a pristine FLAC of a *different* song must
            # never win on format/peer points alone (was grabbing wrong songs).
            if not title_matches(track, filename):
                rejected_title += 1
                continue

            duration_match = False
            if want_duration is not None and file_info.duration > 0:
                if abs(file_info.duration - want_duration) > DURATION_TOLERANCE:
                    rejected_duration += 1
                    continue
                duration_match = True

            score = 0
            if duration_match:
                score += 6
            # Artist match — strong signal, not required (often only in the path).
            if words_match(clean_artist_name(artist), filename) or words_match(artist, filename):
                score += 12
            # Track match strength (gate already passed; grade full vs extras-stripped)
            if words_match(track, filename):
                score += 15
            else:
                score += 10

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

            # Queue length penalty — heavily-queued peers serve us slower
            ql = search_result.queue_length
            if ql > 100:
                score -= 10
            elif ql > 50:
                score -= 6
            elif ql > 20:
                score -= 3
            elif ql > 5:
                score -= 1

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
                    "duration": file_info.duration,
                }))

    if rejected_title:
        log.info(f"[native] title gate skipped {rejected_title} file(s) not matching '{track}'")
    if rejected_quality:
        log.info(f"[native] upgrade gate skipped {rejected_quality} file(s) no better than {better_than[0]}")
    if rejected_duration:
        log.info(f"[native] duration gate skipped {rejected_duration} file(s) not within "
                 f"{DURATION_TOLERANCE}s of {want_duration}s")

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


def build_query_variants(artist: str, track: str) -> list[str]:
    """The 1-4 distinct search queries tried for one track, most specific first."""
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
    out: list[str] = []
    for q in queries:
        if q not in out:
            out.append(q)
    return out[:MAX_QUERY_VARIANTS]


def merge_search_results(responses: list[list[SearchResult]]) -> list[SearchResult]:
    """Merge the responses of several queries into one list: one SearchResult per
    peer (first-seen slot/speed/queue figures), each file listed once per
    (username, filename)."""
    merged: dict[str, SearchResult] = {}
    seen_files: set[tuple[str, str]] = set()
    for results in responses:
        for sr in results:
            target = merged.get(sr.username)
            if target is None:
                target = SearchResult(
                    username=sr.username, token=sr.token, files=[],
                    slots_free=sr.slots_free, avg_speed=sr.avg_speed, queue_length=sr.queue_length,
                )
                merged[sr.username] = target
            for fi in sr.files:
                key = (sr.username, fi.filename)
                if key in seen_files:
                    continue
                seen_files.add(key)
                target.files.append(fi)
    return list(merged.values())


async def search_multi_strategy_native(
    client: "SoulseekClient",
    artist: str,
    track: str,
    better_than: tuple[str, int] | None = None,
    target_duration: int | None = None,
) -> list[dict]:
    """Search the most specific query first; only if it gives no usable
    candidate, search the remaining variants at once, merge everything and rank
    once.

    The first query usually succeeds, so most tracks cost one search (the
    Soulseek server is believed to throttle heavy searchers). For a hard track
    the fallbacks run concurrently — each client.search uses its own token — so
    it costs two search timeouts instead of up to four in a row."""
    queries = build_query_variants(artist, track)

    async def run(qs: list[str]) -> list[list[SearchResult]]:
        log.info(f"[native] Search strategies: {qs}")
        responses = await asyncio.gather(*(client.search(q) for q in qs), return_exceptions=True)
        ok: list[list[SearchResult]] = []
        for q, r in zip(qs, responses):
            if isinstance(r, BaseException):
                log.warning(f"[native] Search '{q}' failed: {r}")
                continue
            ok.append(r)
        return ok

    async def rank(responses: list[list[SearchResult]]) -> list[dict]:
        merged = merge_search_results(responses)
        if not merged:
            return []
        return await pick_best_results_native(merged, artist, track, reputation=client.reputation,
                                              better_than=better_than, target_duration=target_duration)

    first = await run(queries[:1])
    candidates = await rank(first)
    if candidates or len(queries) == 1:
        return candidates
    rest = await run(queries[1:])
    return await rank(first + rest)


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
