"""Query-time joins for download job rows (DC-7 / DC-9): the retry ledger
(download_attempts), upgrade rows (track_upgrades), the imported track, how often
the same track failed in 30 days, and the derived `next` / `outcome` fields.

Everything here reads; nothing writes. Items are the dicts ``/api/jobs`` builds
(``id, card, status, result (str), tracks (str), already_in_library?``) and are
enriched in place with additive keys only. Every join is null-safe: a missing
ledger row, a deleted track or an unparseable JSON column yields ``None``, never
an exception.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services import download_failures
from backend.services.download_attempts import BACKOFF, attempt_key, is_retired, ledger_by_keys  # noqa: F401  (re-exported)

# Failures past this many attempts are retired (download_attempts.is_retired).
LEDGER_MAX_ATTEMPTS = len(BACKOFF) + 1
# Failed scans that retire an upgrade (download_attempts.upgrade_skip_ids default).
UPGRADE_MAX_SCANS = 3
LOSSLESS_FORMATS = {"flac", "alac", "wav", "aiff", "aif", "ape", "wv", "dsf", "dff"}
# Failure classes that say nothing about the track: not counted in times_failed_30d.
NOT_THE_TRACKS_FAULT = {"cancelled", "infra", "orphan"}

_CHUNK = 500


def _loads(text):
    if not text or not isinstance(text, str):
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _result(item: dict) -> dict:
    r = _loads(item.get("result"))
    return r if isinstance(r, dict) else {}


def _t0(item: dict) -> dict:
    t = _loads(item.get("tracks"))
    if isinstance(t, list) and t and isinstance(t[0], dict):
        return t[0]
    return {}


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _chunks(values: list, n: int = _CHUNK):
    for i in range(0, len(values), n):
        yield values[i:i + n]


def key_of(item: dict) -> str | None:
    """attempt_key of a job row's track (tracks[0] artist/track), or None."""
    t0 = _t0(item)
    artist, track = t0.get("artist"), t0.get("track")
    if not artist or not track or not isinstance(artist, str) or not isinstance(track, str):
        return None
    return attempt_key(artist, track)


def keys_for(items: Iterable[dict]) -> dict[str, str]:
    """{job id: attempt_key} for the items whose tracks[0] names a track."""
    out = {}
    for it in items:
        k = key_of(it)
        if k:
            out[it.get("id")] = k
    return out


async def upgrades_by_job_ids(db: AsyncSession, job_ids: Iterable[str]) -> dict:
    """{job id: newest TrackUpgrade row linked to it (TrackUpgrade.job_id)}."""
    from backend.models.upgrade import TrackUpgrade
    ids = list({i for i in job_ids if i})
    out: dict = {}
    for part in _chunks(ids):
        rows = (await db.execute(
            select(TrackUpgrade).where(TrackUpgrade.job_id.in_(part)).order_by(TrackUpgrade.created_at)
        )).scalars().all()
        for r in rows:  # ascending: the newest row per job wins
            out[r.job_id] = r
    return out


async def upgrade_failed_scans(db: AsyncSession, track_ids: Iterable[str]) -> dict[str, int]:
    """{track id: failed TrackUpgrade rows} — each scan inserts a fresh row, so the
    per-track count (not one row's attempts) is what retires an upgrade."""
    from backend.models.upgrade import TrackUpgrade
    ids = list({i for i in track_ids if i})
    out: dict[str, int] = {}
    for part in _chunks(ids):
        rows = (await db.execute(
            select(TrackUpgrade.track_id, func.count(TrackUpgrade.id))
            .where(TrackUpgrade.track_id.in_(part), TrackUpgrade.status == "failed")
            .group_by(TrackUpgrade.track_id)
        )).all()
        out.update({tid: n for tid, n in rows})
    return out


async def tracks_by_ids(db: AsyncSession, track_ids: Iterable[str]) -> dict[str, dict]:
    """{track id: {id, format, bitrate, file_size, play_count, last_played_at,
    duration_seconds}} for tracks that still exist."""
    from backend.models.track import Track
    ids = list({i for i in track_ids if i and isinstance(i, str)})
    out: dict[str, dict] = {}
    for part in _chunks(ids):
        rows = (await db.execute(
            select(Track.id, Track.format, Track.bitrate, Track.file_size, Track.play_count,
                   Track.last_played_at, Track.duration_seconds).where(Track.id.in_(part))
        )).all()
        for r in rows:
            out[r.id] = {
                "id": r.id, "format": r.format, "bitrate": r.bitrate, "file_size": r.file_size,
                "play_count": r.play_count or 0, "last_played_at": _iso(r.last_played_at),
                "duration_seconds": r.duration_seconds,
            }
    return out


async def times_failed_30d(db: AsyncSession, now: datetime | None = None) -> dict[str, int]:
    """{attempt_key: failed download rows in the last 30 days}. One SELECT, grouped
    in Python; rows that were not the track's fault (cancel, restart, outage,
    orphan) are not counted."""
    from backend.models.job import Job
    now = now or datetime.utcnow()
    rows = (await db.execute(
        select(Job.tracks, Job.result).where(
            Job.status == "failed", Job.type.in_(("download", "bulk_download")),
            func.coalesce(Job.finished_at, Job.started_at) >= now - timedelta(days=30),
        )
    )).all()
    out: dict[str, int] = {}
    for tracks, result in rows:
        if download_failures.failure_class("failed", result, tracks) in NOT_THE_TRACKS_FAULT:
            continue
        k = key_of({"tracks": tracks})
        if k:
            out[k] = out.get(k, 0) + 1
    return out


def ledger_dict(row) -> dict | None:
    if row is None:
        return None
    return {
        "attempts": row.attempts or 0,
        "next_retry_at": _iso(row.next_retry_at),
        "retired": is_retired(row.attempts or 0),
        "last_error": row.last_error,
    }


def _scan_count(upgrade_row, failed_scans: dict[str, int] | None) -> int:
    n = upgrade_row.attempts or 0
    if failed_scans and upgrade_row.track_id:
        n = max(n, failed_scans.get(upgrade_row.track_id, 0))
    return n


def upgrade_dict(row, failed_scans: dict[str, int] | None = None) -> dict | None:
    if row is None:
        return None
    return {
        "original_format": row.original_format,
        "original_bitrate": row.original_bitrate,
        "upgraded_format": row.upgraded_format,
        "upgraded_bitrate": row.upgraded_bitrate,
        "attempts": _scan_count(row, failed_scans),
        "max_attempts": row.max_attempts or UPGRADE_MAX_SCANS,
        "status": row.status,
    }


def next_for(item: dict, ledger_row, upgrade_row, failed_scans: dict[str, int] | None = None) -> dict:
    """What happens next to a failed row's track: `retry` (the ledger schedules
    another try at `at`), `retired` (given up on for a year), `scans` (an upgrade:
    k of N scans), or `none` (manual, cancelled with no ledger row, …). Rows that
    did not fail are `none`."""
    none = {"kind": "none", "at": None, "attempts": 0, "max_attempts": None}
    if item.get("status") != "failed":
        return none
    if upgrade_row is not None or item.get("card") == "dl:upgrade":
        attempts = _scan_count(upgrade_row, failed_scans) if upgrade_row is not None else 0
        max_attempts = (upgrade_row.max_attempts if upgrade_row is not None else None) or UPGRADE_MAX_SCANS
        return {"kind": "scans", "at": None, "attempts": attempts, "max_attempts": max_attempts}
    if ledger_row is not None:
        attempts = ledger_row.attempts or 0
        return {"kind": "retired" if is_retired(attempts) else "retry", "at": _iso(ledger_row.next_retry_at),
                "attempts": attempts, "max_attempts": LEDGER_MAX_ATTEMPTS}
    return none


def next_bucket(nxt: dict) -> str:
    """Fold a `next` into the summary's retry / retired / none."""
    kind = nxt.get("kind")
    if kind == "scans":
        m = nxt.get("max_attempts") or UPGRADE_MAX_SCANS
        return "retired" if (nxt.get("attempts") or 0) >= m else "retry"
    return kind if kind in ("retry", "retired") else "none"


def outcome_for(item: dict, upgrade_row) -> str | None:
    """new | replaced | already_had for a completed row, else None. A library bulk
    upgrade with no TrackUpgrade row counts as new."""
    if item.get("status") != "completed":
        return None
    if item.get("already_in_library") or _result(item).get("already_in_library"):
        return "already_had"
    if (upgrade_row is not None and upgrade_row.status == "completed") or item.get("card") == "dl:upgrade":
        return "replaced"
    return "new"


def track_id_of(item: dict, upgrade_row=None) -> str | None:
    tid = _result(item).get("track_id") or item.get("track_id")
    if not tid and upgrade_row is not None and item.get("status") == "completed":
        tid = upgrade_row.track_id
    return tid if isinstance(tid, str) and tid else None


def format_of(item: dict, track: dict | None) -> str | None:
    """Lower-case format of a completed row: the track's, else the filename extension."""
    fmt = (track or {}).get("format")
    if not fmt:
        fname = _result(item).get("filename") or _t0(item).get("filename") or ""
        if isinstance(fname, str) and "." in fname:
            fmt = fname.replace("\\", "/").rsplit(".", 1)[-1]
    return fmt.lower() if isinstance(fmt, str) and fmt else None


async def enrich_items(db: AsyncSession, items: list[dict], now: datetime | None = None) -> list[dict]:
    """Add DC-7's joined keys (ledger, times_failed_30d, next, upgrade, track,
    outcome) to download items, in place. Batched: one query per join for the page."""
    now = now or datetime.utcnow()
    items = [it for it in items if it.get("type") in ("download", "bulk_download") or "type" not in it]
    if not items:
        return items
    keys = keys_for(items)
    ledger = await ledger_by_keys(db, keys.values())
    upgrades = await upgrades_by_job_ids(db, [it.get("id") for it in items])
    failed_scans = await upgrade_failed_scans(db, [u.track_id for u in upgrades.values()])
    track_ids = {it.get("id"): track_id_of(it, upgrades.get(it.get("id"))) for it in items}
    tracks = await tracks_by_ids(db, [t for t in track_ids.values() if t])
    failed_counts = await times_failed_30d(db, now)
    for it in items:
        jid = it.get("id")
        key = keys.get(jid)
        lrow = ledger.get(key) if key else None
        urow = upgrades.get(jid)
        it["ledger"] = ledger_dict(lrow)
        it["times_failed_30d"] = failed_counts.get(key, 0) if key else 0
        it["next"] = next_for(it, lrow, urow, failed_scans)
        it["upgrade"] = upgrade_dict(urow, failed_scans)
        tid = track_ids.get(jid)
        it["track"] = tracks.get(tid) if tid else None
        it["outcome"] = outcome_for(it, urow)
    return items
