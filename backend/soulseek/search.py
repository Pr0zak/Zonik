"""Multi-strategy search + quality scoring — uses native SoulseekClient."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from backend.config import get_settings
from backend.soulseek.protocol.types import SearchResult
from backend.services.soulseek import (
    normalize_text, words_match, strip_track_extras, clean_track_name,
    clean_artist_name, title_matches, PREFERRED_EXTENSIONS,
)

if TYPE_CHECKING:
    from backend.soulseek.client import SoulseekClient

log = logging.getLogger(__name__)

MAX_QUERY_VARIANTS = 5
DURATION_TOLERANCE = 3  # seconds a candidate's reported duration may differ from the target
# A soft target (an outside length, e.g. Last.fm's, which may be another version's)
# only penalises a candidate this far off; it never rejects one.
SOFT_DURATION_MISS = 10
# Funnel stats: why files found by a search did not become candidates.
REJECT_REASONS = ("size", "ext", "quality", "title", "duration", "score", "artist_path")
MAX_STAT_CANDIDATES = 5


def _empty_rejected() -> dict[str, int]:
    return {k: 0 for k in REJECT_REASONS}


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
    strict_duration: bool = True,
    stats: dict | None = None,
) -> list[dict]:
    """Score and rank search results from native client. Returns flat file list.

    better_than=(format, file_size) keeps only files that would upgrade that copy,
    so an upgrade never downloads something the importer will throw away.

    target_duration (seconds) rejects files whose reported duration is more than
    DURATION_TOLERANCE off — a different song that shares enough title words to
    pass the title gate. Files that report no duration are kept; a matching
    duration earns a bonus. With strict_duration=False (a length from outside the
    library, which may be another version's) nothing is rejected: a match within
    DURATION_TOLERANCE still earns the bonus, one more than SOFT_DURATION_MISS off
    loses a little.

    stats, when given, is filled in place with the funnel for this ranking:
    peers_seen, files_seen, rejected {size, ext, quality, title, duration, score,
    artist_path} and kept (files that scored above zero, before the one-per-peer
    cut). Existing keys are overwritten, so the last ranking wins."""
    settings = get_settings()
    min_size = settings.soulseek.min_file_size_mb * 1024 * 1024

    scored = []
    rejected_title = 0
    rejected_quality = 0
    rejected_duration = 0
    rejected_size = 0
    rejected_ext = 0
    rejected_score = 0
    files_seen = 0
    want_duration = int(target_duration) if target_duration and target_duration > 0 else None
    for search_result in results:
        for file_info in search_result.files:
            files_seen += 1
            filename = file_info.filename
            size = file_info.size

            if size < min_size:
                rejected_size += 1
                continue

            ext = ""
            for e in PREFERRED_EXTENSIONS:
                if filename.lower().endswith(e):
                    ext = e
                    break
            if not ext:
                rejected_ext += 1
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
            duration_miss = False
            if want_duration is not None and file_info.duration > 0:
                off = abs(file_info.duration - want_duration)
                if off <= DURATION_TOLERANCE:
                    duration_match = True
                elif strict_duration:
                    rejected_duration += 1
                    continue
                elif off > SOFT_DURATION_MISS:
                    duration_miss = True

            score = 0
            if duration_match:
                score += 6
            elif duration_miss:
                score -= 4
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
                    "extension": ext.lstrip(".").lower(),
                    "size": size,
                    "bitRate": bitrate,
                    "slots_free": search_result.slots_free,
                    "queue_length": ql,
                    "avg_speed": search_result.avg_speed,
                    "duration": file_info.duration,
                    "score": score,
                }))
            else:
                rejected_score += 1

    if rejected_title:
        log.info(f"[native] title gate skipped {rejected_title} file(s) not matching '{track}'")
    if rejected_quality:
        log.info(f"[native] upgrade gate skipped {rejected_quality} file(s) no better than {better_than[0]}")
    if rejected_duration:
        log.info(f"[native] duration gate skipped {rejected_duration} file(s) not within "
                 f"{DURATION_TOLERANCE}s of {want_duration}s")

    if stats is not None:
        rejected = _empty_rejected()
        rejected.update(size=rejected_size, ext=rejected_ext, quality=rejected_quality,
                        title=rejected_title, duration=rejected_duration, score=rejected_score)
        stats["peers_seen"] = len(results)
        stats["files_seen"] = files_seen
        stats["rejected"] = rejected
        stats["kept"] = len(scored)

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


def build_query_variants(artist: str, track: str, album: str | None = None) -> list[str]:
    """The 1-5 distinct search queries tried for one track, most specific first."""
    queries = [f"{artist} {track}"]
    cleaned_track = strip_track_extras(track)
    cleaned_artist = clean_artist_name(artist)
    q2 = f"{cleaned_artist} {cleaned_track}"
    if q2 != queries[0]:
        queries.append(q2)
    if album:
        cleaned_album = strip_track_extras(album)
        if cleaned_album:
            queries.append(f"{cleaned_artist} {cleaned_album}")
    track_words = cleaned_track.split()
    if len(track_words) >= 3:
        queries.append(f"{cleaned_artist} {' '.join(track_words[-2:])}")
    # Title-only query: the Soulseek server returns nothing for searches that contain
    # some major-label artist names (e.g. "Rihanna"), so the title alone is the only
    # way to find those tracks. One-word titles used to be excluded here, which made
    # "Rihanna - Disturbia" unfindable; their results are filtered to files whose path
    # names the artist (see search_multi_strategy_native), so a one-word title can't
    # pull in a different artist's song.
    if cleaned_track:
        queries.append(cleaned_track)
    first_artist = artist.split()[0] if artist.split() else artist
    if first_artist.lower() != cleaned_artist.lower():
        queries.append(f"{first_artist} {cleaned_track}")
    out: list[str] = []
    for q in queries:
        if q not in out:
            out.append(q)
    cap = MAX_QUERY_VARIANTS if album else 4
    return out[:cap]


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
    album: str | None = None,
    better_than: tuple[str, int] | None = None,
    target_duration: int | None = None,
    strict_duration: bool = True,
    *,
    stats: dict | None = None,
    on_event: Callable[[dict], Awaitable[None]] | None = None,
) -> list[dict]:
    """Search the most specific query first; only if it gives no usable
    candidate, search the remaining variants at once, merge everything and rank
    once.

    The first query usually succeeds, so most tracks cost one search (the
    Soulseek server is believed to throttle heavy searchers). For a hard track
    the fallbacks run concurrently — each client.search uses its own token — so
    it costs two search timeouts instead of up to four in a row.

    stats, when given, is filled in place with the search funnel: queries
    [{q, kind, peers, files} | {q, kind, peers, files, error}], album_query,
    peers_seen, files_seen, rejected, kept (from the last ranking, over every
    response so far), wanted_duration, strict and candidates (the first five
    returned). on_event, when given, is awaited with
    {"event": "query_start", i, n, q, kind} before each query and
    {"event": "query_end", i, n, q, kind, peers, files} after it (i is 1-based;
    n grows by one when the album fallback runs); its exceptions are logged and
    swallowed."""
    queries = build_query_variants(artist, track)
    total = len(queries)
    if stats is not None:
        stats["queries"] = []
        stats["album_query"] = None
        stats["peers_seen"] = 0
        stats["files_seen"] = 0
        stats["rejected"] = _empty_rejected()
        stats["kept"] = 0
        stats["wanted_duration"] = (int(target_duration)
                                    if target_duration and target_duration > 0 else None)
        stats["strict"] = bool(strict_duration)
        stats["candidates"] = []

    async def emit(event: dict[str, Any]) -> None:
        if on_event is None:
            return
        try:
            await on_event(event)
        except Exception as e:
            log.warning(f"[native] search on_event callback failed: {e}")

    async def one(i: int, q: str, kind: str, n: int):
        await emit({"event": "query_start", "i": i, "n": n, "q": q, "kind": kind})
        try:
            r = await client.search(q)
        except Exception as e:
            await emit({"event": "query_end", "i": i, "n": n, "q": q, "kind": kind,
                        "peers": 0, "files": 0, "error": str(e)})
            raise
        await emit({"event": "query_end", "i": i, "n": n, "q": q, "kind": kind,
                    "peers": len(r), "files": sum(len(sr.files) for sr in r)})
        return r

    async def run(qs: list[str], first_index: int, kind: str, n: int) -> list[list[SearchResult]]:
        log.info(f"[native] Search strategies: {qs}")
        responses = await asyncio.gather(
            *(one(first_index + k, q, kind, n) for k, q in enumerate(qs)), return_exceptions=True,
        )
        ok: list[list[SearchResult]] = []
        for q, r in zip(qs, responses):
            if isinstance(r, BaseException):
                log.warning(f"[native] Search '{q}' failed: {r}")
                if stats is not None:
                    stats["queries"].append({"q": q, "kind": kind, "peers": 0, "files": 0, "error": str(r)})
                continue
            if stats is not None:
                stats["queries"].append({"q": q, "kind": kind, "peers": len(r),
                                         "files": sum(len(sr.files) for sr in r)})
            ok.append(r)
        return ok

    async def rank(responses: list[list[SearchResult]]) -> list[dict]:
        merged = merge_search_results(responses)
        if not merged:
            return []
        found = await pick_best_results_native(merged, artist, track, reputation=client.reputation,
                                               better_than=better_than, target_duration=target_duration,
                                               strict_duration=strict_duration, stats=stats)
        if len(strip_track_extras(track).split()) == 1:
            # A one-word title matches many unrelated songs; keep files whose path
            # names the artist.
            artist_name = clean_artist_name(artist)
            before = len(found)
            found = [c for c in found if words_match(artist_name, c["filename"]) or words_match(artist, c["filename"])]
            dropped = before - len(found)
            if stats is not None and dropped:
                stats["rejected"]["artist_path"] = stats["rejected"].get("artist_path", 0) + dropped
                stats["kept"] = max(0, stats.get("kept", 0) - dropped)
        return found

    def finish(candidates: list[dict]) -> list[dict]:
        if stats is not None:
            stats["candidates"] = [dict(c) for c in candidates[:MAX_STAT_CANDIDATES]]
        return candidates

    first = await run(queries[:1], 1, "variant", total)
    candidates = await rank(first)
    if candidates or len(queries) == 1:
        return finish(candidates)
    rest = await run(queries[1:], 2, "variant", total)
    candidates = await rank(first + rest)
    if candidates:
        return finish(candidates)

    # If all track-specific queries return no candidates, fall back to album query.
    # Soulseek peers often share full album folders, where folder names match artist + album
    # while files inside are named e.g. "05 - Song.flac".
    target_album = album
    if not target_album:
        try:
            from backend.services.lastfm import get_track_info
            info = await get_track_info(artist, track)
            if info and info.get("album"):
                target_album = info["album"]
                log.info(f"[native] Resolved album via Last.fm for '{artist} - {track}': {target_album}")
        except Exception as e:
            log.debug(f"[native] Last.fm album lookup failed: {e}")

    if target_album:
        cleaned_album = strip_track_extras(target_album)
        cleaned_artist = clean_artist_name(artist)
        album_query = f"{cleaned_artist} {cleaned_album}".strip()
        if album_query and album_query not in queries:
            log.info(f"[native] Fallback album search for '{artist} - {track}': {album_query}")
            if stats is not None:
                stats["album_query"] = album_query
            album_res = await run([album_query], total + 1, "album", total + 1)
            candidates = await rank(first + rest + album_res)

    return finish(candidates)


async def search_and_download_native(
    client: "SoulseekClient",
    artist: str,
    track: str,
    album: str | None = None,
) -> dict:
    """Search and download best result using native client."""
    candidates = await search_multi_strategy_native(client, artist, track, album=album)
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
