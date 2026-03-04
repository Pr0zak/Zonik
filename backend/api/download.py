"""Download API routes - Soulseek search and download triggers."""
from __future__ import annotations

import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db, async_session
from backend.models.job import Job
from backend.services.soulseek import (
    search_multi_strategy, get_slskd_client, pick_best_results,
)

router = APIRouter()


class SearchRequest(BaseModel):
    artist: str
    track: str


class DownloadRequest(BaseModel):
    artist: str
    track: str
    username: str | None = None
    filename: str | None = None


class BulkDownloadRequest(BaseModel):
    tracks: list[dict]  # [{artist, track}, ...]


@router.post("/search")
async def search_soulseek(req: SearchRequest):
    """Search Soulseek for a track using multi-strategy search."""
    candidates = await search_multi_strategy(req.artist, req.track)
    return {
        "results": [
            {
                "username": c.get("username", ""),
                "filename": c.get("filename", ""),
                "size": c.get("size", 0),
                "bitRate": c.get("bitRate", 0) or c.get("bitrate", 0),
                "extension": c.get("filename", "").rsplit(".", 1)[-1] if "." in c.get("filename", "") else "",
            }
            for c in candidates
        ],
        "count": len(candidates),
    }


@router.post("/trigger")
async def trigger_download(req: DownloadRequest, background_tasks: BackgroundTasks):
    """Download a specific file or auto-search and download best result."""
    job_id = str(uuid.uuid4())

    async def do_download():
        async with async_session() as db:
            job = Job(
                id=job_id, type="download", card="dl", status="running",
                started_at=datetime.utcnow(),
                tracks=json.dumps([{"artist": req.artist, "track": req.track, "status": "pending"}]),
            )
            db.add(job)
            await db.commit()

            try:
                client = get_slskd_client()

                if req.username and req.filename:
                    # Direct download from specified peer
                    result = await client.download(req.username, req.filename)
                else:
                    # Auto-search and download best
                    from backend.services.soulseek import search_and_download
                    result = await search_and_download(req.artist, req.track)

                status = "completed" if result.get("ok") or result.get("status") == "downloading" else "failed"
                job.status = status
                job.result = json.dumps(result)
                job.tracks = json.dumps([{
                    "artist": req.artist, "track": req.track,
                    "status": "downloaded" if status == "completed" else "failed",
                }])
            except Exception as e:
                job.status = "failed"
                job.result = json.dumps({"error": str(e)})
            finally:
                job.finished_at = datetime.utcnow()
                await db.merge(job)
                await db.commit()

    background_tasks.add_task(do_download)
    return {"job_id": job_id}


@router.post("/bulk")
async def bulk_download(req: BulkDownloadRequest, background_tasks: BackgroundTasks):
    """Download multiple tracks in parallel."""
    job_id = str(uuid.uuid4())

    async def do_bulk():
        async with async_session() as db:
            track_statuses = [
                {"artist": t.get("artist", ""), "track": t.get("track", ""), "status": "pending"}
                for t in req.tracks
            ]
            job = Job(
                id=job_id, type="bulk_download", card="dl", status="running",
                total=len(req.tracks), started_at=datetime.utcnow(),
                tracks=json.dumps(track_statuses),
            )
            db.add(job)
            await db.commit()

            from backend.services.soulseek import search_and_download
            from backend.config import get_settings
            import asyncio

            settings = get_settings()
            semaphore = asyncio.Semaphore(settings.soulseek.max_workers)

            async def download_one(idx: int, t: dict):
                async with semaphore:
                    try:
                        result = await search_and_download(t.get("artist", ""), t.get("track", ""))
                        ok = result.get("ok") or result.get("status") == "downloading"
                        track_statuses[idx]["status"] = "downloaded" if ok else "failed"
                    except Exception as e:
                        track_statuses[idx]["status"] = "failed"

                    job.progress = sum(1 for s in track_statuses if s["status"] != "pending")
                    job.tracks = json.dumps(track_statuses)
                    await db.merge(job)
                    await db.commit()

            tasks = [download_one(i, t) for i, t in enumerate(req.tracks)]
            await asyncio.gather(*tasks, return_exceptions=True)

            job.status = "completed"
            job.finished_at = datetime.utcnow()
            job.tracks = json.dumps(track_statuses)
            await db.merge(job)
            await db.commit()

    background_tasks.add_task(do_bulk)
    return {"job_id": job_id, "total": len(req.tracks)}


@router.get("/status")
async def download_status():
    """Get current slskd download status."""
    client = get_slskd_client()
    downloads = await client.get_all_downloads()
    return {"downloads": downloads}
