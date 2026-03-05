from __future__ import annotations

import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db, async_session
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
async def list_jobs(limit: int = 50, offset: int = 0, type: str | None = None, db: AsyncSession = Depends(get_db)):
    query = select(Job)
    if type:
        type_list = [t.strip() for t in type.split(",") if t.strip()]
        if type_list:
            query = query.where(Job.type.in_(type_list))
    query = query.order_by(Job.started_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
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
            "started_at": j.started_at.isoformat() if j.started_at else None,
            "finished_at": j.finished_at.isoformat() if j.finished_at else None,
        }
        for j in jobs
    ]


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
    """Retry failed tracks from a failed download/bulk_download job."""
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

    failed_tracks = [t for t in tracks if t.get("status") == "failed"]
    if not failed_tracks:
        return {"error": "No failed tracks to retry"}

    new_job_id = str(uuid.uuid4())

    async def do_retry():
        async with async_session() as db:
            from backend.services.soulseek import search_and_download
            from backend.api.download import is_blacklisted
            from backend.config import get_settings
            import asyncio

            track_statuses = [
                {"artist": t.get("artist", ""), "track": t.get("track", ""), "status": "pending"}
                for t in failed_tracks
            ]
            new_job = Job(
                id=new_job_id, type="bulk_download", card="dl", status="running",
                total=len(failed_tracks), started_at=datetime.utcnow(),
                tracks=json.dumps(track_statuses),
            )
            db.add(new_job)
            await db.commit()
            await broadcast_job_update({"id": new_job_id, "type": "bulk_download", "status": "running", "progress": 0, "total": len(failed_tracks)})

            settings = get_settings()
            semaphore = asyncio.Semaphore(settings.soulseek.max_workers)

            async def download_one(idx: int, t: dict):
                async with semaphore:
                    try:
                        reason = await is_blacklisted(db, t.get("artist", ""), t.get("track", ""))
                        if reason:
                            track_statuses[idx]["status"] = "skipped"
                            track_statuses[idx]["reason"] = reason
                        else:
                            result = await search_and_download(t.get("artist", ""), t.get("track", ""))
                            ok = result.get("ok") or result.get("status") == "downloading"
                            track_statuses[idx]["status"] = "downloaded" if ok else "failed"
                    except Exception as e:
                        track_statuses[idx]["status"] = "failed"

                    new_job.progress = sum(1 for s in track_statuses if s["status"] != "pending")
                    new_job.tracks = json.dumps(track_statuses)
                    await db.merge(new_job)
                    await db.commit()
                    await broadcast_job_update({"id": new_job_id, "type": "bulk_download", "status": "running", "progress": new_job.progress, "total": len(failed_tracks)})

            tasks = [download_one(i, t) for i, t in enumerate(failed_tracks)]
            await asyncio.gather(*tasks, return_exceptions=True)

            new_job.status = "completed"
            new_job.finished_at = datetime.utcnow()
            new_job.tracks = json.dumps(track_statuses)
            await db.merge(new_job)
            await db.commit()
            await broadcast_job_update({"id": new_job_id, "type": "bulk_download", "status": "completed", "progress": len(failed_tracks), "total": len(failed_tracks)})

    background_tasks.add_task(do_retry)
    return {"job_id": new_job_id}


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
