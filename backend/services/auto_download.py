"""One tracked path for every automatic download.

Every download Zonik starts on its own (scheduled discovery, recommendations, bulk
and retry routes, playlist import, quality upgrades) goes through here so that

- a track whose search failed recently is skipped (download_attempts backoff),
- candidates are gated on the song's real length when it is known (Last.fm),
- the outcome is read back from the job row with one tri-state rule and recorded.

The manual single-track /api/download/trigger stays outside: a user picking a
song by hand is never refused because an automatic run failed to find it.

Upgrades (source "upgrade") keep their own per-track accounting in track_upgrades,
so they neither consult nor feed download_attempts.

Two ways to use it:
- download_tracked(): submit, wait for the job to finish, read and record the outcome.
- submit_tracked() + finish_tracked(): submit without waiting (the worker's batches
  poll the job rows themselves and finish each one as it becomes terminal).
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid

from sqlalchemy import select

from backend.database import async_session
from backend.models.job import Job
from backend.services.download_attempts import attempt_key, in_backoff, record_outcome

log = logging.getLogger(__name__)

# Sources whose attempts are tracked elsewhere (track_upgrades), not in download_attempts.
UNTRACKED_SOURCES = {"upgrade"}

# Job statuses that mean the download has not finished yet.
RUNNING_STATUSES = ("pending", "running", "queued", "downloading")

# Last.fm track length per attempt key, seconds (None = unknown). Small and in-process:
# the same track comes up again within a batch or the next night's run.
_duration_cache: dict[str, int | None] = {}
_DURATION_CACHE_MAX = 2000


def is_infra_error(err: str | None) -> bool:
    """Failures that say nothing about whether the track can be found (Soulseek down or
    not logged in, delegation to the web process failed, user cancelled).

    Only the exact messages Zonik itself writes count. A substring match on
    "cancelled" or "not connected" would also catch a peer's own refusal reason
    ("Cancelled" is a standard Soulseek denial) or an OS error text, and those are
    real per-track failures that must enter backoff."""
    e = (err or "").strip()
    return (
        e.startswith("Soulseek download backend unreachable")
        or e.startswith("Soulseek server not connected")
        or e == "Cancelled by user"
    )


async def download_job_outcome(job_id: str | None, *, session_factory=None) -> tuple[bool | None, str | None]:
    """Read a download job. Returns (ok, error): ok=True when it completed (or enqueue
    skipped it because the library already has it), False when the search/transfer failed,
    None when the outcome is unknown: still pending/running, or an infrastructure failure
    (backend unreachable / not connected / cancelled) that must not count against the track."""
    if job_id is None:
        return True, None  # enqueue_download: library already has it
    factory = session_factory or async_session
    try:
        async with factory() as jdb:
            row = (await jdb.execute(select(Job.status, Job.result).where(Job.id == job_id))).first()
    except Exception as e:
        return None, f"could not read job: {e}"
    if row is None:
        return False, "download job not found"
    status, result = row
    payload: dict = {}
    if result:
        try:
            payload = json.loads(result)
            if not isinstance(payload, dict):
                payload = {}
        except (ValueError, TypeError):
            payload = {"message": str(result)[:300]}
    if status == "completed":
        return True, None  # payload carries track_id or already_in_library
    if status in RUNNING_STATUSES:
        return None, None
    err = str(payload.get("last_error") or payload.get("error") or payload.get("message") or f"job {status}")[:500]
    if is_infra_error(err):
        return None, err
    return False, err


async def unsettled_jobs(job_ids: list[str]) -> set[str]:
    """The ids among job_ids whose row is still pending/running. A missing row counts
    as settled (download_job_outcome reports it as not found)."""
    if not job_ids:
        return set()
    async with async_session() as db:
        rows = (await db.execute(
            select(Job.id).where(Job.id.in_(job_ids), Job.status.in_(RUNNING_STATUSES))
        )).all()
    return {r[0] for r in rows}


async def lookup_duration(artist: str, track: str) -> int | None:
    """The song's length in seconds from Last.fm track.getInfo, or None when unknown.
    0 or a failed lookup means no duration gate. Cached per attempt key."""
    key = attempt_key(artist, track)
    if key in _duration_cache:
        return _duration_cache[key]
    try:
        from backend.services.lastfm import get_track_info
        info = await get_track_info(artist, track)
    except Exception as e:
        log.debug(f"[auto-download] Last.fm duration lookup failed for {artist} — {track}: {e}")
        return None  # transient: don't cache, try again next time
    ms = 0
    try:
        ms = int((info or {}).get("duration_ms") or 0)
    except (TypeError, ValueError):
        ms = 0
    secs = int(round(ms / 1000)) if ms > 0 else None
    if len(_duration_cache) >= _DURATION_CACHE_MAX:
        _duration_cache.clear()
    _duration_cache[key] = secs
    return secs


def _tracked(source: str | None) -> bool:
    return source not in UNTRACKED_SOURCES


async def submit_tracked(
    artist: str, track: str, *, source: str | None, target_track_id: str | None = None,
    expected_duration: int | None = None, skip_in_backoff: bool = True,
    job_id: str | None = None, wait: bool = True,
) -> dict:
    """Start one automatic download. Returns {job_id, skipped, error}:

    - skipped: why it was not started (backoff), job_id None.
    - job_id None and no skip: enqueue skipped it because the library already has it.
    - error: enqueue_download raised (job_id is the id it was given).

    With wait=True (the default) this returns once the download has finished, as
    enqueue_download always did; with wait=False it returns once the job row exists."""
    from backend.api.download import enqueue_download

    if skip_in_backoff and _tracked(source):
        try:
            async with async_session() as bo_db:
                why = await in_backoff(bo_db, artist, track)
            if why:
                log.info(f"[auto-download] Skip {artist} — {track}: {why}")
                return {"job_id": None, "skipped": why, "error": None}
        except Exception as e:
            log.debug(f"[auto-download] backoff check failed for {artist} — {track}: {e}")

    if expected_duration is None and not target_track_id:
        expected_duration = await lookup_duration(artist, track)

    job_id = job_id or str(uuid.uuid4())
    try:
        returned = await enqueue_download(artist, track, job_id=job_id, source=source,
                                          target_track_id=target_track_id,
                                          expected_duration=expected_duration, wait=wait)
    except Exception as e:
        log.warning(f"[auto-download] Failed {artist} — {track}: {e}")
        return {"job_id": job_id, "skipped": None, "error": str(e)[:500]}
    return {"job_id": returned, "skipped": None, "error": None}


async def finish_tracked(
    job_id: str | None, artist: str, track: str, source: str | None, *,
    enqueue_error: str | None = None,
) -> dict:
    """Read a submitted download's outcome and record it in download_attempts.

    Returns {artist, track, job_id, ok, error, skipped}. ok is True (done), False
    (the search/transfer failed) or None (unknown: still running, or an infrastructure
    failure) — None is never recorded."""
    ok, err = await download_job_outcome(job_id)
    if ok is None and enqueue_error:
        ok, err = (None if is_infra_error(enqueue_error) else False), enqueue_error
    if ok is not None and _tracked(source):
        try:
            async with async_session() as rec_db:
                await record_outcome(rec_db, artist, track, source, ok, err, job_id)
        except Exception as e:
            log.debug(f"[auto-download] could not record outcome for {artist} — {track}: {e}")
    return {
        "artist": artist, "track": track, "job_id": job_id,
        "ok": ok, "error": err if ok is not True else None, "skipped": None,
    }


async def download_tracked(
    artist: str, track: str, *, source: str | None, target_track_id: str | None = None,
    expected_duration: int | None = None, skip_in_backoff: bool = True,
    job_id: str | None = None,
) -> dict:
    """Submit one automatic download, wait for it, then read and record its outcome.

    Returns {artist, track, job_id, ok, error, skipped}; a skipped download (backoff)
    has ok=None and skipped=<reason>."""
    sub = await submit_tracked(
        artist, track, source=source, target_track_id=target_track_id,
        expected_duration=expected_duration, skip_in_backoff=skip_in_backoff, job_id=job_id,
    )
    if sub["skipped"]:
        return {"artist": artist, "track": track, "job_id": None,
                "ok": None, "error": None, "skipped": sub["skipped"]}
    return await finish_tracked(sub["job_id"], artist, track, source, enqueue_error=sub["error"])


async def download_tracked_many(
    items: list[dict], *, source: str | None = None, concurrency: int = 4,
    skip_in_backoff: bool = True,
) -> list[dict]:
    """download_tracked for each {artist, track[, source, expected_duration]} item, at most `concurrency`
    at a time (the search/transfer queues gate the real download concurrency).
    Items that normalise to the same attempt key are downloaded once. Never raises."""
    seen: set[str] = set()
    unique: list[dict] = []
    for it in items:
        artist, track = (it.get("artist") or "").strip(), (it.get("track") or "").strip()
        if not artist or not track:
            continue
        k = attempt_key(artist, track)
        if k in seen:
            continue
        seen.add(k)
        unique.append({**it, "artist": artist, "track": track})

    sem = asyncio.Semaphore(max(1, concurrency))

    async def one(it: dict) -> dict | None:
        async with sem:
            try:
                return await download_tracked(
                    it["artist"], it["track"], source=it.get("source", source),
                    expected_duration=it.get("expected_duration"),
                    skip_in_backoff=skip_in_backoff,
                )
            except Exception as e:
                log.warning(f"[auto-download] {it['artist']} — {it['track']} failed: {e}")
                return None

    results = await asyncio.gather(*(one(it) for it in unique))
    return [r for r in results if r is not None]


async def finalize_upgrade(upgrade_id: str, ok: bool | None, err: str | None) -> None:
    """Settle a TrackUpgrade row its download left at "downloading".

    The importer marks a real upgrade completed itself, so a row still downloading
    afterwards either failed or is unknown:
    - ok None (job still running, Soulseek down, cancelled): back to pending with the
      attempt refunded, so it doesn't count toward retirement;
    - ok True (the job finished but the importer didn't take it as an upgrade): failed;
    - ok False: failed with the job's error."""
    from datetime import datetime
    from sqlalchemy import func, update
    from backend.models.upgrade import TrackUpgrade

    try:
        async with async_session() as db:
            row = (await db.execute(
                select(TrackUpgrade).where(TrackUpgrade.id == upgrade_id)
            )).scalar_one_or_none()
            if not row or row.status != "downloading":
                return
            if ok is None:
                values = {"status": "pending", "attempts": func.max(TrackUpgrade.attempts - 1, 0)}
            elif ok and row.upgraded_format:
                values = {"status": "completed", "completed_at": row.completed_at or datetime.utcnow()}
            elif ok:
                values = {"status": "failed",
                          "error_message": "Downloaded but not matched as upgrade (title mismatch or same quality)"}
            else:
                values = {"status": "failed", "error_message": (err or "Download failed")[:500]}
            await db.execute(
                update(TrackUpgrade)
                .where(TrackUpgrade.id == upgrade_id, TrackUpgrade.status == "downloading")
                .values(**values, updated_at=datetime.utcnow())
            )
            await db.commit()
    except Exception as e:
        log.debug(f"[auto-download] Could not finalize upgrade {upgrade_id}: {e}")
