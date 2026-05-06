from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy import select, delete, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.helpers import paginate
from backend.database import get_db
from backend.models.job import Job
from backend.api.websocket import broadcast_job_update

router = APIRouter()


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


@router.get("")
async def list_jobs(limit: int = 25, offset: int = 0, type: str | None = None, status: str | None = None, db: AsyncSession = Depends(get_db)):
    base = select(Job)
    if type:
        type_list = [t.strip() for t in type.split(",") if t.strip()]
        if type_list:
            base = base.where(Job.type.in_(type_list))
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
        if j.type in ("download", "bulk_download"):
            item["result"] = j.result
            item["tracks"] = j.tracks
        items.append(item)
    return {"items": items, "total": total}


@router.get("/counts")
async def job_counts(type: str | None = None, db: AsyncSession = Depends(get_db)):
    """Server-side counts grouped by status, for any UI badge that shouldn't
    derive its count from a paginated job list."""
    q = select(Job.status, func.count(Job.id)).group_by(Job.status)
    if type:
        q = q.where(Job.type == type)
    counts = dict((await db.execute(q)).all())
    return {
        "pending": counts.get("pending", 0),
        "running": counts.get("running", 0),
        "completed": counts.get("completed", 0),
        "failed": counts.get("failed", 0),
        "all": sum(counts.values()),
    }


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
async def clear_jobs(type: str | None = None, db: AsyncSession = Depends(get_db)):
    """Delete completed/failed jobs. Optionally filter by type (comma-separated)."""
    query = delete(Job).where(Job.status.in_(["completed", "failed"]))
    if type:
        type_list = [t.strip() for t in type.split(",") if t.strip()]
        if type_list:
            query = query.where(Job.type.in_(type_list))
    result = await db.execute(query)
    await db.commit()
    return {"deleted": result.rowcount}


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
    await broadcast_job_update({"id": job_id, "type": job.type, "status": "failed", "progress": job.progress, "total": job.total})
    return {"ok": True}


@router.post("/{job_id}/retry")
async def retry_job(job_id: str, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """Retry failed tracks from a failed download job."""
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

    from backend.api.download import enqueue_download

    # Preserve original source from job card (e.g. "dl:upgrade" → "upgrade")
    source = job.card.split(":", 1)[1] if job.card and ":" in job.card else None

    for t in retryable_tracks:
        artist = t.get("artist", "")
        track = t.get("track", "")
        if artist and track:
            background_tasks.add_task(enqueue_download, artist, track, source=source)

    return {"ok": True, "total": len(retryable_tracks)}


@router.get("/{job_id}")
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        return {"error": "Job not found"}
    return {
        "id": job.id,
        "type": job.type,
        "status": job.status,
        "progress": job.progress,
        "total": job.total,
        "result": job.result,
        "log": job.log,
        "tracks": job.tracks,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }
