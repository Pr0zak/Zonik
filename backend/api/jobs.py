from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.job import Job

router = APIRouter()


@router.get("")
async def list_jobs(limit: int = 50, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Job).order_by(Job.started_at.desc()).limit(limit)
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
        }
        for j in jobs
    ]


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
