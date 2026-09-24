"""Needs-attention summary for the admin dashboard.

One call that ranks the things an admin should look at — failing jobs, failed
downloads and upgrades, low-quality tracks, reclaimable duplicates, the Soulseek
connection, switched-off scheduled tasks — each with a link to the page (already
filtered) where it gets fixed. Everything is derived from data the server already
keeps; nothing here changes state.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.job import Job
from backend.models.schedule import ScheduleTask
from backend.models.track import Track
from backend.models.upgrade import TrackUpgrade

router = APIRouter()

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
DOWNLOAD_TYPES = ("download", "bulk_download")
# Upgrade rows that are still going somewhere (or already done): a low-quality track
# with one of these doesn't need the admin.
UPGRADE_IN_HAND = ("pending", "queued", "downloading", "completed")


def _item(key: str, severity: str, title: str, detail: str, action: str, href: str) -> dict:
    return {"key": key, "severity": severity, "title": title, "detail": detail,
            "action": action, "href": href}


def _n(x: int) -> str:
    return f"{x:,}"


@router.get("")
async def attention(db: AsyncSession = Depends(get_db)) -> dict:
    items: list[dict] = []
    now = datetime.utcnow()

    # --- Soulseek connection: nothing downloads without it ---
    try:
        from backend.soulseek import get_client
        client = get_client()
        if client is not None and not client.logged_in:
            items.append(_item("soulseek", "critical", "Soulseek is disconnected",
                               "Downloads and upgrades can't run until it reconnects",
                               "Check connection", "/settings#soulseek"))
    except Exception:
        pass

    # --- Job failure rate, last 7 days ---
    week_ago = now - timedelta(days=7)
    total_7d, failed_7d = (await db.execute(
        select(func.count(Job.id), func.coalesce(func.sum(case((Job.status == "failed", 1), else_=0)), 0))
        .where(Job.started_at >= week_ago)
    )).one()
    total_7d, failed_7d = int(total_7d or 0), int(failed_7d or 0)
    if total_7d >= 10 and failed_7d:
        rate = failed_7d / total_7d
        if rate >= 0.2:
            from backend.api.jobs import FAILURE_REASONS, _failure_filter
            parts = []
            for key, label in FAILURE_REASONS.items():
                n = (await db.execute(
                    select(func.count(Job.id)).where(
                        Job.status == "failed", Job.type.in_(DOWNLOAD_TYPES),
                        Job.started_at >= week_ago, _failure_filter(key))
                )).scalar_one()
                if n:
                    short = label.split(" (")[0]
                    parts.append(f"{_n(n)} {short[0].lower()}{short[1:]}")
            items.append(_item(
                "job_failures", "critical" if rate >= 0.5 else "warning",
                f"{round(rate * 100)}% of jobs failed in the last 7 days",
                f"{_n(failed_7d)} of {_n(total_7d)}" + (f" · downloads: {', '.join(parts)}" if parts else ""),
                "Open failures", "/downloads?status=failed",
            ))

    # --- Failed upgrades, split by why ---
    failed_upgrades = (await db.execute(
        select(TrackUpgrade.error_message, func.count(TrackUpgrade.id))
        .where(TrackUpgrade.status == "failed").group_by(TrackUpgrade.error_message)
    )).all()
    n_failed_up = sum(c for _, c in failed_upgrades)
    if n_failed_up:
        buckets = {"nothing better found": 0, "not found": 0, "wrong song": 0,
                   "download failed": 0, "retries used up": 0, "other": 0}
        for msg, c in failed_upgrades:
            m = (msg or "").lower()
            if "not higher quality" in m or "no source better" in m:
                buckets["nothing better found"] += c
            elif "no results" in m:
                buckets["not found"] += c
            elif "not the same track" in m:
                buckets["wrong song"] += c
            elif "max attempts" in m:
                buckets["retries used up"] += c
            elif "download failed" in m or "sources failed" in m or "peer" in m or "timed out" in m:
                buckets["download failed"] += c
            else:
                buckets["other"] += c
        detail = " · ".join(f"{_n(c)} {k}" for k, c in buckets.items() if c)
        items.append(_item("upgrades_failed", "warning" if n_failed_up < 500 else "critical",
                           f"{_n(n_failed_up)} upgrades failed", detail,
                           "Review", "/upgrades?status=failed"))

    # --- Low-bitrate tracks nobody is upgrading ---
    in_hand = select(TrackUpgrade.track_id).where(TrackUpgrade.status.in_(UPGRADE_IN_HAND))
    low_q = (await db.execute(
        select(func.count(Track.id)).where(
            Track.bitrate.isnot(None), Track.bitrate < 256000, Track.id.notin_(in_hand))
    )).scalar_one()
    if low_q:
        items.append(_item("low_quality", "warning",
                           f"{_n(low_q)} low-bitrate tracks with no upgrade queued",
                           "Under 256 kbps, and no pending or completed upgrade",
                           "Queue upgrades", "/upgrades"))

    # --- Duplicates worth reclaiming ---
    try:
        from backend.services.cleanup import find_duplicates_enriched
        dup = await find_duplicates_enriched(db)
        reclaim = dup.get("reclaimable_bytes") or 0
        if dup.get("total_groups") and reclaim >= 1024 ** 3:
            mism = sum(1 for g in dup["groups"] if g.get("best_format") != g.get("worst_format"))
            items.append(_item(
                "duplicates", "warning",
                f"{reclaim / 1024 ** 3:.1f} GB reclaimable in duplicates",
                f"{_n(dup['total_groups'])} groups · {_n(dup.get('total_duplicates', 0))} extra files"
                + (f" · {_n(mism)} in different formats" if mism else ""),
                "Resolve", "/duplicates",
            ))
    except Exception:
        pass

    # --- Scheduled tasks switched off ---
    off = (await db.execute(
        select(ScheduleTask.task_name).where(ScheduleTask.enabled == False)  # noqa: E712
    )).scalars().all()
    if off:
        names = ", ".join(t.replace("_", " ").capitalize() for t in off[:4])
        items.append(_item("tasks_off", "info",
                           f"{len(off)} scheduled task{'s are' if len(off) != 1 else ' is'} off",
                           names + (f" and {len(off) - 4} more" if len(off) > 4 else ""),
                           "Schedule", "/schedule"))

    items.sort(key=lambda i: SEVERITY_ORDER.get(i["severity"], 9))
    return {
        "items": items,
        "counts": {s: sum(1 for i in items if i["severity"] == s) for s in SEVERITY_ORDER},
        "generated_at": now.isoformat(),
    }
