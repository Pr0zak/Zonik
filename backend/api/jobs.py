from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, BackgroundTasks, Query
from pydantic import BaseModel
from sqlalchemy import select, delete, func, case, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from backend import database
from backend.api.helpers import paginate
from backend.database import get_db
from backend.models.job import Job
from backend.api.websocket import broadcast_job_update
from backend.api.download import job_outcome
from backend.services import download_failures, download_ledger

router = APIRouter()

DOWNLOAD_TYPES = ("download", "bulk_download")


def _job_description(j: Job) -> str:
    """Generate a human-readable description for a job."""
    # Try to extract track names from tracks JSON
    if j.tracks:
        try:
            tracks = json.loads(j.tracks)
            if isinstance(tracks, list) and tracks:
                names = [f"{t.get('artist', '')} — {t.get('track', '')}" for t in tracks[:3] if t.get('track')]
                if names:
                    suffix = f" (+{len(tracks) - 3} more)" if len(tracks) > 3 else ""
                    return ", ".join(names) + suffix
        except (json.JSONDecodeError, TypeError):
            pass
    # Try to extract from result JSON
    if j.result:
        try:
            result = json.loads(j.result)
            if isinstance(result, dict):
                if result.get("message"):
                    return result["message"]
                if result.get("error"):
                    return result["error"]
        except (json.JSONDecodeError, TypeError):
            pass
    return ""


def _loads(text: str | None):
    if not text:
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _first_track(tracks_json: str | None) -> dict:
    tracks = _loads(tracks_json)
    if isinstance(tracks, list) and tracks and isinstance(tracks[0], dict):
        return tracks[0]
    return {}


def _download_fields(j: Job) -> dict:
    """DC-7 per-row additions read from the row itself (no joins): the failure class
    and the live stage/attempt/funnel fields of tracks[0]. Additive only."""
    t0 = _first_track(j.tracks)
    result = _loads(j.result)
    result = result if isinstance(result, dict) else {}
    source_errors = t0.get("source_errors")
    if not isinstance(source_errors, list):
        source_errors = result.get("source_errors")
    search = result.get("search") if isinstance(result.get("search"), dict) else None
    if search is None and isinstance(t0.get("search"), dict):
        search = t0["search"]
    return {
        "failure_class": download_failures.failure_class(j.status, j.result, j.tracks),
        "stage": t0.get("stage"),
        "stage_since": t0.get("stage_since"),
        "attempt": t0.get("attempt"),
        "of": t0.get("of"),
        "source_errors": source_errors if isinstance(source_errors, list) else [],
        "search": search,
    }


# Why a download failed, grouped the way the Downloads page shows it. The message lives in
# Job.result ({"message": ...}); for "All N sources failed" the useful part is the last
# per-track error in Job.tracks. The buckets are the ones
# services.download_failures.BUCKET_OF_CLASS maps every failure_class to.
FAILURE_REASONS = {
    "not_found": "Not found on Soulseek",
    "no_better": "No better-quality source",
    "rejected": "Not imported (duplicate, not better, wrong song)",
    "peer": "Peer or transfer problem",
    "infra": "Not the track's fault (cancelled, restart, outage)",
}


def _starts(expr, prefix: str):
    """Case-sensitive, wildcard-free `expr startswith prefix` (LIKE is neither)."""
    return func.substr(expr, 1, len(prefix)) == prefix


def _json_text(col, path: str):
    """The string at `path` in a JSON text column, or '' (NULL, malformed JSON, a
    missing key or a non-string value). Nested CASEs because SQLite's json_type
    raises on malformed JSON and only a CASE branch is guaranteed not to run."""
    return case(
        (func.json_valid(col) == 1,
         case((func.json_type(col, path) == "text", func.json_extract(col, path)), else_="")),
        else_="",
    )


def _failure_parts():
    """(infra, not_found, no_better, rejected) SQL conditions mirroring
    download_failures.failure_class rule by rule, so the SQL bucket of a row equals
    BUCKET_OF_CLASS[failure_class(row)]. The parts overlap; _failure_filter makes
    them disjoint in the classifier's order.

    SQLite reads the JSON (result.error / result.message / tracks[0].error) like the
    classifier does. Postgres falls back to whole-text LIKE (json_extract is SQLite's)."""
    patterns = download_failures.INFRA_PATTERNS
    if database._is_postgres():
        res = func.coalesce(Job.result, "")
        trk = func.coalesce(Job.tracks, "")
        infra = or_(Job.result.is_(None), Job.result.in_(("{}", json.dumps({download_failures.DISMISSED_KEY: True}))),
                    *[res.like(f"%{p}%") for p in patterns])
        not_found = or_(*[res.like(f"%{p}%") for p in download_failures.NOT_FOUND_PREFIXES])
        no_better = res.like(f"%{download_failures.NO_BETTER_PREFIX}%")
        rejected = or_(trk.like(f"%{download_failures.REJECTED_LEGACY}%"),
                       trk.like(f"%{download_failures.REJECTED_PREFIX}%"),
                       res.like(f'%"message": "{download_failures.REJECTED_PREFIX}%'))
        return infra, not_found, no_better, rejected

    res = Job.result
    is_obj = func.coalesce(case((func.json_valid(res) == 1, func.json_type(res)), else_=None), "") == "object"
    err = _json_text(res, "$.error")
    msg = func.trim(_json_text(res, "$.message"))
    primary = func.trim(case((err != "", err), else_=_json_text(res, "$.message")))
    track_err = func.trim(_json_text(Job.tracks, "$[0].error"))
    # An orphan whose result only gained the incident-dismissed flag stays an orphan.
    only_flag = func.coalesce(case(
        (func.json_valid(res) == 1, func.json_remove(res, f"$.{download_failures.DISMISSED_KEY}")),
        else_=None), "") == "{}"
    infra = or_(
        ~is_obj,  # orphan: NULL / unparseable / not an object
        only_flag,
        err == "Cancelled by user",
        primary == "Cancelled by user",
        *[_starts(primary, p) for p in patterns if p != "Cancelled by user"],
    )
    not_found = or_(*[_starts(msg, p) for p in download_failures.NOT_FOUND_PREFIXES])
    no_better = _starts(msg, download_failures.NO_BETTER_PREFIX)
    rejected = or_(
        _starts(track_err, download_failures.REJECTED_PREFIX),
        func.instr(track_err, download_failures.REJECTED_LEGACY) > 0,
        _starts(msg, download_failures.REJECTED_PREFIX),
    )
    return infra, not_found, no_better, rejected


def _failure_filter(reason: str):
    """SQL condition selecting failed jobs in one FAILURE_REASONS group (disjoint:
    every failed row lands in exactly one).

    "rejected" also covers the old "Import rejected … empty, truncated, or unreadable"
    message, which was attached to every importer refusal regardless of cause, and
    reads only the LAST per-track error, so an earlier peer's "Not imported" kept in
    source_errors does not turn a later timeout into a rejection."""
    infra, not_found, no_better, rejected = _failure_parts()
    if reason == "infra":
        return infra
    if reason == "not_found":
        return and_(~infra, not_found)
    if reason == "no_better":
        return and_(~infra, ~not_found, no_better)
    if reason == "rejected":
        return and_(~infra, ~not_found, ~no_better, rejected)
    if reason == "peer":
        return and_(~infra, ~not_found, ~no_better, ~rejected)
    return None


def _type_filter(q, type: str | None):
    if type:
        type_list = [t.strip() for t in type.split(",") if t.strip()]
        if type_list:
            q = q.where(Job.type.in_(type_list))
    return q


# Rolling aliases kept for old callers; the page sends `since` (its local midnight).
TIMEFRAME_DAYS = {"today": 1, "week": 7, "month": 30}


def _parse_since(since: str | None) -> datetime | None:
    """ISO timestamp → naive UTC (the DB's timestamps are naive UTC). Aware values are
    converted; naive ones are taken as UTC. Unparseable → None (no scope)."""
    if not since:
        return None
    s = since.strip()
    if "T" in s:
        s = s.replace(" ", "+")  # an unencoded "+00:00" arrives as " 00:00"
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _scope_start(since: str | None, timeframe: str | None = None) -> datetime | None:
    start = _parse_since(since)
    if start is None and timeframe in TIMEFRAME_DAYS:
        start = datetime.utcnow() - timedelta(days=TIMEFRAME_DAYS[timeframe])
    return start


def _since_filter(q, since: str | None, timeframe: str | None = None):
    """Scope a select/delete to rows that finished (or started, while unfinished) at or
    after `since`; `timeframe` is the rolling fallback when `since` is absent."""
    start = _scope_start(since, timeframe)
    if start is not None:
        q = q.where(func.coalesce(Job.finished_at, Job.started_at) >= start)
    return q


@router.get("")
async def list_jobs(limit: int = 25, offset: int = 0, type: str | None = None, status: str | None = None,
                    reason: str | None = None, timeframe: str | None = None, since: str | None = None,
                    db: AsyncSession = Depends(get_db)):
    base = select(Job)
    if reason:
        cond = _failure_filter(reason)
        if cond is not None:
            base = base.where(Job.status == "failed", cond)
    base = _since_filter(base, since, timeframe)
    base = _type_filter(base, type)
    if status:
        status_list = [s.strip() for s in status.split(",") if s.strip()]
        if status_list:
            base = base.where(Job.status.in_(status_list))
    # Active jobs (running/pending) first, then by date
    status_priority = case(
        (Job.status == "running", 0),
        (Job.status == "pending", 1),
        else_=2,
    )
    base = base.order_by(status_priority, Job.started_at.desc())
    page = await paginate(db, base, offset, limit)
    total = page["total"]
    jobs = page["items"]
    items = []
    download_items = []
    for j in jobs:
        item = {
            "id": j.id,
            "type": j.type,
            "card": j.card,
            "status": j.status,
            "progress": j.progress,
            "total": j.total,
            "description": _job_description(j),
            "started_at": j.started_at.isoformat() if j.started_at else None,
            "finished_at": j.finished_at.isoformat() if j.finished_at else None,
        }
        # Include result/tracks detail for download jobs
        if j.type in DOWNLOAD_TYPES:
            item["result"] = j.result
            item["tracks"] = j.tracks
            item.update(job_outcome(j.status, j.result))
            item.update(_download_fields(j))
            download_items.append(item)
        items.append(item)
    if download_items:
        await download_ledger.enrich_items(db, download_items)
    return {"items": items, "total": total}


@router.get("/counts")
async def job_counts(type: str | None = None, since: str | None = None, db: AsyncSession = Depends(get_db)):
    """Server-side counts grouped by status, for any UI badge that shouldn't
    derive its count from a paginated job list. `type` may be comma-separated.
    `completed_since`/`failed_since` are scoped to `since` (all-time without it);
    the other keys keep their old meaning."""
    q = _type_filter(select(Job.status, func.count(Job.id)).group_by(Job.status), type)
    counts = dict((await db.execute(q)).all())

    # Calculate timeframe counts for completed jobs
    now = datetime.utcnow()
    q_today = select(func.count(Job.id)).where(
        Job.status == "completed",
        func.coalesce(Job.finished_at, Job.started_at) >= now - timedelta(days=1)
    )
    q_week = select(func.count(Job.id)).where(
        Job.status == "completed",
        func.coalesce(Job.finished_at, Job.started_at) >= now - timedelta(days=7)
    )
    q_today = _type_filter(q_today, type)
    q_week = _type_filter(q_week, type)

    completed_today = (await db.execute(q_today)).scalar_one() or 0
    completed_week = (await db.execute(q_week)).scalar_one() or 0

    q_since = _since_filter(_type_filter(
        select(Job.status, func.count(Job.id)).where(Job.status.in_(("completed", "failed")))
        .group_by(Job.status), type), since)
    scoped = dict((await db.execute(q_since)).all())

    return {
        "pending": counts.get("pending", 0),
        "running": counts.get("running", 0),
        "completed": counts.get("completed", 0),
        "completed_today": completed_today,
        "completed_week": completed_week,
        "failed": counts.get("failed", 0),
        "all": sum(counts.values()),
        "active": counts.get("pending", 0) + counts.get("running", 0),
        "completed_since": scoped.get("completed", 0),
        "failed_since": scoped.get("failed", 0),
    }


@router.get("/failures")
async def failure_summary(type: str | None = None, since: str | None = None, db: AsyncSession = Depends(get_db)):
    """Failed jobs counted per FAILURE_REASONS group, largest first (empty groups left out)."""
    out = []
    for key, label in FAILURE_REASONS.items():
        q = _type_filter(select(func.count(Job.id)).where(Job.status == "failed", _failure_filter(key)), type)
        q = _since_filter(q, since)
        n = (await db.execute(q)).scalar_one()
        if n:
            out.append({"reason": key, "label": label, "count": n})
    return sorted(out, key=lambda r: r["count"], reverse=True)


@router.get("/summary")
async def jobs_summary(type: str | None = None, since: str | None = None, db: AsyncSession = Depends(get_db)):
    """Totals for the Downloads page in one scope (DC-9): what finished and how
    (new / replaced / already had, bytes added, % lossless, played since), what failed
    per bucket and class, what happens next to the failed tracks, and the newest
    finished row (the quiet state's "Last job finished …", not scoped)."""
    type = type or ",".join(DOWNLOAD_TYPES)

    def _scoped(q):
        return _since_filter(_type_filter(q, type), since)

    # Completed rows in scope
    done_rows = (await db.execute(_scoped(
        select(Job.id, Job.card, Job.status, Job.result, Job.tracks, Job.finished_at)
        .where(Job.status == "completed")
    ))).all()
    done = [{"id": r.id, "card": r.card, "status": r.status, "result": r.result, "tracks": r.tracks,
             "finished_at": r.finished_at} for r in done_rows]
    upgrades = await download_ledger.upgrades_by_job_ids(db, [d["id"] for d in done])
    for d in done:
        d["outcome"] = download_ledger.outcome_for(d, upgrades.get(d["id"]))
        d["track_id"] = download_ledger.track_id_of(d, upgrades.get(d["id"]))
    tracks = await download_ledger.tracks_by_ids(db, [d["track_id"] for d in done if d["track_id"]])
    outcomes = {"new": 0, "replaced": 0, "already_had": 0}
    bytes_added = 0
    lossless = known_fmt = played = 0
    for d in done:
        outcomes[d["outcome"]] = outcomes.get(d["outcome"], 0) + 1
        if d["outcome"] == "already_had":
            continue
        res = _loads(d["result"])
        res = res if isinstance(res, dict) else {}
        size = res.get("file_size")
        if isinstance(size, (int, float)) and size > 0:
            bytes_added += int(size)
        trk = tracks.get(d["track_id"]) if d["track_id"] else None
        fmt = download_ledger.format_of(d, trk)
        if fmt:
            known_fmt += 1
            lossless += fmt in download_ledger.LOSSLESS_FORMATS
        if trk and trk["play_count"] > 0 and trk["last_played_at"] and d["finished_at"] \
                and datetime.fromisoformat(trk["last_played_at"]) >= d["finished_at"]:
            played += 1

    # Failed rows in scope: SQL buckets (same as /failures), Python classes, next
    failed = {}
    for key in FAILURE_REASONS:
        q = _scoped(select(func.count(Job.id)).where(Job.status == "failed", _failure_filter(key)))
        failed[key] = (await db.execute(q)).scalar_one()
    failed["total"] = sum(failed[k] for k in FAILURE_REASONS)
    failed_rows = (await db.execute(_scoped(
        select(Job.id, Job.card, Job.status, Job.result, Job.tracks).where(Job.status == "failed")
    ))).all()
    fitems = [{"id": r.id, "card": r.card, "status": r.status, "result": r.result, "tracks": r.tracks}
              for r in failed_rows]
    by_class = {c: 0 for c in download_failures.BUCKET_OF_CLASS}
    for it in fitems:
        cls = download_failures.failure_class(it["status"], it["result"], it["tracks"])
        if cls:
            by_class[cls] = by_class.get(cls, 0) + 1
    keys = download_ledger.keys_for(fitems)
    ledger = await download_ledger.ledger_by_keys(db, keys.values())
    fup = await download_ledger.upgrades_by_job_ids(db, [it["id"] for it in fitems])
    scans = await download_ledger.upgrade_failed_scans(db, [u.track_id for u in fup.values()])
    nxt = {"retry": 0, "retired": 0, "none": 0}
    for it in fitems:
        key = keys.get(it["id"])
        n = download_ledger.next_for(it, ledger.get(key) if key else None, fup.get(it["id"]), scans)
        nxt[download_ledger.next_bucket(n)] += 1

    # Newest finished row (any time)
    last = (await db.execute(_type_filter(
        select(Job).where(Job.status.in_(("completed", "failed")), Job.finished_at.isnot(None))
        .order_by(Job.finished_at.desc()).limit(1), type)
    )).scalar_one_or_none()
    last_finished = None
    if last is not None:
        t0 = _first_track(last.tracks)
        last_finished = {"id": last.id, "finished_at": last.finished_at.isoformat(),
                         "artist": t0.get("artist"), "track": t0.get("track"),
                         "card": last.card, "status": last.status}

    return {
        "outcomes": outcomes,
        "bytes_added": bytes_added,
        "pct_lossless": round(lossless * 100 / known_fmt) if known_fmt else None,
        "played_since": played,
        "failed": failed,
        "failed_by_class": by_class,
        "next": nxt,
        "last_finished": last_finished,
    }


# Rows /failed-tracks and /runs load per request (newest first); enough for a week
# of scheduler runs, bounded so a long scope can't load the whole table.
SCOPED_ROWS_MAX = 1000


async def _scoped_download_items(db: AsyncSession, type: str | None, since: str | None,
                                 status: str | None = None) -> list[dict]:
    """Download rows in scope as enriched list items (the same keys /api/jobs gives
    them), newest first, at most SCOPED_ROWS_MAX."""
    q = select(Job).where(Job.type.in_(DOWNLOAD_TYPES))
    if status:
        q = q.where(Job.status == status)
    q = _since_filter(_type_filter(q, type), since)
    q = q.order_by(func.coalesce(Job.finished_at, Job.started_at).desc()).limit(SCOPED_ROWS_MAX)
    rows = (await db.execute(q)).scalars().all()
    items = []
    for j in rows:
        item = {
            "id": j.id, "type": j.type, "card": j.card, "status": j.status,
            "started_at": j.started_at.isoformat() if j.started_at else None,
            "finished_at": j.finished_at.isoformat() if j.finished_at else None,
            "result": j.result, "tracks": j.tracks,
        }
        item.update(job_outcome(j.status, j.result))
        item.update(_download_fields(j))
        items.append(item)
    if items:
        await download_ledger.enrich_items(db, items)
    return items


@router.get("/failed-tracks")
async def failed_tracks(type: str | None = None, since: str | None = None,
                        cls: Annotated[str | None, Query(alias="class")] = None,
                        db: AsyncSession = Depends(get_db)):
    """Failed downloads folded per track (DC-20): one entry per attempt_key with the
    newest failed row as `last_job`, its class, how often the track failed in 30 days,
    its ledger/upgrade row and what happens next. `class` filters by a failure class
    or by a bucket (`infra` = cancelled + infra + orphan). `totals` count the entries
    returned (per track, not per row)."""
    items = await _scoped_download_items(db, type, since, status="failed")
    groups = download_ledger.group_failed_tracks(items)
    if cls:
        groups = [g for g in groups if cls in (g["class"], g["bucket"])]
    return {"items": groups, "totals": download_ledger.failed_totals(groups)}


@router.get("/runs")
async def download_runs(type: str | None = None, since: str | None = None, db: AsyncSession = Depends(get_db)):
    """Download rows grouped into runs (DC-20), newest first: by tracks[0].batch.id,
    else per card split on a 20-minute gap, with outcome / failure-bucket / live
    counts and the member job ids."""
    items = await _scoped_download_items(db, type, since)
    return {"items": download_ledger.group_runs(items)}


async def _retry_downloads(items: list[dict]) -> None:
    """Re-run failed downloads, a few at a time. Backoff is not consulted: the user
    asked for these retries.

    Each item is {artist, track, source, job_id (the failed job)}. An upgrade whose
    failed job still has its TrackUpgrade row goes back through the upgrades path
    (target track, row settled by finalize_upgrade); everything else goes through
    download_tracked, which records the outcome and looks up a length only for
    discovery-style sources (manual and upgrade retries get neither)."""
    from backend.database import async_session
    from backend.models.upgrade import TrackUpgrade
    from backend.services.auto_download import download_tracked_many

    upgrade_queue: list[tuple[str, str, str]] = []
    plain: list[dict] = []
    for it in items:
        if it.get("source") == "upgrade" and it.get("job_id"):
            try:
                async with async_session() as db:
                    row = (await db.execute(
                        select(TrackUpgrade).where(TrackUpgrade.job_id == it["job_id"])
                        .order_by(TrackUpgrade.created_at.desc()).limit(1)
                    )).scalar_one_or_none()
                    if row is not None and row.status not in ("completed", "queued", "downloading"):
                        row.status = "queued"
                        row.attempts = (row.attempts or 0) + 1
                        row.error_message = None
                        row.updated_at = datetime.utcnow()
                        await db.commit()
                        upgrade_queue.append((row.id, it["artist"], it["track"]))
                        continue
            except Exception:
                pass
        plain.append(it)

    if upgrade_queue:
        from backend.api.upgrades import _process_upgrade_queue
        await _process_upgrade_queue(upgrade_queue)
    if plain:
        await download_tracked_many(plain, skip_in_backoff=False)


@router.post("/retry-failed")
async def retry_failed(background_tasks: BackgroundTasks, type: str | None = None, reason: str | None = None,
                       since: str | None = None, db: AsyncSession = Depends(get_db)):
    """Re-queue every failed download (optionally one FAILURE_REASONS group).

    Each retried job's failed entry is deleted: the new attempt gets its own job, and
    keeping both would count the same track twice as failed and pending."""
    q = select(Job).where(Job.status == "failed", Job.type.in_(DOWNLOAD_TYPES))
    q = _type_filter(q, type)
    q = _since_filter(q, since)
    if reason:
        cond = _failure_filter(reason)
        if cond is None:
            return {"error": "Unknown reason"}
        q = q.where(cond)
    jobs = (await db.execute(q)).scalars().all()

    return await _delete_and_retry(db, background_tasks, jobs)


def _retry_items(job: Job) -> list[dict]:
    """The _retry_downloads items of one failed download row ([] when nothing is
    retryable). Any non-terminal track status counts: a row reaped mid-flight
    never got past queued/downloading."""
    tracks = _loads(job.tracks)
    tracks = tracks if isinstance(tracks, list) else []
    source = job.card.split(":", 1)[1] if job.card and ":" in job.card else None
    return [{"artist": t["artist"], "track": t["track"], "source": source, "job_id": job.id}
            for t in tracks if isinstance(t, dict)
            and t.get("status") in ("failed", "queued", "pending", "downloading", None)
            and t.get("artist") and t.get("track")]


async def _delete_and_retry(db: AsyncSession, background_tasks: BackgroundTasks, jobs: list[Job]) -> dict:
    """Delete each retryable row and re-queue its tracks in the background."""
    queued = 0
    retried_jobs = 0
    retry_items: list[dict] = []
    for job in jobs:
        wanted = _retry_items(job)
        if not wanted:
            continue
        retry_items.extend(wanted)
        queued += len(wanted)
        await db.delete(job)
        retried_jobs += 1
    await db.commit()
    if retry_items:
        background_tasks.add_task(_retry_downloads, retry_items)
    return {"ok": True, "jobs": retried_jobs, "tracks": queued}


INCIDENT_DEFAULT_DAYS = 7


async def _incident_rows(db: AsyncSession, type: str | None, since: str | None) -> list[Job]:
    """Failed download rows in scope that were not the track's fault (cancelled,
    infra, orphan). `since` defaults to 7 days ago."""
    q = select(Job).where(Job.status == "failed", Job.type.in_(DOWNLOAD_TYPES), _failure_filter("infra"))
    q = _type_filter(q, type)
    if _parse_since(since) is None:
        since = (datetime.utcnow() - timedelta(days=INCIDENT_DEFAULT_DAYS)).isoformat()
    q = _since_filter(q, since)
    rows = (await db.execute(q)).scalars().all()
    return [j for j in rows
            if download_failures.BUCKET_OF_CLASS.get(
                download_failures.failure_class(j.status, j.result, j.tracks) or "") == "infra"]


def _group(rows: list[Job]) -> list[dict]:
    return download_failures.group_incidents(
        (j.id, j.card, j.finished_at or j.started_at, download_failures.failure_text(j.result),
         download_failures.is_dismissed(j.result))
        for j in rows)


async def _incident_members(db: AsyncSession, incident_id: str, type: str | None,
                            since: str | None) -> list[Job] | None:
    rows = await _incident_rows(db, type, since)
    inc = next((i for i in _group(rows) if i["id"] == incident_id), None)
    if inc is None:
        return None
    ids = set(inc["job_ids"])
    return [j for j in rows if j.id in ids]


@router.get("/incidents")
async def list_incidents(type: str | None = None, since: str | None = None, db: AsyncSession = Depends(get_db)):
    """Not-the-track's-fault failures grouped into incidents (DC-17): restart, outage,
    cancel, internal, unreachable, orphan, per 15-minute window, newest first."""
    return {"items": _group(await _incident_rows(db, type, since))}


@router.post("/incidents/{incident_id}/retry")
async def retry_incident(incident_id: str, background_tasks: BackgroundTasks, type: str | None = None,
                         since: str | None = None, db: AsyncSession = Depends(get_db)):
    """Re-queue every member of an incident (rows deleted, like retry-failed)."""
    members = await _incident_members(db, incident_id, type, since)
    if members is None:
        return {"error": "Incident not found"}
    return await _delete_and_retry(db, background_tasks, members)


@router.post("/incidents/{incident_id}/dismiss")
async def dismiss_incident(incident_id: str, type: str | None = None, since: str | None = None,
                           db: AsyncSession = Depends(get_db)):
    """Hide an incident: `incident_dismissed: true` merged into each member's result
    (terminal rows only; no table, no settings key; pruned with the rows)."""
    members = await _incident_members(db, incident_id, type, since)
    if members is None:
        return {"error": "Incident not found"}
    n = 0
    for j in members:
        if j.status in ("pending", "running"):
            continue
        result = _loads(j.result)
        if not isinstance(result, dict):
            # An orphan: keep nothing of an unparseable value but its class (orphan).
            result = {}
        if result.get(download_failures.DISMISSED_KEY) is True:
            continue
        result[download_failures.DISMISSED_KEY] = True
        j.result = json.dumps(result)
        n += 1
    await db.commit()
    return {"dismissed": n}


@router.get("/dashboard")
async def job_dashboard(db: AsyncSession = Depends(get_db)):
    """Job pipeline health metrics for the dashboard."""
    from datetime import timedelta

    now = datetime.utcnow()
    day_ago = now - timedelta(hours=24)
    week_ago = now - timedelta(days=7)

    # Status counts (24h)
    status_result = await db.execute(
        select(Job.status, func.count(Job.id))
        .where(Job.started_at >= day_ago)
        .group_by(Job.status)
    )
    status_counts = dict(status_result.all())

    # Type distribution (24h)
    type_result = await db.execute(
        select(Job.type, func.count(Job.id))
        .where(Job.started_at >= day_ago)
        .group_by(Job.type)
        .order_by(func.count(Job.id).desc())
    )
    type_dist = [{"type": t, "count": c} for t, c in type_result.all()]

    # Timeline (hourly for 24h)
    hourly_result = await db.execute(
        select(
            func.strftime("%Y-%m-%d %H:00", Job.started_at).label("hour"),
            func.count(Job.id),
        )
        .where(Job.started_at >= day_ago)
        .group_by("hour")
        .order_by("hour")
    )
    timeline = [{"hour": h, "count": c} for h, c in hourly_result.all()]

    # Avg duration by type (completed only, 7d)
    duration_result = await db.execute(
        select(
            Job.type,
            func.avg(
                func.julianday(Job.finished_at) - func.julianday(Job.started_at)
            ).label("avg_days"),
        )
        .where(Job.status == "completed", Job.started_at >= week_ago, Job.finished_at.isnot(None))
        .group_by(Job.type)
    )
    avg_duration = {
        t: round((d or 0) * 86400, 1)  # Convert days to seconds
        for t, d in duration_result.all()
    }

    # Currently active
    active_result = await db.execute(
        select(func.count(Job.id)).where(Job.status.in_(["running", "pending"]))
    )
    active_count = active_result.scalar() or 0

    # Failure rate (7d)
    week_total = await db.execute(
        select(func.count(Job.id)).where(Job.started_at >= week_ago)
    )
    week_failed = await db.execute(
        select(func.count(Job.id)).where(Job.started_at >= week_ago, Job.status == "failed")
    )
    total_7d = week_total.scalar() or 0
    failed_7d = week_failed.scalar() or 0
    failure_rate = round(failed_7d / total_7d * 100, 1) if total_7d > 0 else 0

    return {
        "status_counts": status_counts,
        "type_distribution": type_dist,
        "timeline": timeline,
        "avg_duration": avg_duration,
        "active_count": active_count,
        "total_24h": sum(status_counts.values()),
        "failure_rate_7d": failure_rate,
        "failed_7d": failed_7d,
        "total_7d": total_7d,
    }


@router.get("/active")
async def active_jobs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Job).where(Job.status.in_(["pending", "running"]))
    )
    jobs = result.scalars().all()
    return [
        {
            "id": j.id,
            "type": j.type,
            "card": j.card,
            "status": j.status,
            "progress": j.progress,
            "total": j.total,
            "description": _job_description(j),
        }
        for j in jobs
    ]


@router.get("/stream/recent")
async def recent_job_updates(limit: int = 20, db: AsyncSession = Depends(get_db)):
    """Get recent job updates for live log display."""
    result = await db.execute(
        select(Job).order_by(Job.started_at.desc()).limit(limit)
    )
    jobs = result.scalars().all()
    return [
        {
            "id": j.id,
            "type": j.type,
            "status": j.status,
            "progress": j.progress,
            "total": j.total,
            "started_at": j.started_at.isoformat() if j.started_at else None,
            "finished_at": j.finished_at.isoformat() if j.finished_at else None,
        }
        for j in jobs
    ]


@router.delete("/clear")
async def clear_jobs(type: str | None = None, status: str | None = None, reason: str | None = None,
                     since: str | None = None, db: AsyncSession = Depends(get_db)):
    """Delete completed/failed jobs. Optionally filter by type, status (completed/failed),
    failure reason, or `since` (only rows that finished in the scope shown). Never
    deletes pending/running rows, whatever `status` asks for."""
    statuses = [s.strip() for s in status.split(",") if s.strip()] if status else ["completed", "failed"]
    statuses = [s for s in statuses if s not in ("pending", "running")]
    if not statuses:
        return {"deleted": 0}
    query = delete(Job).where(Job.status.in_(statuses))
    query = _type_filter(query, type)
    query = _since_filter(query, since)
    if reason:
        cond = _failure_filter(reason)
        if cond is not None:
            query = query.where(cond)
    result = await db.execute(query)
    await db.commit()
    return {"deleted": result.rowcount}


@router.delete("/{job_id}")
async def delete_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """Remove one finished download row on the server (the page's "Remove").
    Active rows are refused: the running task still writes to them."""
    job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
    if not job:
        return {"error": "Job not found"}
    if job.status in ("pending", "running"):
        return {"error": "Job is active"}
    if job.type not in DOWNLOAD_TYPES:
        return {"error": "Not a download job"}
    await db.delete(job)
    await db.commit()
    return {"deleted": 1}


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """Mark a running job as failed/cancelled. The background task checks this flag."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        return {"error": "Job not found"}
    if job.status not in ("pending", "running"):
        return {"error": "Job not cancellable"}
    job.status = "failed"
    job.finished_at = datetime.utcnow()
    if not job.result:
        job.result = json.dumps({"error": "Cancelled by user"})
    await db.commit()
    if job.type == "download":
        # The running download polls this in-memory set rather than the DB row.
        # Only for a job a task in this process still owns: anything else (a stale
        # row from before a restart) would leave the id in the set forever.
        from backend.api.download import cancelled_jobs, live_download_jobs
        if job_id in live_download_jobs:
            cancelled_jobs.add(job_id)
    await broadcast_job_update({"id": job_id, "type": job.type, "status": "failed", "progress": job.progress, "total": job.total})
    return {"ok": True}


@router.post("/{job_id}/retry")
async def retry_job(job_id: str, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """Retry failed tracks from a failed download job.

    The failed row is deleted (like retry-failed): the retry gets its own job, and
    keeping both would count the track as failed and pending at once. The reply's
    `replaced_job_id` lets the page drop the old row. _retry_downloads still finds a
    TrackUpgrade by the old job id string, which outlives the row."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        return {"error": "Job not found"}

    if job.type not in ("download", "bulk_download") or job.status != "failed":
        return {"error": "Job not retryable"}

    try:
        tracks = json.loads(job.tracks) if job.tracks else []
    except (json.JSONDecodeError, TypeError):
        return {"error": "Job not retryable"}

    # Accept any non-terminal track status — for orphaned jobs cancelled mid-flight
    # (e.g. service restart, peer drop with no signal) the per-track JSON never gets
    # past "queued"/"downloading" even though the job itself is marked failed.
    retryable_tracks = [
        t for t in tracks
        if t.get("status") in ("failed", "queued", "pending", "downloading", None)
    ]
    if not retryable_tracks:
        return {"error": "No retryable tracks"}

    # Preserve original source from job card (e.g. "dl:upgrade" → "upgrade")
    source = job.card.split(":", 1)[1] if job.card and ":" in job.card else None

    items = [{"artist": t.get("artist", ""), "track": t.get("track", ""), "source": source, "job_id": job.id}
             for t in retryable_tracks if t.get("artist") and t.get("track")]
    if items:
        await db.delete(job)
        await db.commit()
        background_tasks.add_task(_retry_downloads, items)

    return {"ok": True, "total": len(retryable_tracks), "replaced_job_id": job_id if items else None}


class StopTryingRequest(BaseModel):
    remove: bool = False  # also delete the job row (finished rows only)


@router.post("/{job_id}/stop-trying")
async def stop_trying(job_id: str, body: StopTryingRequest | None = None, db: AsyncSession = Depends(get_db)):
    """Give up on a download's track: blacklist it (track-level, reason "Stopped from
    Downloads"; scheduler, bulk and playlist runs skip it from then on), forget its
    retry-ledger row, and skip its pending/queued/failed upgrades. With `remove` the
    job row is deleted too (never an active one)."""
    from backend.models.blacklist import DownloadBlacklist
    from backend.models.download_attempt import DownloadAttempt
    from backend.models.upgrade import TrackUpgrade
    from backend.services.download_attempts import attempt_key
    from backend.services.soulseek import normalize_text
    import uuid

    remove = bool(body and body.remove)
    job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
    if not job:
        return {"error": "Job not found"}
    if job.type not in DOWNLOAD_TYPES:
        return {"error": "Not a download job"}
    t0 = _first_track(job.tracks)
    artist = (t0.get("artist") or "").strip()
    track = (t0.get("track") or "").strip()
    if not artist or not track:
        return {"error": "No track on this job"}

    # Reuse an existing entry for the same track (same matching as is_blacklisted).
    existing = (await db.execute(
        select(DownloadBlacklist).where(func.lower(DownloadBlacklist.artist) == artist.lower())
    )).scalars().all()
    entry = next((e for e in existing if e.track is not None
                  and normalize_text(e.track) == normalize_text(track)), None)
    if entry is None:
        entry = DownloadBlacklist(id=str(uuid.uuid4()), artist=artist, track=track,
                                  reason="Stopped from Downloads")
        db.add(entry)

    attempt_deleted = (await db.execute(
        delete(DownloadAttempt).where(DownloadAttempt.key == attempt_key(artist, track))
    )).rowcount > 0

    result = _loads(job.result)
    track_id = result.get("track_id") if isinstance(result, dict) else None
    match = TrackUpgrade.job_id == job_id
    if track_id:
        match = or_(match, TrackUpgrade.track_id == track_id)
    upgrades = (await db.execute(
        select(TrackUpgrade).where(match, TrackUpgrade.status.in_(("pending", "queued", "failed")))
    )).scalars().all()
    for u in upgrades:
        u.status = "skipped"
        u.updated_at = datetime.utcnow()

    removed = False
    if remove and job.status not in ("pending", "running"):
        await db.delete(job)
        removed = True
    await db.commit()
    return {"blacklisted": entry.id, "attempt_deleted": attempt_deleted,
            "upgrades_skipped": len(upgrades), "removed": removed}


@router.get("/{job_id}")
async def get_job(job_id: str, detail: bool = False, db: AsyncSession = Depends(get_db)):
    """One job. Every key the pollers (discover, WeeklyRadar, lib/download.js, the
    phone) read keeps its name and type; `card` is always added. `?detail=1` adds the
    drawer's payload (DC-19): parsed copies of result/tracks/log, the funnel, the
    candidates, the failure class and stage, the ledger/upgrade/track joins and the
    peers' reputation. The joins only run with detail=1."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        return {"error": "Job not found"}
    out = {
        "id": job.id,
        "type": job.type,
        "card": job.card,
        "status": job.status,
        "progress": job.progress,
        "total": job.total,
        "result": job.result,
        "log": job.log,
        "tracks": job.tracks,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        **job_outcome(job.status, job.result),
    }
    if detail:
        out.update(await _job_detail(db, job, out))
    return out


async def _job_detail(db: AsyncSession, job: Job, base: dict) -> dict:
    """The DC-19 additions for get_job(detail=1). Null-safe on every column."""
    from backend.soulseek import get_client

    result = _loads(job.result)
    tracks = _loads(job.tracks)
    res = result if isinstance(result, dict) else {}
    t0 = _first_track(job.tracks)
    fields = _download_fields(job)
    outcome = job_outcome(job.status, job.result, job.tracks)
    candidates = res.get("candidates")
    extra = {
        "result_json": result,
        "tracks_json": tracks,
        "timeline": download_ledger.timeline_of(job.log),
        "search": fields["search"],
        "candidates": [c for c in candidates if isinstance(c, dict)] if isinstance(candidates, list) else [],
        "source_errors": outcome.get("source_errors", []),
        "failure_class": outcome.get("failure_class"),
        "stage": outcome.get("stage"),
        "stage_since": outcome.get("stage_since"),
        "attempt": fields["attempt"],
        "of": fields["of"],
        "ledger": None,
        "upgrade": None,
        "track": None,
        "outcome": None,
        "times_failed_30d": 0,
        "next": {"kind": "none", "at": None, "attempts": 0, "max_attempts": None},
        "peers": {},
    }
    if job.type in DOWNLOAD_TYPES:
        item = {k: base.get(k) for k in ("id", "type", "card", "status", "result", "tracks",
                                          "track_id", "already_in_library")}
        await download_ledger.enrich_items(db, [item])
        for k in ("ledger", "upgrade", "track", "outcome", "times_failed_30d", "next"):
            extra[k] = item.get(k, extra[k])
        try:
            extra["peers"] = await download_ledger.peers_for(
                download_ledger.usernames_of(res, t0), get_client())
        except Exception:
            extra["peers"] = {}
    return extra
