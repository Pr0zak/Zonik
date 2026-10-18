"""Retry ledger API (DC-14): the failed-search memory of automatic downloads.

Mounted at /api/download/attempts. Read-only except POST /run, which re-queues the
rows whose backoff has elapsed. Keys, `retired` and `reason` come from
backend.services.download_attempts; nothing here re-implements them.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.download_attempt import DownloadAttempt
from backend.models.schedule import ScheduleTask
from backend.services import download_attempts as ledger

router = APIRouter()


def _parse_before(value: str | None) -> datetime | None:
    """ISO timestamp (naive = UTC, 'Z' or an offset accepted) → naive UTC."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid due_before: {value!r}")
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


@router.get("")
async def list_attempts(
    due_before: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """Ledger rows, soonest retry first.

    Without `due_before` every row is listed (the backoff list); with it only the
    rows whose backoff has elapsed by then. `count_due` counts rows due by
    `due_before` (default now), `count_total` every row."""
    now = datetime.utcnow()
    before = _parse_before(due_before)
    if before is not None:
        rows = await ledger.rows_due(db, before, limit=limit)
    else:
        rows = list((await db.execute(
            select(DownloadAttempt)
            .order_by(DownloadAttempt.next_retry_at.asc(), DownloadAttempt.key)
            .limit(limit)
        )).scalars().all())
    return {
        "count_total": await ledger.count_all(db),
        "count_due": await ledger.count_due(db, before or now),
        "items": [ledger.row_to_dict(r, now) for r in rows],
    }


@router.get("/summary")
async def attempts_summary(due_before: str | None = None, db: AsyncSession = Depends(get_db)):
    """Counts for the quiet state plus the next runs of the download-feeding tasks.

    `due_now`: rows due already; `due_before`: rows due by the given time (equals
    `due_now` when omitted); `due_by_next_run`: rows due by the soonest
    `next_runs` entry, or null when no download task is scheduled."""
    from backend.api.schedule import next_download_runs

    now = datetime.utcnow()
    before = _parse_before(due_before)
    due_now = await ledger.count_due(db, now)
    tasks = (await db.execute(
        select(ScheduleTask).where(ScheduleTask.enabled.is_(True))
    )).scalars().all()
    next_runs = next_download_runs(tasks, now)
    due_by_next_run = None
    if next_runs:
        first = datetime.fromisoformat(next_runs[0]["next_run_at"])
        due_by_next_run = await ledger.count_due(db, max(first, now))
    return {
        "due_now": due_now,
        "due_before": await ledger.count_due(db, before) if before is not None else due_now,
        "total": await ledger.count_all(db),
        "next_runs": next_runs,
        "due_by_next_run": due_by_next_run,
    }


@router.post("/run")
async def run_due(
    background_tasks: BackgroundTasks,
    due_before: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Re-queue every row due by `due_before` (default now) through the tracked
    path with the backoff check off; outcomes update the ledger as usual."""
    from backend.services import auto_download

    before = _parse_before(due_before) or datetime.utcnow()
    rows = await ledger.rows_due(db, before)
    items = [{"artist": r.artist, "track": r.track, "source": r.source} for r in rows]
    if items:
        background_tasks.add_task(auto_download.download_tracked_many, items, skip_in_backoff=False)
    return {"queued": len(items)}
