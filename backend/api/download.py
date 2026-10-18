"""Download API routes - Soulseek search and download triggers."""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
import uuid
from collections import Counter
from datetime import datetime

log = logging.getLogger(__name__)

# Two module-level queues. A job takes a *search* slot when it starts (that is
# what "pending" vs "running" means for a job row) and gives it back once it has
# its candidates; each transfer attempt then takes a *transfer* slot. Searches are
# cheap and short, transfers long, so one stubborn track no longer holds a slot
# for 20 minutes while other jobs can't even search.
_search_semaphore: asyncio.Semaphore | None = None
_transfer_semaphore: asyncio.Semaphore | None = None

# Download jobs the user cancelled (filled by the job-cancel route in
# backend/api/jobs.py). Checked in memory on every poll instead of reading the
# job row from SQLite every 2 seconds.
cancelled_jobs: set[str] = set()

# Download jobs owned by a task in this process, from the moment their row is
# written (so a job still waiting for a slot counts) until that task ends. The
# cancel route only adds ids found here, so a stale row from before a restart
# can't leave an id in cancelled_jobs that nothing will ever remove.
live_download_jobs: set[str] = set()


# Fine stage of every live download job (tracks[0].stage), kept in memory so
# /api/download/status can count stages over ALL active jobs without reading the
# rows. stage_counts[stage] == number of jobs in _job_stage at that stage.
STAGES = ("queue_search", "searching", "peer_lock", "waiting_slot", "connecting",
          "queued_at_peer", "transferring", "importing")
# A transfer's state -> the job stage it means (poll_transfer's on_state, and the
# live counts in /api/download/status, which prefer the transfer table).
_TRANSFER_STAGE = {"requested": "queued_at_peer", "queued": "queued_at_peer",
                   "connected": "connecting", "transferring": "transferring"}
stage_counts: Counter[str] = Counter()
_job_stage: dict[str, str] = {}

# Each live download job's timeline (the list stored as JSON in Job.log), so a
# stage write appends without re-reading the row.
_timelines: dict[str, list] = {}


def _forget_stage(job_id: str) -> None:
    """Take a job out of the stage counters (idempotent)."""
    old = _job_stage.pop(job_id, None)
    if old is not None:
        stage_counts[old] -= 1
        if stage_counts[old] <= 0:
            del stage_counts[old]


def _job_done(job_id: str) -> None:
    """Forget a download job's in-memory flags once its task has finished."""
    live_download_jobs.discard(job_id)
    cancelled_jobs.discard(job_id)
    _forget_stage(job_id)
    _timelines.pop(job_id, None)

# How long a job waits for a peer that another job is downloading from before it
# moves on to its next candidate (the busy one is retried once at the end).
PEER_BUSY_WAIT = 60

# Seconds the download code waits for a reconnect before failing a job, and the
# scans an upgrade gets before it is retired (download_attempts.upgrade_skip_ids).
RECONNECT_WAIT_S = 30
UPGRADE_MAX_SCANS = 3


def _get_search_semaphore() -> asyncio.Semaphore:
    """Lazy-init the job/search queue (soulseek.max_concurrent_searches)."""
    global _search_semaphore
    if _search_semaphore is None:
        from backend.config import get_settings
        limit = max(1, get_settings().soulseek.max_concurrent_searches)
        _search_semaphore = asyncio.Semaphore(limit)
        log.info(f"[download] Search queue initialized: max {limit} concurrent searches")
    return _search_semaphore


def _get_transfer_semaphore() -> asyncio.Semaphore:
    """Lazy-init the transfer queue (soulseek.max_concurrent_downloads)."""
    global _transfer_semaphore
    if _transfer_semaphore is None:
        from backend.config import get_settings
        limit = max(1, get_settings().soulseek.max_concurrent_downloads)
        _transfer_semaphore = asyncio.Semaphore(limit)
        log.info(f"[download] Transfer queue initialized: max {limit} concurrent transfers")
    return _transfer_semaphore


def _get_semaphore() -> asyncio.Semaphore:
    """The queue a new download job waits in (its search phase)."""
    return _get_search_semaphore()


def reset_download_semaphore():
    """Reset both queues after a config change. New limits take effect for the
    next jobs; slots already held are returned to the semaphore they came from."""
    global _search_semaphore, _transfer_semaphore
    _search_semaphore = None
    _transfer_semaphore = None


class _SearchSlot:
    """A search-queue slot a job holds from admission until it has its candidates.
    release() is idempotent, so the job can hand it back early and the wrapper's
    finally can still call it safely."""

    def __init__(self, sem: asyncio.Semaphore):
        self._sem = sem
        self._held = False

    async def acquire(self) -> None:
        await self._sem.acquire()
        self._held = True

    def release(self) -> None:
        if self._held:
            self._held = False
            self._sem.release()


# --- stage writer + timeline (tracks[0] / Job.log of a download row) -----------

# tracks[0].status keeps exactly these values (jobs.py decides retryability from
# them); the fine-grained position lives in tracks[0].stage.
TRACK_STATUSES = ("queued", "pending", "downloading", "downloaded", "failed")
# tracks[0] keys carried over from one rewrite of the row to the next.
_STICKY_TRACK_KEYS = ("stage", "stage_since", "attempt", "of", "username", "filename", "queue_place",
                      "source_errors", "search", "origin", "batch", "file_size", "track_id", "error")
TIMELINE_CAP = 200
# Candidate fields kept in result.candidates / the picked event (DC-5), and how many.
_CANDIDATE_KEYS = ("username", "filename", "extension", "size", "bitRate", "slots_free",
                   "queue_length", "avg_speed", "duration", "score")
MAX_RESULT_CANDIDATES = 5


def _utc_iso() -> str:
    """Naive UTC ISO timestamp, the same shape as Job.started_at."""
    return datetime.utcnow().isoformat()


def _prev_track(job) -> dict | None:
    """tracks[0] of a job row as a dict, or None."""
    try:
        tracks = json.loads(job.tracks) if job.tracks else None
    except (TypeError, ValueError):
        return None
    if isinstance(tracks, list) and tracks and isinstance(tracks[0], dict):
        return tracks[0]
    return None


def _track_doc(req, status: str, *, prev: dict | None = None, **fields) -> dict:
    """Build tracks[0] for a download row: artist/track from req (or fields/prev),
    the sticky keys from prev, then fields on top. A field passed as None removes
    that key. `search` only survives while stage == "searching"."""
    if status not in TRACK_STATUSES:
        raise ValueError(f"tracks status {status!r} not in {TRACK_STATUSES}")
    prev = prev or {}
    doc: dict = {
        "artist": req.artist if req is not None else fields.pop("artist", prev.get("artist", "")),
        "track": req.track if req is not None else fields.pop("track", prev.get("track", "")),
        "status": status,
    }
    fields.pop("artist", None)
    fields.pop("track", None)
    for k in _STICKY_TRACK_KEYS:
        if k in prev:
            doc[k] = prev[k]
    for k, v in fields.items():
        if v is None:
            doc.pop(k, None)
        else:
            doc[k] = v
    if doc.get("stage") != "searching":
        doc.pop("search", None)
    return doc


def _timeline(job, job_id: str) -> list:
    """The in-memory timeline of a job, seeded from Job.log when that already
    holds a list of events (a list of strings is another job type's log)."""
    tl = _timelines.get(job_id)
    if tl is None:
        tl = []
        try:
            existing = json.loads(job.log) if getattr(job, "log", None) else None
        except (TypeError, ValueError):
            existing = None
        if isinstance(existing, list) and all(isinstance(e, dict) for e in existing):
            tl = existing
        _timelines[job_id] = tl
    return tl


def _log_event(job, job_id: str, kind: str, /, **fields) -> None:
    """Append {"t", "k", ...fields} to the job's timeline and mirror it into job.log
    (persisted by the next save). Keeps the first event (submitted) plus the
    newest ones within TIMELINE_CAP."""
    tl = _timeline(job, job_id)
    tl.append({"t": _utc_iso(), "k": kind, **fields})
    if len(tl) > TIMELINE_CAP:
        del tl[1:len(tl) - TIMELINE_CAP + 1]
    job.log = json.dumps(tl)


def _note_stage(job_id: str, stage: str) -> None:
    """Move a job to `stage` in the in-memory counters."""
    old = _job_stage.get(job_id)
    if old == stage:
        return
    if old is not None:
        stage_counts[old] -= 1
        if stage_counts[old] <= 0:
            del stage_counts[old]
    _job_stage[job_id] = stage
    stage_counts[stage] += 1


def _job_payload(job, job_id: str, description: str, doc: dict | None, *, progress: int = 0, total: int = 1) -> dict:
    """A running download's job_update: today's keys plus the stage fields (DC-3)."""
    doc = doc or {}
    return {
        "id": job_id, "type": "download", "status": job.status, "progress": progress, "total": total,
        "description": description, "card": getattr(job, "card", None),
        "stage": doc.get("stage"), "stage_since": doc.get("stage_since"),
        "attempt": doc.get("attempt"), "of": doc.get("of"), "username": doc.get("username"),
        "queue_place": doc.get("queue_place"), "search": doc.get("search"),
    }


def _initial_row(job_id: str, req, card: str, initial_status: str) -> tuple[str, str]:
    """tracks + log JSON for a new download row (stage queue_search while it waits
    for a search slot, searching otherwise), registered in the stage counters."""
    stage = "queue_search" if initial_status == "pending" else "searching"
    origin = getattr(req, "origin", None) or None
    doc = _track_doc(req, "queued" if initial_status == "pending" else "pending",
                     stage=stage, stage_since=_utc_iso(), origin=origin)
    _note_stage(job_id, stage)
    submitted = {"t": _utc_iso(), "k": "submitted", "card": card, "source": req.source}
    if origin:
        submitted["origin"] = origin
    tl = [submitted]
    _timelines[job_id] = tl
    return json.dumps([doc]), json.dumps(tl)


async def _set_stage(job, job_id: str, desc: str, req, *, stage: str | None = None, status: str | None = None,
                     event: str | None = None, event_fields: dict | None = None, description: str | None = None,
                     broadcast: bool = True, **fields) -> dict:
    """Rewrite tracks[0] of a live download row, save it and (broadcast) send a
    job_update. stage_since changes only when the stage does; status None keeps
    the current tracks status. event is appended to the timeline with
    event_fields (default: fields). Never touches job.result."""
    prev = _prev_track(job) or {}
    if status is None:
        status = prev.get("status") if prev.get("status") in TRACK_STATUSES else "pending"
    if stage is not None:
        if stage not in STAGES:
            raise ValueError(f"unknown stage {stage!r}")
        if stage != prev.get("stage") or not prev.get("stage_since"):
            fields["stage_since"] = _utc_iso()
        fields["stage"] = stage
        _note_stage(job_id, stage)
    doc = _track_doc(req, status, prev=prev, **fields)
    job.tracks = json.dumps([doc])
    if event:
        ev = event_fields if event_fields is not None else {
            k: v for k, v in fields.items() if k not in ("stage", "stage_since")}
        _log_event(job, job_id, event, **ev)
    if job_id in cancelled_jobs:
        # The cancel route already wrote the row as failed ("Cancelled by user") and
        # broadcast it. Saving this detached, still-running copy (search events and
        # transfer state changes arrive until the task notices) would flip the row
        # and the page back to running; the terminal write saves the timeline.
        return doc
    await _save_job_obj(job)
    if broadcast:
        await broadcast_job_update(_job_payload(job, job_id, description if description is not None else desc, doc))
    return doc


def _terminal_event(job, job_id: str) -> None:
    """Log done / cancelled / failed for a job whose status and result are final."""
    try:
        result = json.loads(job.result) if job.result else {}
    except (TypeError, ValueError):
        result = {}
    if not isinstance(result, dict):
        result = {}
    if job.status == "completed":
        _log_event(job, job_id, "done", track_id=result.get("track_id"), file_size=result.get("file_size"),
                   already_in_library=bool(result.get("already_in_library")), attempt=result.get("attempt"))
    elif result.get("error") == "Cancelled by user":
        _log_event(job, job_id, "cancelled")
    else:
        try:
            from backend.services.download_failures import failure_class
            cls = failure_class(job.status, job.result, job.tracks)
        except Exception:
            cls = None
        _log_event(job, job_id, "failed", error=job_outcome(job.status, job.result).get("error"), **{"class": cls})


# Seconds between two looks at a transfer in poll_transfer (tests shrink it).
POLL_INTERVAL = 2


async def poll_transfer(client, transfer, job_id: str | None, queue_timeout=120, stall_timeout=60, check_cancel=True,
                        *, on_state=None):
    """Poll a Transfer (the object client.download returned) until it settles.
    Returns (status, save_path, error). Every give-up goes through
    TransferManager.abort(), which also stops the socket task and deletes the partial.

    Gives up when the peer doesn't start within queue_timeout, when data stops
    for stall_timeout, or at the soulseek.transfer_max_minutes ceiling — a slow
    transfer that keeps making progress is otherwise allowed to finish. A job id
    found in cancelled_jobs (check_cancel) aborts the transfer as the user's doing.

    on_state (async, optional) is awaited with the transfer whenever its state or
    queue_place differs from what the previous tick saw (the first tick always
    reports); its exceptions are logged and never stop the poll."""
    import time
    from backend.soulseek.protocol.types import TransferState
    from backend.config import get_settings as _cfg
    last_bytes = 0
    stall_start = None
    queue_start = time.monotonic()
    max_seconds = max(1, _cfg().soulseek.transfer_max_minutes) * 60
    seen = None  # (state, queue_place) last reported to on_state
    while time.monotonic() - queue_start < max_seconds:
        await asyncio.sleep(POLL_INTERVAL)
        if on_state is not None:
            now_seen = (transfer.state, getattr(transfer, "queue_place", None))
            if now_seen != seen:
                seen = now_seen
                try:
                    await on_state(transfer)
                except Exception as e:
                    log.warning(f"[download] on_state callback failed for {job_id}: {e}")
        if check_cancel and job_id in cancelled_jobs:
            client.transfers.abort(transfer, "Cancelled by user", blame_peer=False)
            return "cancelled", None, "Cancelled by user"
        if transfer.state == TransferState.COMPLETED:
            return "completed", transfer.save_path, None
        elif transfer.state in (TransferState.FAILED, TransferState.DENIED):
            return "failed", None, transfer.error or transfer.state
        if not client.transfers.is_tracked(transfer):
            client.transfers.abort(transfer, "Transfer removed")
            return "failed", None, "Transfer removed"

        # Waiting for peer to accept (REQUESTED/QUEUED) — use queue timeout
        if transfer.state in (TransferState.REQUESTED, TransferState.QUEUED):
            if time.monotonic() - queue_start > queue_timeout:
                if transfer.state == TransferState.REQUESTED:
                    client.transfers.abort(transfer, "Peer never answered")
                    return "failed", None, f"Peer never answered in {queue_timeout:.0f} s"
                place = getattr(transfer, "queue_place", None)
                client.transfers.abort(transfer, "Peer queued us but did not start")
                where = f" (place {place})" if place is not None else ""
                return "failed", None, f"Peer queued us{where} but did not start in {queue_timeout:.0f} s"
            continue  # Don't check stall yet

        # CONNECTED/TRANSFERRING — detect data stall
        if transfer.received_bytes > last_bytes:
            last_bytes = transfer.received_bytes
            stall_start = None
        else:
            if stall_start is None:
                stall_start = time.monotonic()
            elif time.monotonic() - stall_start > stall_timeout:
                client.transfers.abort(transfer, "Stalled (no data)")
                return "failed", None, "Transfer stalled — no data received"
    minutes = max_seconds // 60
    client.transfers.abort(transfer, f"Took longer than {minutes} min")
    return "timeout", None, f"Transfer took longer than {minutes} minutes"


from fastapi import APIRouter, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db, async_session
from backend.models.job import Job
from backend.models.track import Track
from backend.models.blacklist import DownloadBlacklist
from backend.services.soulseek import (
    search_multi_strategy, pick_best_results,
)
from backend.services.blacklist import BlacklistedTrack, is_blacklisted  # noqa: F401  (/search, /trigger, enqueue)
from backend.api.websocket import broadcast_job_update

router = APIRouter()


async def _save_job_obj(job):
    """Save a detached Job object with a short-lived session."""
    async with async_session() as s:
        await s.merge(job)
        await s.commit()


async def _find_existing_download(db: AsyncSession, artist: str, track: str) -> str | None:
    """Check if a pending/running download already exists for this artist+track. Returns job_id or None."""
    artist_lower = artist.strip().lower()
    track_lower = track.strip().lower()
    # Filter by type+status in SQL and use LIKE to narrow candidates before Python scan
    like_pattern = f"%{track_lower[:20]}%"
    result = await db.execute(
        select(Job.id, Job.tracks).where(
            Job.type == "download",
            Job.status.in_(["pending", "running"]),
            Job.tracks.ilike(like_pattern),
        ).limit(50)
    )
    for job_id, tracks_json in result.all():
        if not tracks_json:
            continue
        try:
            tracks = json.loads(tracks_json)
            for t in tracks:
                if (t.get("artist", "").strip().lower() == artist_lower
                        and t.get("track", "").strip().lower() == track_lower):
                    return job_id
        except (json.JSONDecodeError, TypeError):
            pass
    return None


class SearchRequest(BaseModel):
    ai: bool = False  # rank results with the AI download advisor (adds a Claude call)
    artist: str = ""
    track: str = ""
    query: str = ""
    timeout: int = 25  # seconds — search bar uses 10, downloads page uses 25


class DownloadRequest(BaseModel):
    artist: str
    track: str
    album: str | None = None
    username: str | None = None
    filename: str | None = None
    source: str | None = None  # manual, upgrade, discovery, similar, remix, playlist, library
    target_track_id: str | None = None  # the existing track this download should upgrade/replace
    exclude_users: list[str] = []  # peers to skip — "try another source" after these failed
    expected_duration: int | None = None  # seconds; the length candidates are scored against
    # True: candidates more than a few seconds off expected_duration are rejected. Only
    # for a length from the library's own copy; an outside length (Last.fm, a playlist
    # service) may be another version's, so it only scores. A target_track_id's own
    # duration is always strict.
    strict_duration: bool = False
    # True for "Download all" style requests: a track in the failed-search backoff is
    # skipped. A single click (bulk False) always downloads; its outcome is still recorded.
    bulk: bool = False
    # Where in the app the request came from (free text, e.g. "weekly-radar:row"),
    # stamped into tracks[0].origin and the submitted event. Optional.
    origin: str | None = None


class BulkDownloadRequest(BaseModel):
    tracks: list[dict]  # [{artist, track}, ...]
    source: str | None = None


async def find_in_library(db: AsyncSession, artist: str, track: str) -> str | None:
    """Library track id for artist+track, or None.

    Uses the shared library matcher (case, punctuation and "feat." insensitive). That
    matcher also ignores a trailing "(...)", so a request that names a version
    — "(Live)", "[Remix]" — is never matched: the plain song being in the
    library doesn't mean that version is.
    """
    artist, track = (artist or "").strip(), (track or "").strip()
    if not artist or not track or re.search(r"[\(\[]", track):
        return None
    from backend.services.library_match import match_library
    return await match_library(db, artist, track)


_UNSET = object()


def job_outcome(status: str, result_json: str | None, tracks_json=_UNSET) -> dict:
    """What a client needs to finish a download row: the playable track, or why not.

    Sent on the final job_update so clients don't have to fetch the job and
    parse its result string.

    Passing tracks_json (the row's Job.tracks, even None) also returns
    source_errors (list, [] when none), failure_class
    (services.download_failures), stage and stage_since. Callers that leave it out
    (the jobs list and GET /api/jobs/{id}) get exactly the keys they always got.
    """
    try:
        result = json.loads(result_json) if result_json else {}
    except (TypeError, ValueError):
        result = {}
    out: dict = {}
    if isinstance(result, dict):
        if result.get("track_id"):
            out["track_id"] = result["track_id"]
        if result.get("already_in_library"):
            out["already_in_library"] = True
        if result.get("failed_sources"):
            out["failed_sources"] = result["failed_sources"]
        elif result.get("username") and status == "failed":
            out["failed_sources"] = [result["username"]]
        if status == "failed":
            error = result.get("error") or result.get("message")
            if error and result.get("last_error") and result["last_error"] != error:
                error = f"{error}: {result['last_error']}"
            if error:
                out["error"] = error
    elif tracks_json is _UNSET:
        return {}
    if tracks_json is _UNSET:
        return out
    t0 = {}
    try:
        tracks = json.loads(tracks_json) if tracks_json else None
        if isinstance(tracks, list) and tracks and isinstance(tracks[0], dict):
            t0 = tracks[0]
    except (TypeError, ValueError):
        pass
    errs = t0.get("source_errors")
    if not isinstance(errs, list) and isinstance(result, dict):
        errs = result.get("source_errors")
    out["source_errors"] = errs if isinstance(errs, list) else []
    try:
        from backend.services.download_failures import failure_class
        out["failure_class"] = failure_class(status, result_json, tracks_json)
    except Exception:
        out["failure_class"] = None
    out["stage"] = t0.get("stage")
    out["stage_since"] = t0.get("stage_since")
    return out


@router.post("/search")
async def search_soulseek(req: SearchRequest, db: AsyncSession = Depends(get_db)):
    """Search Soulseek P2P network — returns all results with quality info."""
    # Support single query field or artist+track
    artist = req.artist.strip()
    track = req.track.strip()
    if not artist and not track and req.query.strip():
        # Try to split "Artist - Track" from query
        q = req.query.strip()
        parts = [p.strip() for p in q.split(" - ", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            artist, track = parts[0], parts[1]
        else:
            artist, track = q, ""

    reason = await is_blacklisted(db, artist, track) if artist else None
    if reason:
        return {"results": [], "count": 0, "users": 0, "blacklisted": True, "reason": reason}

    from backend.soulseek import get_client
    client = get_client()

    if client and client.logged_in:
        # Native client — return all results
        query = f"{artist} {track}".strip()
        search_results = await client.search(query, timeout=req.timeout, max_responses=100)
        log.warning(f"[search_soulseek] query='{query}' raw_results={len(search_results)} total_files={sum(len(sr.files) for sr in search_results)}")

        results = []
        users = set()
        min_size = 3 * 1024 * 1024
        for sr in search_results:
            for fi in sr.files:
                fn = fi.filename
                ext = ""
                for e in [".flac", ".wav", ".alac", ".mp3", ".m4a", ".ogg", ".opus"]:
                    if fn.lower().endswith(e):
                        ext = e[1:]
                        break
                if not ext or fi.size < min_size:
                    continue
                # Basic relevance: match track or multi-word freeform search tokens
                from backend.services.soulseek import search_relevance_matches
                if not search_relevance_matches(artist, track, fn):
                    continue
                users.add(sr.username)
                results.append({
                    "username": sr.username,
                    "filename": fn,
                    "size": fi.size,
                    "bitrate": fi.bitrate,
                    "extension": ext,
                    "slots_free": sr.slots_free,
                    "speed": sr.avg_speed,
                    "queue_length": sr.queue_length,
                })

        if not results:
            log.info(f"[search_soulseek] Primary query '{query}' yielded 0 results, running multi-strategy fallbacks")
            resolved_artist = artist
            resolved_track = track
            resolved_album = None

            # If track is empty and query is multi-word, attempt catalog resolution
            if not resolved_track and resolved_artist:
                try:
                    from backend.services.catalog import search_catalog
                    from backend.services.soulseek import normalize_text, words_match
                    cat_res = await search_catalog(resolved_artist, limit=3)
                    cat_tracks = cat_res.get("tracks", [])
                    if cat_tracks:
                        top = cat_tracks[0]
                        q_words = [w for w in normalize_text(resolved_artist).split() if len(w) > 1]
                        title_norm = normalize_text(top.get("title", ""))
                        matched_words = sum(1 for w in q_words if w in title_norm)
                        if matched_words >= max(1, len(q_words) // 2) or words_match(resolved_artist, top.get("title", "")):
                            resolved_artist = top.get("artist") or resolved_artist
                            resolved_track = top.get("title") or ""
                            resolved_album = top.get("album")
                            log.info(f"[search_soulseek] Catalog resolved '{artist}' -> artist='{resolved_artist}', track='{resolved_track}', album='{resolved_album}'")
                except Exception as e:
                    log.debug(f"[search_soulseek] Catalog resolution error: {e}")

            # If artist and track are known, resolve album if missing
            if resolved_artist and resolved_track and not resolved_album:
                try:
                    from backend.services.lastfm import get_track_info
                    info = await get_track_info(resolved_artist, resolved_track)
                    if info and info.get("album"):
                        resolved_album = info["album"]
                        log.info(f"[search_soulseek] Last.fm resolved album: '{resolved_album}'")
                except Exception as e:
                    log.debug(f"[search_soulseek] Last.fm album lookup error: {e}")

            # Build fallback queries
            from backend.soulseek.search import build_query_variants
            from backend.services.soulseek import clean_artist_name, strip_track_extras, TITLE_STOPWORDS, normalize_text, words_match, search_relevance_matches
            fallback_queries = []
            if resolved_artist and resolved_track:
                variants = build_query_variants(resolved_artist, resolved_track, album=resolved_album)
                for v in variants:
                    if v != query and v not in fallback_queries:
                        fallback_queries.append(v)

            # Token subsets for 3+ word queries (e.g. "red right hand" -> "right hand", "red right")
            target_str = artist if not track else track
            raw_words = [w for w in normalize_text(target_str).split() if len(w) > 1 and w not in TITLE_STOPWORDS and not w.isdigit()]
            if len(raw_words) >= 3:
                sub_end = " ".join(raw_words[-2:])
                sub_start = " ".join(raw_words[:2])
                if resolved_artist and resolved_artist != artist:
                    c_art = clean_artist_name(resolved_artist)
                    q_art_sub = f"{c_art} {sub_end}"
                    if q_art_sub != query and q_art_sub not in fallback_queries:
                        fallback_queries.append(q_art_sub)
                if sub_end != query and sub_end not in fallback_queries:
                    fallback_queries.append(sub_end)
                if sub_start != query and sub_start not in fallback_queries:
                    fallback_queries.append(sub_start)

            # Execute fallback queries concurrently
            if fallback_queries:
                log.info(f"[search_soulseek] Running fallback queries: {fallback_queries[:4]}")
                fb_timeout = min(req.timeout, 8)
                fb_responses = await asyncio.gather(
                    *(client.search(fq, timeout=fb_timeout, max_responses=50) for fq in fallback_queries[:4]),
                    return_exceptions=True
                )
                seen_keys = set()
                for resp in fb_responses:
                    if isinstance(resp, BaseException) or not resp:
                        continue
                    for sr in resp:
                        for fi in sr.files:
                            fn = fi.filename
                            key = (sr.username, fn)
                            if key in seen_keys:
                                continue
                            ext = ""
                            for e in [".flac", ".wav", ".alac", ".mp3", ".m4a", ".ogg", ".opus"]:
                                if fn.lower().endswith(e):
                                    ext = e[1:]
                                    break
                            if not ext or fi.size < min_size:
                                continue
                            if not search_relevance_matches(resolved_artist or artist, resolved_track or track, fn):
                                continue
                            seen_keys.add(key)
                            users.add(sr.username)
                            results.append({
                                "username": sr.username,
                                "filename": fn,
                                "size": fi.size,
                                "bitrate": fi.bitrate,
                                "extension": ext,
                                "slots_free": sr.slots_free,
                                "speed": sr.avg_speed,
                                "queue_length": sr.queue_length,
                            })
                if resolved_artist and resolved_track:
                    artist, track = resolved_artist, resolved_track

        # Fetch reputation scores for sorting (recently-failed peers sort last)
        for r in results:
            r["rep_score"] = await client.reputation.get_score_adjustment(r["username"])

        # Sort: artist match + format + reputation + slots + size
        from backend.services.soulseek import clean_artist_name, words_match
        format_order = {"flac": 0, "wav": 1, "alac": 1, "mp3": 2, "m4a": 3, "ogg": 3, "opus": 3}
        c_artist = clean_artist_name(artist) if artist else ""
        results.sort(key=lambda r: (
            0 if (c_artist and (words_match(c_artist, r["filename"]) or words_match(artist, r["filename"]))) else (1 if artist else 0),
            format_order.get(r["extension"], 9),
            -r.get("rep_score", 0),
            not r["slots_free"],
            -r["size"],
        ))

        # Optional AI scoring
        from backend.config import get_settings
        ai_settings = get_settings().assistant
        # Opt-in per request: it's a blocking Claude call on the search path,
        # so only callers that show its pick (the web Downloads page) ask.
        if req.ai and ai_settings.ai_download_advisor and ai_settings.claude_api_key and len(results) > 3:
            try:
                from backend.services.ai.download_advisor import rank_search_results
                ai_result = await rank_search_results(artist, track, results[:15])
                if "ranked" in ai_result and ai_result["ranked"]:
                    # Merge AI scores into results
                    ai_map = {r.get("filename", ""): r for r in ai_result["ranked"]}
                    for r in results:
                        ai = ai_map.get(r["filename"])
                        if ai:
                            r["ai_score"] = ai.get("ai_score")
                            r["ai_reason"] = ai.get("ai_reason", "")
                            r["ai_pick"] = ai.get("ai_pick", False)
            except Exception as e:
                log.debug("AI download advisor error: %s", e)

        return {
            "results": results, "count": len(results), "users": len(users),
            "library_track_id": await find_in_library(db, artist, track),
        }

    # Legacy slskd fallback — limited results
    candidates = await search_multi_strategy(artist, track)
    return {
        "results": [
            {
                "username": c.get("username", ""),
                "filename": c.get("filename", ""),
                "size": c.get("size", 0),
                "bitrate": c.get("bitRate", 0) or c.get("bitrate", 0),
                "extension": c.get("filename", "").rsplit(".", 1)[-1] if "." in c.get("filename", "") else "",
                "slots_free": True,
                "speed": 0,
                "queue_length": 0,
            }
            for c in candidates
        ],
        "count": len(candidates),
        "users": len(set(c.get("username", "") for c in candidates)),
    }


@router.post("/trigger")
async def trigger_download(req: DownloadRequest, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """Download a specific file or auto-search and download best result."""
    reason = await is_blacklisted(db, req.artist, req.track)
    if reason:
        return {"error": "blacklisted", "reason": reason}

    # Discovery-style sources (Weekly Radar, discovery tabs, recommendations, ...) with
    # no hand-picked file go through the failed-search memory: the outcome is always
    # recorded, and a "Download all" request (bulk) skips a track in backoff. No source,
    # "manual", "library" and "upgrade" stay untracked.
    from backend.services.auto_download import TRACKED_SOURCES
    tracked = req.source in TRACKED_SOURCES and not req.filename and not req.target_track_id

    # Auto-download (no specific file picked, not an upgrade) of a song the
    # library already has: nothing to fetch, hand back the track. A picked file
    # still goes ahead — it may be a better copy, and the importer sorts that out.
    if not req.filename and not req.target_track_id:
        in_lib = await find_in_library(db, req.artist, req.track)
        if in_lib:
            return {"status": "in_library", "track_id": in_lib}

    if tracked and req.bulk:
        from backend.services.download_attempts import in_backoff
        why = await in_backoff(db, req.artist, req.track)
        if why:
            log.info(f"[download] Skip ({req.source}): {req.artist} — {req.track}: {why}")
            # "error" too, so clients that only check it stop instead of polling a job.
            return {"status": "skipped", "reason": why, "error": "skipped"}

    # Dedup: skip if same artist+track already pending/running
    existing = await _find_existing_download(db, req.artist, req.track)
    if existing:
        log.info(f"[download] Dedup: {req.artist} — {req.track} already in job {existing}")
        return {"status": "already_downloading", "job_id": existing}

    if tracked and req.expected_duration is None:
        # Same (soft) duration scoring as the scheduler's downloads (Last.fm length).
        from backend.services.auto_download import lookup_duration
        req.expected_duration = await lookup_duration(req.artist, req.track)

    job_id = str(uuid.uuid4())
    desc = f"{req.artist} — {req.track}"
    card = f"dl:{req.source}" if req.source else "dl"
    sem = _get_semaphore()

    # Write the Job row before returning its id, so a client that looks the job
    # up straight away finds it instead of "Job not found".
    initial_status = "pending" if sem.locked() else "running"
    # Register the job as live before the row is committed, so a cancel that
    # arrives between the commit and the registration is still seen.
    live_download_jobs.add(job_id)
    try:
        tracks_json, log_json = _initial_row(job_id, req, card, initial_status)
        async with async_session() as job_sess:
            job = Job(
                id=job_id, type="download", card=card, status=initial_status,
                started_at=datetime.utcnow(), tracks=tracks_json, log=log_json,
            )
            job_sess.add(job)
            await job_sess.commit()
            job_sess.expunge(job)
        await broadcast_job_update(_job_payload(job, job_id, f"Queued: {desc}" if initial_status == "pending" else desc,
                                                _prev_track(job)))
    except Exception:
        _job_done(job_id)
        raise

    async def do_download():
        # Wait for a search slot — no DB session held
        slot = _SearchSlot(sem)
        try:
            import time as _time
            t0 = _time.monotonic()
            await slot.acquire()
            was_pending = job.status == "pending"
            if was_pending:
                job.status = "running"
            try:
                await _set_stage(job, job_id, desc, req, stage="searching", status="pending", event="search_slot",
                                 event_fields={"waited_s": round(_time.monotonic() - t0, 1)},
                                 description=desc, broadcast=was_pending)
            except Exception as e:
                # _do_download_inner retries the write inside its own error handling.
                log.warning(f"[download] Could not mark {job_id} searching: {e}")
                _forget_stage(job_id)
            await _do_download_inner(None, job, job_id, desc, req, search_slot=slot)
        finally:
            slot.release()
            _job_done(job_id)
            if tracked:
                try:
                    from backend.services.auto_download import finish_tracked
                    await finish_tracked(job_id, req.artist, req.track, req.source)
                except Exception as e:
                    log.debug(f"[download] could not record outcome for {desc}: {e}")

    background_tasks.add_task(do_download)
    return {"job_id": job_id}


async def _do_download_inner(db_ignored, job, job_id, desc, req, search_slot: "_SearchSlot | None" = None):
    """Core download logic. Entered holding a search slot (search_slot), which it
    releases once it has its candidates; each transfer attempt then takes a
    transfer slot and the peer's one-at-a-time lock.
    Uses short-lived DB sessions to avoid holding connections during transfers."""
    import asyncio
    from backend.soulseek import get_client
    from backend.soulseek.client import PeerBusy
    from backend.services.scanner import import_downloaded_file

    async def _save_job():
        await _save_job_obj(job)

    outcome: dict = {}  # extra facts for the job result, set by _import_or_fail

    def _file_size(path):
        """Get file size in bytes, or 0 if unavailable."""
        try:
            import os
            return os.path.getsize(path) if path else 0
        except Exception:
            return 0

    # Importer reasons that mean the peer sent a broken file (its fault), as
    # opposed to a deliberate rejection — wrong song, not an upgrade — which is
    # our search's fault and must not count against the peer.
    _PEER_FAULT_REASONS = ("the peer sent an empty file", "isn't readable audio")

    async def _import_or_fail(path):
        """Import a finished transfer. Returns (track_id, file_size, error, peer_fault).

        A peer can report a transfer COMPLETED while delivering an empty or
        truncated file. The importer rejects those and returns no track, so
        treat a missing track_id as a failed download — never a success.
        peer_fault is True only when the rejection was the file's fault.
        """
        fsize = _file_size(path)
        reasons: list[str] = []
        existing_ids: list[str] = []
        async with async_session() as import_sess:
            track_id = await import_downloaded_file(
                import_sess, path, artist_hint=req.artist, target_track_id=req.target_track_id,
                reasons=reasons, existing_ids=existing_ids,
            )
        if not track_id and existing_ids:
            # The library already has this song at equal or better quality. The
            # listener asked for the song, not this particular file, so that's
            # a success: hand back the track they already have. (This used to
            # fail the job and count against a peer that sent a good file.)
            outcome["already_in_library"] = True
            return existing_ids[0], fsize, None, False
        if not track_id:
            # The importer says why; most rejections are deliberate (duplicate, not an
            # upgrade, wrong song), not broken files as this message used to claim.
            why = reasons[-1] if reasons else "the file couldn't be imported"
            peer_fault = any(r in why for r in _PEER_FAULT_REASONS)
            return None, fsize, f"Not imported: {why}", peer_fault
        return track_id, fsize, None, False

    try:
        if job_id in cancelled_jobs:  # cancelled while it waited for a slot
            job.status = "failed"
            job.result = json.dumps({"error": "Cancelled by user"})
            return
        if _job_stage.get(job_id) != "searching":
            # Entered without the caller's slot write (a direct call): start the stage here.
            await _set_stage(job, job_id, desc, req, stage="searching", status="pending",
                             event="search_slot", event_fields={"waited_s": 0.0}, description=desc)
        native_client = get_client()
        from backend.config import get_settings as _get_settings
        dl_settings = _get_settings()
        parallel_sources = dl_settings.soulseek.parallel_sources
        source_strategy = dl_settings.soulseek.source_strategy

        # If the native client exists but the server connection just dropped
        # (auto-reconnect in flight), wait briefly for it to come back rather
        # than instantly failing or falling through to a slskd path that may
        # not be configured. Up to ~30s — short relative to the per-transfer
        # ceiling (soulseek.transfer_max_minutes) but enough to ride through
        # most reconnect blips.
        if native_client and not native_client.logged_in:
            log.info(f"[download] Native client not logged in — waiting up to 30s for reconnect")
            await _set_stage(job, job_id, desc, req, stage="searching", event="reconnect_wait",
                             event_fields={}, description=desc)
            for _ in range(RECONNECT_WAIT_S):
                await asyncio.sleep(1)
                if native_client.logged_in:
                    log.info("[download] Native client reconnected — proceeding")
                    break

        # Treat a not-logged-in native client as "no native client" so we don't
        # waste a full search timeout against a dead connection.
        native_ready = bool(native_client and native_client.logged_in)

        # Upgrades only consider files better than the copy being replaced. Without
        # this the best available MP3 was downloaded and then thrown away as "not
        # higher quality" (266 upgrades failed that way).
        better_than = None
        # Candidates whose reported length differs from the track's by more than a
        # few seconds are a different song (74 upgrades a week were fetched and then
        # discarded as "not the track being upgraded").
        target_duration = req.expected_duration
        strict_duration = req.strict_duration
        if req.target_track_id:
            async with async_session() as q_sess:
                cur = (await q_sess.execute(
                    select(Track.format, Track.file_size, Track.duration_seconds)
                    .where(Track.id == req.target_track_id)
                )).first()
            if cur:
                better_than = (cur[0] or "", cur[1] or 0)
                if cur[2]:
                    # The library's own copy: a different length is a different song.
                    target_duration = int(round(cur[2]))
                    strict_duration = True

        # The search funnel (DC-5 `search`), filled in place by the native search;
        # each query start/end moves the live row (tracks[0].search, DC-1).
        search_stats: dict = {}
        files_seen = {"n": 0}

        async def on_search_event(ev: dict) -> None:
            """Save + broadcast the query the job is on. Runs while the job holds a
            search slot, so it does one save and one broadcast, nothing more."""
            if ev.get("event") == "query_end":
                files_seen["n"] += int(ev.get("files") or 0)
            await _set_stage(job, job_id, desc, req, stage="searching",
                             search={"query_index": ev.get("i"), "query_total": ev.get("n"), "query": ev.get("q"),
                                     "files_seen": files_seen["n"], "kept": int(search_stats.get("kept") or 0)},
                             event=ev.get("event"), event_fields={k: v for k, v in ev.items() if k != "event"},
                             description=desc)

        if req.username and req.filename and native_ready:
            # Direct download — try requested source first, then fall back to search
            candidates = [{"username": req.username, "filename": req.filename, "size": 0}]
            try:
                from backend.soulseek.search import search_multi_strategy_native
                fallbacks = await search_multi_strategy_native(native_client, req.artist, req.track, album=req.album,
                                                               better_than=better_than,
                                                               target_duration=target_duration,
                                                               strict_duration=strict_duration,
                                                               stats=search_stats, on_event=on_search_event)
                # Add fallbacks excluding the already-requested source
                for fb in fallbacks:
                    if fb["username"] != req.username:
                        candidates.append(fb)
                candidates = candidates[:5]  # Limit total attempts
            except Exception as e:
                log.debug("Fallback search failed: %s", e)
        elif native_ready:
            # Auto-download — get candidates from search
            from backend.soulseek.search import search_multi_strategy_native
            candidates = await search_multi_strategy_native(native_client, req.artist, req.track, album=req.album,
                                                            better_than=better_than,
                                                            target_duration=target_duration,
                                                            strict_duration=strict_duration,
                                                            stats=search_stats, on_event=on_search_event)
        elif native_client:
            # Native client exists but never reconnected — fail fast with a
            # clear, recognizable error instead of falling through to slskd.
            job.status = "failed"
            job.result = json.dumps({"error": "Soulseek server not connected — try again later"})
            job.tracks = json.dumps([_track_doc(req, "failed", prev=_prev_track(job), error="Soulseek server not connected")])
            candidates = []  # Skip native loop
        else:
            from backend.services.soulseek import search_and_download
            result = await search_and_download(req.artist, req.track, album=req.album)
            ok = result.get("ok") or result.get("status") == "downloading"
            job.status = "completed" if ok else "failed"
            job.result = json.dumps(result)
            job.tracks = json.dumps([_track_doc(req, "downloaded" if ok else "failed", prev=_prev_track(job))])
            candidates = []  # Skip native loop

        if req.exclude_users and candidates:
            skip = {u.lower() for u in req.exclude_users}
            candidates = [c for c in candidates if c["username"].lower() not in skip]

        # The funnel and the candidates actually tried go on the timeline now and
        # into the result at the terminal write (never mid-run).
        funnel = ({k: v for k, v in search_stats.items() if k != "candidates"}
                  if search_stats.get("queries") is not None else None)
        picked = [{k: c.get(k) for k in _CANDIDATE_KEYS} for c in (candidates or [])[:MAX_RESULT_CANDIDATES]]
        if funnel is not None:
            _log_event(job, job_id, "searched", funnel=funnel)
            _log_event(job, job_id, "picked", candidates=picked)

        def with_funnel(d: dict) -> dict:
            """A terminal result dict plus the search funnel and candidates (DC-5)."""
            if funnel is not None:
                d["search"] = funnel
                d["candidates"] = picked
            return d

        # Search phase over: let the next job search while this one transfers.
        if search_slot is not None:
            search_slot.release()
        transfer_sem = _get_transfer_semaphore()

        if native_ready and not candidates and job.status != "failed":
            job.status = "failed"
            if better_than is not None:
                msg = f"No source better than the current {better_than[0] or 'file'} for {req.artist} - {req.track}"
            else:
                msg = (f"No other sources for {req.artist} - {req.track}" if req.exclude_users
                       else f"No results for {req.artist} - {req.track}")
            job.result = json.dumps(with_funnel({"message": msg}))
            job.tracks = json.dumps([_track_doc(req, "failed", prev=_prev_track(job), search=None)])

        async def _peer_failed(errors: list, user: str, error: str, description: str,
                               event: str = "peer_failed", **event_extra) -> None:
            """One source failed: append it (with "at") to errors — the list
            result.source_errors is written from — then save and broadcast it as
            tracks[0].source_errors at once, and log the event. tracks[0].error is
            left to the terminal write (it holds the LAST error only)."""
            errors.append({"user": user, "error": error, "at": _utc_iso()})
            try:
                await _set_stage(job, job_id, desc, req, source_errors=[dict(e) for e in errors], event=event,
                                 event_fields={"user": user, "error": error, **event_extra},
                                 description=description)
            except Exception as e:
                log.debug(f"[download] Could not save the failure of {user} for {job_id}: {e}")

        def _on_state_for(user: str, description: str, **extra):
            """poll_transfer's on_state for one attempt: the transfer's state becomes
            the row's stage (requested/queued → queued_at_peer, connected →
            connecting, transferring), with the peer's queue place; the
            timeline gets queued{user,place}, connected{user,total_bytes},
            transferring{user} (requested was logged when the request went out)."""
            async def on_state(t) -> None:
                st = _TRANSFER_STAGE.get(t.state)
                if st is None:  # completed / failed: the next write says what happened
                    return
                ev_fields: dict = {"user": user}
                if t.state == "queued":
                    ev_fields["place"] = t.queue_place
                elif t.state == "connected":
                    ev_fields["total_bytes"] = t.total_bytes
                await _set_stage(job, job_id, desc, req, stage=st, status="downloading",
                                 queue_place=getattr(t, "queue_place", None),
                                 event=None if t.state == "requested" else t.state, event_fields=ev_fields,
                                 description=description, **extra)
            return on_state

        if candidates and native_ready and parallel_sources > 1:
            # === Multi-source parallel download ===
            # Several attempts write the same row concurrently: the last writer
            # wins for the stage text (tracks[0].stage is the most recent move of
            # any source), while source_errors accumulates every failure.
            batch = candidates[:parallel_sources]
            many_desc = f"{desc} — {len(batch)} sources"
            await _set_stage(job, job_id, desc, req, stage="peer_lock", status="queued", sources=len(batch), event="peer_lock",
                             event_fields={"users": [c["username"] for c in batch]},
                             description=f"Queued for slot: {desc} ({len(batch)} sources)")

            # Start all downloads concurrently
            async def try_source(candidate):
                """Attempt download from one source. Returns (candidate, status, save_path, error)."""
                import time as _time
                dl_username = candidate["username"]
                dl_filename = candidate["filename"]
                transfer = None
                try:
                    # One file at a time per peer (waiting only briefly if another
                    # job holds it), then a transfer slot.
                    async with native_client.peer_slot(dl_username, timeout=PEER_BUSY_WAIT):
                        await _set_stage(job, job_id, desc, req, stage="waiting_slot", sources=len(batch),
                                         event="peer_lock", event_fields={"user": dl_username},
                                         description=f"Queued for slot: {desc} ({len(batch)} sources)")
                        t_slot = _time.monotonic()
                        async with transfer_sem:
                            if job_id in cancelled_jobs:
                                return candidate, "cancelled", None, "Cancelled by user"
                            _log_event(job, job_id, "transfer_slot", waited_s=round(_time.monotonic() - t_slot, 1))
                            await _set_stage(job, job_id, desc, req, stage="connecting", status="downloading",
                                             sources=len(batch), event="connecting",
                                             event_fields={"user": dl_username},
                                             description=many_desc)
                            try:
                                transfer = await native_client.download(dl_username, dl_filename, job_id=job_id)
                                log.info(f"[download] Multi-source queued: {dl_username}")
                            except Exception as e:
                                # Peer unreachable — no Transfer exists, so this is the one record.
                                # Not when our own server link is down: that's not the peer's fault.
                                if native_client.logged_in:
                                    await native_client.reputation.record_failure(dl_username)
                                return candidate, "failed", None, str(e)
                            _log_event(job, job_id, "requested", user=dl_username)
                            status, save_path, error = await poll_transfer(
                                native_client, transfer, job_id,
                                on_state=_on_state_for(dl_username, many_desc, sources=len(batch)))
                except PeerBusy:
                    return candidate, "failed", None, "Peer busy with another download"
                except asyncio.CancelledError:
                    # "first" strategy: another source won — stop this one for real
                    if transfer is not None:
                        native_client.transfers.abort(transfer, "Another source finished first", blame_peer=False)
                    raise
                # The transfer's own success/failure is recorded once by the
                # client's on_complete — not again here.
                if status == "completed":
                    return candidate, "completed", save_path, None
                return candidate, status, None, error

            if source_strategy == "first":
                # Race — keep first completed, cancel the rest
                tasks_map = {}
                for c in batch:
                    task = asyncio.create_task(try_source(c))
                    tasks_map[task] = c

                winner = None
                source_errors = []
                pending = set(tasks_map.keys())
                while pending:
                    done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        cand, status, save_path, error = task.result()
                        if status == "completed" and not winner:
                            winner = (cand, save_path)
                        elif status == "completed" and winner:
                            # Duplicate completed — remove the extra file
                            if save_path:
                                try:
                                    from pathlib import Path
                                    Path(save_path).unlink(missing_ok=True)
                                except Exception:
                                    pass
                        else:
                            await _peer_failed(source_errors, cand["username"], error or status, many_desc)
                    if winner:
                        for t in pending:
                            t.cancel()
                        break

                if winner:
                    cand, save_path = winner
                    short = cand["filename"].rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
                    await _set_stage(job, job_id, desc, req, stage="importing", sources=len(batch), event="importing",
                                     event_fields={"user": cand["username"], "bytes": _file_size(save_path)},
                                     description=many_desc)
                    track_id, fsize, import_err, peer_fault = await _import_or_fail(save_path)
                    if import_err:
                        log.warning(f"[download] {cand['username']} / {short}: {import_err}")
                        if peer_fault:
                            await native_client.reputation.record_failure(cand["username"])
                        job.status = "failed"
                        job.result = json.dumps({"message": import_err, "username": cand["username"], "filename": cand["filename"], "save_path": save_path, "file_size": fsize, "sources_tried": len(batch), "strategy": "first"})
                        job.tracks = json.dumps([_track_doc(req, "failed", prev=_prev_track(job), error=import_err)])
                        return
                    job.status = "completed"
                    job.result = json.dumps(with_funnel({"username": cand["username"], "filename": cand["filename"], "save_path": save_path, "file_size": fsize, "sources_tried": len(batch), "strategy": "first", "track_id": track_id}))
                    job.tracks = json.dumps([_track_doc(req, "downloaded", prev=_prev_track(job), username=cand["username"], filename=short, file_size=fsize, track_id=track_id)])
                else:
                    failed_users = [c["username"] for c in batch]
                    last_err = source_errors[-1]["error"] if source_errors else "unknown"
                    job.status = "failed"
                    job.result = json.dumps(with_funnel({"message": f"All {len(batch)} parallel sources failed", "last_error": last_err, "strategy": "first", "failed_sources": failed_users, "source_errors": source_errors}))
                    job.tracks = json.dumps([_track_doc(req, "failed", prev=_prev_track(job), error=last_err)])

            else:
                # "best" strategy — wait for all, keep highest quality. Failures are
                # only known once every source has settled, so they are saved then.
                results_all = await asyncio.gather(*[try_source(c) for c in batch], return_exceptions=True)
                completed = []
                source_errors = []
                for r in results_all:
                    if isinstance(r, Exception):
                        await _peer_failed(source_errors, "unknown", str(r), many_desc)
                        continue
                    cand, status, save_path, error = r
                    if status == "completed" and save_path:
                        completed.append((cand, save_path))
                    else:
                        await _peer_failed(source_errors, cand["username"], error or status, many_desc)

                best_cand = best_path = None
                track_id, fsize = None, 0

                if completed:
                    def _quality_score(item):
                        cand, path = item
                        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
                        fmt_scores = {"flac": 20, "wav": 18, "alac": 18, "mp3": 5, "m4a": 3, "ogg": 3, "opus": 3}
                        score = fmt_scores.get(ext, 0)
                        score += cand.get("bitRate", 0) or 0
                        score += (cand.get("size", 0) or 0) // (1024 * 1024)
                        return score

                    completed.sort(key=_quality_score, reverse=True)
                    await _set_stage(job, job_id, desc, req, stage="importing", sources=len(batch), event="importing",
                                     event_fields={"user": completed[0][0]["username"],
                                                   "bytes": _file_size(completed[0][1])},
                                     description=many_desc)

                    # Import in quality order and keep the first file that
                    # survives import. _quality_score ranks on the peer's
                    # *advertised* size, so a peer that over-states its file
                    # and then delivers 0 bytes sorts first — fall through to
                    # the next-best source instead of trusting the winner.
                    for cand, path in completed:
                        track_id, fsize, import_err, peer_fault = await _import_or_fail(path)
                        if not import_err:
                            best_cand, best_path = cand, path
                            break
                        log.warning(f"[download] {cand['username']}: {import_err}")
                        if peer_fault:
                            await native_client.reputation.record_failure(cand["username"])
                        await _peer_failed(source_errors, cand["username"], import_err, many_desc)

                    # Delete everything we didn't import (the winner has
                    # already been moved into the library by the importer)
                    for cand, path in completed:
                        if path == best_path:
                            continue
                        try:
                            from pathlib import Path
                            Path(path).unlink(missing_ok=True)
                        except Exception:
                            pass

                if best_cand:
                    short = best_cand["filename"].rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
                    job.status = "completed"
                    job.result = json.dumps(with_funnel({"username": best_cand["username"], "filename": best_cand["filename"], "save_path": best_path, "file_size": fsize, "sources_tried": len(batch), "sources_completed": len(completed), "strategy": "best", "track_id": track_id}))
                    job.tracks = json.dumps([_track_doc(req, "downloaded", prev=_prev_track(job), username=best_cand["username"], filename=short, file_size=fsize, track_id=track_id)])
                else:
                    failed_users = [c["username"] for c in batch]
                    last_err = source_errors[-1]["error"] if source_errors else "unknown"
                    job.status = "failed"
                    job.result = json.dumps(with_funnel({"message": f"All {len(batch)} parallel sources failed", "last_error": last_err, "strategy": "best", "failed_sources": failed_users, "source_errors": source_errors}))
                    job.tracks = json.dumps([_track_doc(req, "failed", prev=_prev_track(job), error=last_err)])

        elif candidates and native_ready:
            # === Sequential download (parallel_sources == 1, original behavior) ===
            import time as _time
            last_error = ""
            source_errors = []  # [{user, error, at}, ...] — also tracks[0].source_errors, live
            # (candidate, already_deferred). A candidate whose peer is busy with
            # another job's file is moved to the back once, so the job tries its
            # other sources instead of queueing behind someone else's transfer.
            work = [(c, False) for c in candidates]
            attempt = 0
            while work:
                candidate, deferred = work.pop(0)
                if job_id in cancelled_jobs:
                    job.status = "failed"
                    job.result = json.dumps({"error": "Cancelled by user"})
                    job.tracks = json.dumps([_track_doc(req, "failed", prev=_prev_track(job))])
                    break
                dl_username = candidate["username"]
                dl_filename = candidate["filename"]
                short_name = dl_filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] if dl_filename else ""

                # attempt/of stay 1-based and sticky; a busy-peer deferral gives the
                # number back below, so `of` is always len(candidates).
                attempt += 1
                attempt_label = f"attempt {attempt}/{len(candidates)}"
                queued_desc = f"Queued for slot: {desc} — {short_name}"
                live_desc = f"{desc} — {short_name} ({attempt_label})"
                await _set_stage(job, job_id, desc, req, stage="peer_lock", status="queued",
                                 username=dl_username, filename=short_name, attempt=attempt, of=len(candidates),
                                 queue_place=None,
                                 event="attempt",
                                 event_fields={"i": attempt, "of": len(candidates), "user": dl_username,
                                               "filename": short_name, "size": candidate.get("size"),
                                               "ext": candidate.get("extension")
                                               or (short_name.rsplit(".", 1)[-1].lower() if "." in short_name else None)},
                                 description=queued_desc)

                # One file at a time per peer (so two jobs never have two files
                # queued with the same uploader), then a transfer slot. Both are
                # released before the import below. A busy peer is waited on only
                # briefly; when it is the last thing left to try the wait repeats
                # in the same short steps so a cancel is noticed between them.
                try:
                    async with native_client.peer_slot(dl_username, timeout=PEER_BUSY_WAIT):
                        # Have the peer; now wait for one of our transfer slots.
                        await _set_stage(job, job_id, desc, req, stage="waiting_slot",
                                         event="peer_lock", event_fields={"user": dl_username},
                                         description=queued_desc)
                        t_slot = _time.monotonic()
                        async with transfer_sem:
                            if job_id in cancelled_jobs:
                                status, save_path, error = "cancelled", None, "Cancelled by user"
                            else:
                                _log_event(job, job_id, "transfer_slot",
                                           waited_s=round(_time.monotonic() - t_slot, 1))
                                await _set_stage(job, job_id, desc, req, stage="connecting", status="downloading",
                                                 username=dl_username, filename=short_name,
                                                 event="connecting", event_fields={"user": dl_username},
                                                 description=live_desc)
                                try:
                                    transfer = await native_client.download(dl_username, dl_filename, job_id=job_id)
                                    log.info(f"[download] Transfer queued: {dl_username} / {short_name}")
                                except Exception as e:
                                    # Peer unreachable before any Transfer exists: the one place this
                                    # job records a failure for a source that never got to transfer.
                                    timeout_like = isinstance(e, (asyncio.TimeoutError, ConnectionRefusedError, OSError))
                                    log.warning(f"[download] Could not reach {dl_username}: {e}")
                                    last_error = f"Connection {'timeout' if timeout_like else 'failed'}: {e}"
                                    # Only the peer's fault while our own server link is up; with it
                                    # down (reconnect in flight) no peer can be reached at all.
                                    if native_client.logged_in:
                                        await native_client.reputation.record_failure(dl_username)
                                    else:
                                        log.info(f"[download] Not blaming {dl_username}: our Soulseek server link is down")
                                    await _peer_failed(source_errors, dl_username, last_error, live_desc)
                                    continue

                                _log_event(job, job_id, "requested", user=dl_username)
                                status, save_path, error = await poll_transfer(
                                    native_client, transfer, job_id, on_state=_on_state_for(dl_username, live_desc))
                except PeerBusy:
                    attempt -= 1
                    if job_id in cancelled_jobs:
                        status, save_path, error = "cancelled", None, "Cancelled by user"
                    elif not deferred:
                        log.info(f"[download] {dl_username} is busy with another download — trying other sources first")
                        _log_event(job, job_id, "peer_busy", user=dl_username, deferred=True)
                        work.append((candidate, True))
                        continue
                    elif not work:
                        # Nothing else left: keep waiting for this peer, one short
                        # step at a time, checking for a cancel between steps.
                        work.append((candidate, True))
                        continue
                    else:
                        last_error = "Peer busy with another download"
                        await _peer_failed(source_errors, dl_username, last_error, queued_desc,
                                           event="peer_busy", deferred=False)
                        continue
                log.info(f"[download] Result: {dl_username} / {short_name} → {status} ({error or 'ok'})")

                if status == "completed":
                    await _set_stage(job, job_id, desc, req, stage="importing", event="importing",
                                     event_fields={"user": dl_username, "bytes": _file_size(save_path)},
                                     description=live_desc)
                    track_id, fsize, import_err, peer_fault = await _import_or_fail(save_path)
                    if import_err:
                        # The transfer "succeeded" but produced nothing usable. Blame
                        # the peer only for a broken file — a wrong song or a file no
                        # better than ours is our search's fault, not theirs.
                        log.warning(f"[download] {dl_username} / {short_name}: {import_err}")
                        if peer_fault:
                            await native_client.reputation.record_failure(dl_username)
                        last_error = import_err
                        await _peer_failed(source_errors, dl_username, import_err, live_desc)
                        continue
                    job.status = "completed"
                    job.result = json.dumps(with_funnel({"username": dl_username, "filename": dl_filename, "save_path": save_path, "file_size": fsize, "attempt": attempt, "sources_tried": len(source_errors) + 1, "track_id": track_id}))
                    job.tracks = json.dumps([_track_doc(req, "downloaded", prev=_prev_track(job), username=dl_username, filename=short_name, file_size=fsize, track_id=track_id)])
                    break
                elif status == "cancelled":
                    job.status = "failed"
                    job.result = json.dumps({"error": "Cancelled by user"})
                    job.tracks = json.dumps([_track_doc(req, "failed", prev=_prev_track(job))])
                    break
                else:
                    # Already recorded once by the client's on_complete.
                    last_error = error or status
                    await _peer_failed(source_errors, dl_username, last_error, live_desc)

            else:
                if candidates and job.status != "failed":
                    failed_users = [c["username"] for c in candidates]
                    job.status = "failed"
                    err_detail = last_error or "unknown"
                    job.result = json.dumps(with_funnel({
                        "message": f"All {len(candidates)} sources failed",
                        "last_error": err_detail,
                        "failed_sources": failed_users,
                        "source_errors": source_errors,
                    }))
                    job.tracks = json.dumps([_track_doc(req, "failed", prev=_prev_track(job), error=err_detail)])

    except Exception as e:
        log.warning(f"[download] Job {job_id} exception: {e}", exc_info=True)
        job.status = "failed"
        # Our own failure (e.g. "database is locked"), not the track's.
        job.result = json.dumps({"error": f"Internal error: {e}"})
    finally:
        if job_id in cancelled_jobs and job.status != "completed":
            job.status = "failed"
            job.result = json.dumps({"error": "Cancelled by user"})
        cancelled_jobs.discard(job_id)
        job.finished_at = datetime.utcnow()
        if outcome and job.status == "completed":
            try:
                job.result = json.dumps({**json.loads(job.result or "{}"), **outcome})
            except (TypeError, ValueError):
                pass
        if job.status == "completed":
            # The row keeps the imported file's size as progress/total (capped to
            # the INTEGER column); the WS message below still says 1/1.
            try:
                fsize = int((json.loads(job.result or "{}") or {}).get("file_size") or 0)
            except (TypeError, ValueError, AttributeError):
                fsize = 0
            job.progress = job.total = min(max(fsize, 0), 2**31 - 1)
        try:
            _terminal_event(job, job_id)
        except Exception as e:
            log.debug(f"[download] Could not log the end of {job_id}: {e}")
        last_stage = (_prev_track(job) or {}).get("stage")
        # Capture status before save (avoid reading from detached ORM object later)
        final_status = job.status
        await _save_job()
        _forget_stage(job_id)
        _timelines.pop(job_id, None)
        await broadcast_job_update({
            "id": job_id, "type": "download", "status": final_status, "progress": 1, "total": 1,
            "description": desc, **job_outcome(final_status, job.result, job.tracks),
            "card": getattr(job, "card", None), "stage": last_stage,
        })
        # The file has been imported (moved into the library) or rejected by
        # now — drop this job's staging folder and anything a loser left in it.
        try:
            _client = get_client()
            if _client is not None:
                _client.transfers.discard_job(job_id)
        except Exception as e:
            log.debug(f"[download] Staging cleanup skipped for {job_id}: {e}")

async def _delegate_download_to_web(artist: str, track: str, job_id: str | None, source: str | None, target_track_id: str | None = None,
                                     *, album: str | None = None, expected_duration: int | None = None, wait: bool = True,
                                     strict_duration: bool = False, origin: str | None = None) -> str | None:
    """Delegate a download to the web process, which owns the native Soulseek
    client. The arq worker has no native client of its own (it can only bind the
    listen port in one process), so any download it initiates must run where the
    client lives. wait=True waits for the download to finish (enqueue_download stays
    synchronous); wait=False only waits for the web to create the job row."""
    import httpx
    from backend.config import get_settings
    job_id = job_id or str(uuid.uuid4())
    try:
        port = get_settings().server.port
    except Exception:
        port = 3000
    url = f"http://127.0.0.1:{port}/api/download/internal-run"
    try:
        # Waiting: the read timeout should cover a slow-but-successful download
        # (search + queue wait + transfer); a longer one is read back from the job
        # row as "still running" (outcome unknown), never as a failure. Not waiting:
        # the web only dedups, checks the library and writes the row.
        timeout = httpx.Timeout(connect=10.0, read=1800.0 if wait else 60.0, write=30.0, pool=None)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                url, json={"artist": artist, "track": track, "album": album, "job_id": job_id,
                           "source": source, "target_track_id": target_track_id,
                           "expected_duration": expected_duration, "wait": wait,
                           "strict_duration": strict_duration, "origin": origin}
            )
            if resp.status_code == 200:
                body = resp.json()
                if body.get("blacklisted"):
                    raise BlacklistedTrack(body.get("reason") or "Blacklisted")
                return body.get("job_id", job_id)
            raise RuntimeError(f"web returned {resp.status_code}: {resp.text[:200]}")
    except BlacklistedTrack:
        raise  # a refusal, not a delegation failure: no failed row
    except Exception as e:
        log.error(f"[download] Worker→web delegation failed for {artist} — {track}: {e}")
        await _record_delegation_failure(job_id, artist, track, source, str(e))
        return job_id


async def _record_delegation_failure(job_id: str, artist: str, track: str, source: str | None, err: str) -> None:
    """Persist a clear failed job so a delegation failure isn't silent/opaque."""
    try:
        card = f"dl:{source}" if source else "dl"
        msg = f"Soulseek download backend unreachable: {err}"
        async with async_session() as sess:
            row = (await sess.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
            # Don't clobber a job the web already owns — a read-timeout can fire
            # while the web is still actively downloading that same job_id.
            if row is not None and row.status not in ("pending",):
                return
            tracks = json.dumps([_track_doc(None, "failed", artist=artist, track=track)])
            result = json.dumps({"error": msg, "last_error": msg})
            if row:
                row.status = "failed"
                row.finished_at = datetime.utcnow()
                row.result = result
                row.tracks = tracks
            else:
                sess.add(Job(
                    id=job_id, type="download", card=card, status="failed",
                    started_at=datetime.utcnow(), finished_at=datetime.utcnow(),
                    result=result, tracks=tracks,
                ))
            await sess.commit()
    except Exception as e:
        log.debug(f"[download] Could not record delegation failure: {e}")


# Sources that fetch *new* music automatically. Before downloading for these, check the
# library: 159 "similar" downloads were fetched only for the importer to discard them as
# duplicates of lossless files already there.
_LIBRARY_CHECK_SOURCES = {"similar", "discovery", "recommendation", "playlist"}
_LOSSLESS = {"flac", "wav", "alac", "aiff"}


async def _already_have_lossless(artist: str, track: str) -> bool:
    """True when the library already holds this exact title by this artist in a
    lossless format. Deliberately strict — an exact (case-insensitive) title match, so
    'Song (Remix)' never counts as 'Song' — and lossy copies still download, because
    the importer upgrades them in place when the new file is better."""
    from backend.services.scanner import _find_existing_track
    async with async_session() as sess:
        existing = await _find_existing_track(sess, track, artist)
    if existing is None:
        return False
    same_title = (existing.title or "").strip().lower() == (track or "").strip().lower()
    return same_title and (existing.format or "").lower() in _LOSSLESS


# Downloads started with wait=False run as tasks of their own; keep a reference so
# the event loop doesn't garbage-collect one mid-flight.
_background_downloads: set[asyncio.Task] = set()


async def _create_download_job(artist: str, track: str, job_id: str | None, source: str | None,
                               target_track_id: str | None, expected_duration: int | None,
                               strict_duration: bool = False, album: str | None = None,
                               origin: str | None = None):
    """Write a download job's row and register it live. Returns what
    _run_download_job needs: (job_id, desc, request, search semaphore, initial status)."""
    job_id = job_id or str(uuid.uuid4())
    desc = f"{artist} — {track}"
    dl_req = DownloadRequest(artist=artist, track=track, album=album, source=source, target_track_id=target_track_id,
                             expected_duration=expected_duration, strict_duration=strict_duration, origin=origin)
    sem = _get_semaphore()

    # Create job with short-lived session (don't hold connection while waiting for semaphore)
    initial_status = "pending" if sem.locked() else "running"
    card = f"dl:{source}" if source else "dl"
    # Register the job as live before the row is committed, so a cancel that
    # arrives between the commit and the registration is still seen.
    live_download_jobs.add(job_id)
    try:
        tracks_json, log_json = _initial_row(job_id, dl_req, card, initial_status)
        async with async_session() as sess:
            job = Job(
                id=job_id, type="download", card=card, status=initial_status,
                started_at=datetime.utcnow(), tracks=tracks_json, log=log_json,
            )
            sess.add(job)
            await sess.commit()
    except Exception:
        _job_done(job_id)
        raise
    # The row's first job_update (sent here rather than when its task starts, so it
    # can carry the stage fields of the row just written).
    await broadcast_job_update(_job_payload(job, job_id, f"Queued: {desc}" if initial_status == "pending" else desc,
                                            _prev_track(job)))
    return job_id, desc, dl_req, sem, initial_status


async def _run_download_job(job_id: str, desc: str, dl_req: DownloadRequest, sem: asyncio.Semaphore,
                            initial_status: str) -> None:
    """Wait for a search slot, then run the download to its end. Always forgets the
    job's in-memory flags when it returns."""
    slot = _SearchSlot(sem)
    try:
        import time as _time
        t0 = _time.monotonic()
        await slot.acquire()
        async with async_session() as sess:
            job = (await sess.execute(select(Job).where(Job.id == job_id))).scalar_one()
            sess.expunge(job)
        # job is now detached — _do_download_inner uses its own short-lived sessions
        was_pending = job.status == "pending"
        if was_pending:
            job.status = "running"
        if job.status == "running":
            # One save: status running (when it was pending) + stage searching.
            try:
                await _set_stage(job, job_id, desc, dl_req, stage="searching", status="pending", event="search_slot",
                                 event_fields={"waited_s": round(_time.monotonic() - t0, 1)},
                                 description=desc, broadcast=was_pending)
            except Exception as e:
                # _do_download_inner retries the write inside its own error handling.
                log.warning(f"[download] Could not mark {job_id} searching: {e}")
                _forget_stage(job_id)
        await _do_download_inner(None, job, job_id, desc, dl_req, search_slot=slot)
    finally:
        slot.release()
        _job_done(job_id)


async def _run_download_job_detached(job_id: str, *args) -> None:
    """_run_download_job as a task nobody awaits: a failure before the download
    proper (which handles its own) still leaves a failed row, not a row stuck
    pending that a polling batch would wait on until its deadline."""
    try:
        await _run_download_job(job_id, *args)
    except Exception as e:
        log.warning(f"[download] Background job {job_id} failed: {e}", exc_info=True)
        _forget_stage(job_id)
        _timelines.pop(job_id, None)
        try:
            async with async_session() as sess:
                row = (await sess.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
                if row is not None and row.status in ("pending", "running"):
                    row.status = "failed"
                    row.finished_at = datetime.utcnow()
                    row.result = json.dumps({"error": f"Internal error: {e}"[:500]})
                    await sess.commit()
        except Exception as e2:
            log.debug(f"[download] Could not mark background job {job_id} failed: {e2}")


async def enqueue_download(artist: str, track: str, job_id: str | None = None, source: str | None = None, target_track_id: str | None = None,
                           *, album: str | None = None, expected_duration: int | None = None, wait: bool = True,
                           strict_duration: bool = False, origin: str | None = None) -> str | None:
    """Create an individual download job with semaphore queuing. Returns job_id, or
    None when an automatic download was skipped because the library already has it.
    Raises BlacklistedTrack (no job row) when the artist or track is blacklisted —
    never None for that, which callers read as "already in the library".

    wait=True (the default) returns once the download has finished. wait=False
    returns as soon as the job row exists and runs the download as a background
    task; the caller reads the outcome from the job row."""
    # Dedup: skip if same artist+track already pending/running
    async with async_session() as check_sess:
        existing = await _find_existing_download(check_sess, artist, track)
        if existing:
            log.info(f"[download] Dedup: {artist} — {track} already in job {existing}")
            return existing

    # Blacklist: before the library pre-check and the worker→web delegation, so
    # every automatic path (scheduler, bulk, playlist, retries) honours it.
    async with async_session() as bl_sess:
        why = await is_blacklisted(bl_sess, artist, track)
    if why:
        log.info(f"[download] Skip ({source}): {artist} — {track} is blacklisted ({why})")
        raise BlacklistedTrack(why)

    if source in _LIBRARY_CHECK_SOURCES and not target_track_id:
        try:
            if await _already_have_lossless(artist, track):
                log.info(f"[download] Skip ({source}): {artist} — {track} already in library as lossless")
                return None
        except Exception as e:
            log.debug(f"[download] Library pre-check failed for {artist} — {track}: {e}")

    # The native Soulseek client lives in the web process; the arq worker has none.
    # If this process can't download natively, delegate to the web.
    from backend.soulseek import get_client
    if get_client() is None:
        return await _delegate_download_to_web(artist, track, job_id, source, target_track_id,
                                               album=album, expected_duration=expected_duration, wait=wait,
                                               strict_duration=strict_duration, origin=origin)

    job_id, desc, dl_req, sem, initial_status = await _create_download_job(
        artist, track, job_id, source, target_track_id, expected_duration, strict_duration, album=album,
        origin=origin)
    if not wait:
        task = asyncio.create_task(_run_download_job_detached(job_id, desc, dl_req, sem, initial_status))
        _background_downloads.add(task)
        task.add_done_callback(_background_downloads.discard)
        return job_id
    await _run_download_job(job_id, desc, dl_req, sem, initial_status)
    return job_id


class InternalDownloadRequest(BaseModel):
    artist: str
    track: str
    album: str | None = None
    job_id: str | None = None
    source: str | None = None
    target_track_id: str | None = None
    expected_duration: int | None = None
    strict_duration: bool = False
    # False: create the job, start it in the background and answer at once (the
    # worker's batches poll the job rows instead of holding a request per download).
    wait: bool = True
    origin: str | None = None


@router.post("/internal-run")
async def internal_run_download(req: InternalDownloadRequest):
    """Internal: run a download IN THIS process, which owns the native Soulseek
    client. Called by the arq worker (via _delegate_download_to_web) to perform
    downloads it cannot run itself. Localhost-only by deployment. With wait=false
    it answers once the job row exists and the download runs in the background."""
    try:
        jid = await enqueue_download(req.artist, req.track, job_id=req.job_id, source=req.source,
                                     target_track_id=req.target_track_id, album=req.album,
                                     expected_duration=req.expected_duration, wait=req.wait,
                                     strict_duration=req.strict_duration, origin=req.origin)
    except BlacklistedTrack as e:
        # The worker re-raises this from _delegate_download_to_web (no failed row).
        return {"job_id": None, "blacklisted": True, "reason": e.reason}
    return {"job_id": jid}


@router.post("/bulk")
async def bulk_download(req: BulkDownloadRequest, background_tasks: BackgroundTasks):
    """Download multiple tracks as individual download jobs."""
    queue = []
    for t in req.tracks:
        artist = t.get("artist", "")
        track = t.get("track", "")
        album = t.get("album")
        if artist and track:
            queue.append({"artist": artist, "track": track, "album": album})

    if queue:
        background_tasks.add_task(_process_bulk_download_queue, queue, req.source)

    return {"ok": True, "total": len(queue)}


async def _process_bulk_download_queue(queue: list[dict], source: str | None = None):
    """Run bulk downloads through the tracked path (backoff, duration gate, outcome
    recorded) with bounded concurrency; the search/transfer queues gate the rest."""
    from backend.services.auto_download import download_tracked_many
    await download_tracked_many(queue, source=source)


class CancelTransferRequest(BaseModel):
    username: str
    filename: str


@router.post("/cancel-transfer")
async def cancel_transfer(req: CancelTransferRequest):
    """Cancel an active transfer in the native Soulseek client."""
    from backend.soulseek import get_client
    client = get_client()
    if not client:
        return {"error": "Native client not available"}
    transfer = client.transfers.get_transfer(req.username, req.filename)
    if not transfer:
        return {"error": "Transfer not found"}
    client.transfers.abort(transfer, "Cancelled by user", blame_peer=False)
    from backend.api.websocket import broadcast_transfer_progress
    await broadcast_transfer_progress(client.transfers.get_all_transfers())
    return {"ok": True}



def _whole(x: float):
    """x as an int when it is a whole number (6.0 -> 6), else rounded to 2 places."""
    return int(x) if float(x).is_integer() else round(x, 2)


def download_limits() -> dict:
    """Every limit the Downloads page shows (DC-12 `limits`), read from the settings
    at call time plus the code constants, so the page never hard-codes a number."""
    from backend.config import get_settings
    from backend.soulseek import transfer as _tr
    from backend.soulseek import client as _cl
    from backend.services import download_attempts as _da
    cfg = get_settings().soulseek
    sig = inspect.signature(poll_transfer).parameters
    return {
        "transfer_slots": max(1, int(getattr(cfg, "max_concurrent_downloads", 4))),
        "search_slots": max(1, int(getattr(cfg, "max_concurrent_searches", 3))),
        "searches_per_minute": max(1, int(getattr(cfg, "searches_per_minute", 15))),
        "search_min_interval_s": max(0.0, float(getattr(cfg, "search_min_interval_s", 3.0))),
        "transfer_max_minutes": max(1, int(getattr(cfg, "transfer_max_minutes", 30))),
        "parallel_sources": max(1, int(getattr(cfg, "parallel_sources", 1))),
        "peer_connect_s": _cl.DEFAULT_PEER_TIMEOUT,
        "peer_busy_wait_s": PEER_BUSY_WAIT,
        "peer_queue_s": sig["queue_timeout"].default,
        "peer_queue_sweep_s": _tr.QUEUE_TIMEOUT_SECONDS,
        "connected_no_data_s": _tr.CONNECTED_TIMEOUT_SECONDS,
        "stall_s": sig["stall_timeout"].default,
        "search_timeout_s": _cl.DEFAULT_SEARCH_TIMEOUT,
        "terminal_keep_s": _tr.TERMINAL_KEEP_SECONDS,
        "reconnect_wait_s": RECONNECT_WAIT_S,
        "backoff_days": list(_da.BACKOFF),
        "retired_days": _da.RETIRED_DAYS,
        "backoff_slack_h": _whole(_da.SLACK.total_seconds() / 3600),
        "upgrade_max_scans": UPGRADE_MAX_SCANS,
    }


def _pacer_of(client) -> dict:
    """client.pacer_status(), or zeros when the client has none / it fails."""
    try:
        p = client.pacer_status() if client is not None and hasattr(client, "pacer_status") else None
    except Exception as e:
        log.debug(f"[download] pacer_status failed: {e}")
        p = None
    p = p or {}
    return {"waiting": int(p.get("waiting") or 0), "sent_last_minute": int(p.get("sent_last_minute") or 0),
            "next_slot_in_s": float(p.get("next_slot_in_s") or 0.0)}


async def _db_active_counts() -> dict:
    """pending/running download rows (one GROUP BY), so a restart — counters empty,
    rows still pending — is visible. Zeros when the database can't be read."""
    out = {"db_pending": 0, "db_running": 0}
    try:
        async with async_session() as s:
            rows = (await s.execute(
                select(Job.status, func.count(Job.id))
                .where(Job.type == "download", Job.status.in_(["pending", "running"]))
                .group_by(Job.status)
            )).all()
        for st, n in rows:
            out[f"db_{st}"] = int(n)
    except Exception as e:
        log.debug(f"[download] stage snapshot DB counts failed: {e}")
    return out


async def stage_snapshot(client, transfers: list[dict] | None = None, pacer: dict | None = None) -> dict:
    """Stage counts over ALL active download jobs (DC-12 `stages`): the in-memory
    counters from _set_stage, with connecting / queued_at_peer / transferring taken
    from the live transfer table instead, pacer_waiting from the search pacer,
    `live` = the sum of the live stages, plus db_pending / db_running."""
    stages = {k: int(stage_counts.get(k, 0)) for k in STAGES}
    if transfers is None:
        try:
            transfers = client.transfers.get_all_transfers() if client is not None else []
        except Exception:
            transfers = []
    from_transfers = {"queued_at_peer": 0, "connecting": 0, "transferring": 0}
    for t in transfers or []:
        st = _TRANSFER_STAGE.get(str(t.get("state") or ""))
        if st:
            from_transfers[st] += 1
    stages.update(from_transfers)
    live = sum(stages[k] for k in STAGES)
    pacer = pacer if pacer is not None else _pacer_of(client)
    ordered = {k: stages[k] for k in STAGES[:2]}
    ordered["pacer_waiting"] = int(pacer.get("waiting") or 0)
    ordered.update({k: stages[k] for k in STAGES[2:]})
    ordered["live"] = live
    ordered.update(await _db_active_counts())
    return ordered


def _soulseek_block(client) -> dict:
    """The connection facts the Downloads page's chip needs (DC-12 `soulseek`)."""
    import time
    if client is None:
        return {"connected": False, "username": None, "uptime_seconds": 0, "reconnects": 0,
                "disconnected_since": None, "reconnecting": False}
    server = getattr(client, "server", None)
    since = getattr(server, "connected_since", None)
    connected = bool(getattr(client, "logged_in", False))
    return {
        "connected": connected,
        "username": getattr(client, "username", None),
        "uptime_seconds": round(time.time() - since) if (since and connected) else 0,
        "reconnects": int(getattr(server, "total_reconnects", 0) or 0),
        "disconnected_since": getattr(server, "disconnected_since", None),
        "reconnecting": bool(getattr(server, "reconnecting", False)),
    }


def _aggregate_speed(transfers: list[dict]) -> int:
    """Summed speed of the transferring downloads (as soulseek-stats computes it)."""
    return round(sum(t.get("speed", 0) or 0 for t in transfers if t.get("state") == "transferring"))


@router.get("/status")
async def download_status():
    """Get current download status from native Soulseek client, plus the limits,
    stage counts, pacer and connection facts the Downloads page shows."""
    from backend.soulseek import get_client
    client = get_client()
    limits = download_limits()
    if client:
        downloads = client.transfers.get_all_transfers()
        pacer = _pacer_of(client)
        return {
            "downloads": downloads,
            "uploads": client.transfers.get_all_uploads(),
            "logged_in": client.logged_in,
            "limits": limits,
            "stages": await stage_snapshot(client, downloads, pacer),
            "aggregate_speed": _aggregate_speed(downloads),
            "pacer": pacer,
            "soulseek": _soulseek_block(client),
        }
    pacer = _pacer_of(None)
    return {"downloads": [], "uploads": [], "logged_in": False,
            "limits": limits, "stages": await stage_snapshot(None, [], pacer),
            "aggregate_speed": 0, "pacer": pacer, "soulseek": _soulseek_block(None)}


@router.get("/soulseek-stats")
async def soulseek_stats():
    """Get Soulseek client stats — connection, shares, peers, transfers."""
    from backend.soulseek import get_client
    from backend.soulseek.shares import get_share_counts

    client = get_client()
    num_dirs, num_files = get_share_counts()

    import time

    if not client:
        return {
            "connected": False,
            "username": None,
            "peers": 0,
            "shared_folders": num_dirs,
            "shared_files": num_files,
            "listen_port": None,
            "uptime_seconds": 0,
            "reconnects": 0,
            "active_searches": 0,
            "active_transfers": 0,
            "queued_transfers": 0,
            "completed_transfers": 0,
            "failed_transfers": 0,
            "total_bytes_transferred": 0,
            "aggregate_speed": 0,
            "reputation": {"tracked_peers": 0, "peers": []},
            "uploads": {"active": 0, "queued": 0, "completed": 0, "failed": 0, "bytes_sent": 0, "speed": 0},
            "disconnected_since": None,
            "reconnecting": False,
            "pacer_waiting": 0,
            "session": {"completed": 0, "failed": 0, "bytes": 0},
        }

    transfers = client.transfers.get_all_transfers()
    active = sum(1 for t in transfers if t.get("state") in ("transferring", "connected"))
    queued = sum(1 for t in transfers if t.get("state") in ("requested", "queued"))
    completed = sum(1 for t in transfers if t.get("state") == "completed")
    failed = sum(1 for t in transfers if t.get("state") in ("failed", "denied"))
    total_bytes = sum(t.get("received_bytes", 0) for t in transfers)
    agg_speed = sum(t.get("speed", 0) for t in transfers if t.get("state") == "transferring")

    # Uploads we serve to peers (share_library) — kept apart from the download counts.
    uploads = client.transfers.get_all_uploads()
    upload_stats = {
        "active": sum(1 for u in uploads if u.get("state") in ("transferring", "connected")),
        "queued": sum(1 for u in uploads if u.get("state") in ("requested", "queued")),
        # Session totals (finished entries are swept from the list after a minute).
        "completed": client.uploads.totals["completed"],
        "failed": client.uploads.totals["failed"],
        "bytes_sent": client.uploads.totals["bytes_sent"]
        + sum(u.get("received_bytes", 0) for u in uploads if u.get("state") == "transferring"),
        "speed": round(sum(u.get("speed", 0) for u in uploads if u.get("state") == "transferring")),
    }

    uptime = 0.0
    if client.server.connected_since:
        uptime = time.time() - client.server.connected_since

    return {
        "connected": client.logged_in,
        "username": client.username,
        "peers": len(client.peers),
        "shared_folders": num_dirs,
        "shared_files": num_files,
        "listen_port": client.server.listen_port,
        "uptime_seconds": round(uptime),
        "reconnects": client.server.total_reconnects,
        "active_searches": len(client._search_events),
        "active_transfers": active,
        "queued_transfers": queued,
        "completed_transfers": completed,
        "failed_transfers": failed,
        "total_bytes_transferred": total_bytes,
        "aggregate_speed": round(agg_speed),
        "reputation": client.reputation.get_summary(),
        "uploads": upload_stats,
        "disconnected_since": getattr(client.server, "disconnected_since", None),
        "reconnecting": bool(getattr(client.server, "reconnecting", False)),
        "pacer_waiting": _pacer_of(client)["waiting"],
        "session": {k: int((getattr(client, "session_totals", None) or {}).get(k, 0) or 0)
                    for k in ("completed", "failed", "bytes")},
    }


@router.get("/soulseek-stats/history")
async def soulseek_stats_history(hours: int = 24, db: AsyncSession = Depends(get_db)):
    """Get historical Soulseek stats for charting."""
    from backend.models.stats import SoulseekSnapshot
    from datetime import timedelta

    cutoff = datetime.utcnow() - timedelta(hours=hours)
    result = await db.execute(
        select(SoulseekSnapshot)
        .where(SoulseekSnapshot.timestamp >= cutoff)
        .order_by(SoulseekSnapshot.timestamp)
    )
    snapshots = result.scalars().all()
    return [
        {
            "timestamp": s.timestamp.isoformat(),
            "connected": s.connected,
            "peers": s.peers,
            "active_transfers": s.active_transfers,
            "completed_transfers": s.completed_transfers,
            "failed_transfers": s.failed_transfers,
            "queued_transfers": s.queued_transfers,
            "bytes_transferred": s.bytes_transferred,
            "speed": s.speed,
            "active_searches": s.active_searches,
        }
        for s in snapshots
    ]


@router.post("/reset-reputation")
async def reset_reputation():
    """Clear all peer reputation data (cooldowns + scores)."""
    from backend.soulseek import get_client

    client = get_client()
    if not client:
        return {"cleared": 0}

    count = await client.reputation.reset_all()
    return {"cleared": count}


# --- Blacklist CRUD ---

class BlacklistEntry(BaseModel):
    artist: str
    track: str | None = None
    reason: str | None = None


@router.get("/blacklist")
async def list_blacklist(db: AsyncSession = Depends(get_db)):
    """Get all blacklist entries."""
    result = await db.execute(
        select(DownloadBlacklist).order_by(DownloadBlacklist.artist, DownloadBlacklist.track)
    )
    entries = result.scalars().all()
    return [
        {
            "id": e.id,
            "artist": e.artist,
            "track": e.track,
            "reason": e.reason,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in entries
    ]


@router.post("/blacklist")
async def add_to_blacklist(entry: BlacklistEntry, db: AsyncSession = Depends(get_db)):
    """Add an artist or track to the download blacklist."""
    bl = DownloadBlacklist(
        id=str(uuid.uuid4()),
        artist=entry.artist.strip(),
        track=entry.track.strip() if entry.track else None,
        reason=entry.reason,
    )
    db.add(bl)
    await db.commit()
    return {"id": bl.id, "artist": bl.artist, "track": bl.track}


@router.delete("/blacklist/{entry_id}")
async def remove_from_blacklist(entry_id: str, db: AsyncSession = Depends(get_db)):
    """Remove a blacklist entry."""
    result = await db.execute(select(DownloadBlacklist).where(DownloadBlacklist.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        return {"error": "Not found"}
    await db.delete(entry)
    await db.commit()
    return {"ok": True}
