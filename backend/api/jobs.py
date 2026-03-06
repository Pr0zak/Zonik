from __future__ import annotations

import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy import select, delete, func
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
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar()
    query = base.order_by(Job.started_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    jobs = result.scalars().all()
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
            from backend.api.download import is_blacklisted
            from backend.config import get_settings
            from backend.services.scanner import import_downloaded_file
            import asyncio
            import time as _time

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

            # Try native client first, fall back to facade
            native_client = None
            try:
                from backend.soulseek import get_client
                from backend.soulseek.search import search_multi_strategy_native
                from backend.soulseek.protocol.types import TransferState
                native_client = get_client()
            except Exception:
                pass

            max_retries = 3

            async def poll_transfer(client, username, filename, timeout=150):
                """Poll transfer until done. Returns (save_path, error)."""
                queue_start = _time.monotonic()
                last_bytes = 0
                stall_start = None
                for _ in range(timeout):
                    await asyncio.sleep(2)
                    transfer = client.transfers.get_transfer(username, filename)
                    if not transfer:
                        return None, "Transfer removed"
                    if transfer.state == TransferState.COMPLETED:
                        return transfer.save_path, None
                    if transfer.state in (TransferState.FAILED, TransferState.DENIED):
                        return None, transfer.error or str(transfer.state)
                    if transfer.state in (TransferState.REQUESTED, TransferState.QUEUED):
                        if _time.monotonic() - queue_start > 120:
                            return None, "Peer did not respond"
                        continue
                    if transfer.received_bytes > last_bytes:
                        last_bytes = transfer.received_bytes
                        stall_start = None
                    elif stall_start is None:
                        stall_start = _time.monotonic()
                    elif _time.monotonic() - stall_start > 60:
                        return None, "Transfer stalled"
                return None, "Timeout"

            async def download_one(idx: int, t: dict):
                async with semaphore:
                    artist = t.get("artist", "")
                    track = t.get("track", "")
                    try:
                        reason = await is_blacklisted(db, artist, track)
                        if reason:
                            track_statuses[idx]["status"] = "skipped"
                            track_statuses[idx]["reason"] = reason
                        elif native_client:
                            # Native path: search → download → poll → import
                            candidates = await search_multi_strategy_native(native_client, artist, track)
                            if not candidates:
                                track_statuses[idx]["status"] = "failed"
                                track_statuses[idx]["error"] = "No results"
                            else:
                                last_error = ""
                                for cand in candidates[:max_retries]:
                                    un = cand["username"]
                                    fn = cand["filename"]
                                    short = fn.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
                                    try:
                                        await native_client.download(un, fn)
                                        save_path, error = await poll_transfer(native_client, un, fn)
                                        if save_path:
                                            await native_client.reputation.record_success(un)
                                            import os
                                            fsize = os.path.getsize(save_path) if save_path else 0
                                            track_id = await import_downloaded_file(db, save_path, artist_hint=artist)
                                            track_statuses[idx]["status"] = "downloaded"
                                            track_statuses[idx]["username"] = un
                                            track_statuses[idx]["filename"] = short
                                            track_statuses[idx]["file_size"] = fsize
                                            track_statuses[idx]["track_id"] = track_id
                                            break
                                        last_error = error or "Transfer failed"
                                        await native_client.reputation.record_failure(un)
                                    except Exception as e:
                                        last_error = str(e)
                                        await native_client.reputation.record_failure(un)
                                else:
                                    track_statuses[idx]["status"] = "failed"
                                    track_statuses[idx]["error"] = last_error
                        else:
                            # Legacy facade fallback
                            from backend.services.soulseek import search_and_download
                            last_error = ""
                            for attempt in range(max_retries):
                                result = await search_and_download(artist, track)
                                ok = result.get("ok") or result.get("status") == "downloading"
                                if ok:
                                    track_statuses[idx]["status"] = "downloaded"
                                    track_statuses[idx]["username"] = result.get("username", "")
                                    fn = result.get("filename", "")
                                    track_statuses[idx]["filename"] = fn.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] if fn else ""
                                    track_statuses[idx]["file_size"] = result.get("size", 0)
                                    break
                                last_error = result.get("message", "")
                                if attempt < max_retries - 1:
                                    await asyncio.sleep(5)
                            else:
                                track_statuses[idx]["status"] = "failed"
                                track_statuses[idx]["error"] = last_error
                    except Exception as e:
                        track_statuses[idx]["status"] = "failed"
                        track_statuses[idx]["error"] = str(e)

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
