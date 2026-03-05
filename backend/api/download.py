"""Download API routes - Soulseek search and download triggers."""
from __future__ import annotations

import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db, async_session
from backend.models.job import Job
from backend.models.blacklist import DownloadBlacklist
from backend.services.soulseek import (
    search_multi_strategy, pick_best_results, normalize_text,
)
from backend.api.websocket import broadcast_job_update

router = APIRouter()


async def is_blacklisted(db: AsyncSession, artist: str, track: str) -> str | None:
    """Check if artist/track is blacklisted. Returns reason or None."""
    artist_norm = normalize_text(artist)
    result = await db.execute(select(DownloadBlacklist))
    for entry in result.scalars().all():
        if normalize_text(entry.artist) == artist_norm:
            if entry.track is None:
                return entry.reason or "Artist blacklisted"
            if normalize_text(entry.track) == normalize_text(track):
                return entry.reason or "Track blacklisted"
    return None


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
async def search_soulseek(req: SearchRequest, db: AsyncSession = Depends(get_db)):
    """Search Soulseek for a track using multi-strategy search."""
    reason = await is_blacklisted(db, req.artist, req.track)
    if reason:
        return {"results": [], "count": 0, "blacklisted": True, "reason": reason}

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
async def trigger_download(req: DownloadRequest, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """Download a specific file or auto-search and download best result."""
    reason = await is_blacklisted(db, req.artist, req.track)
    if reason:
        return {"error": "blacklisted", "reason": reason}

    job_id = str(uuid.uuid4())

    async def do_download():
        import asyncio
        from backend.soulseek import get_client
        from backend.soulseek.protocol.types import TransferState
        async with async_session() as db:
            job = Job(
                id=job_id, type="download", card="dl", status="running",
                started_at=datetime.utcnow(),
                tracks=json.dumps([{"artist": req.artist, "track": req.track, "status": "pending"}]),
            )
            db.add(job)
            await db.commit()
            desc = f"{req.artist} — {req.track}"
            await broadcast_job_update({"id": job_id, "type": "download", "status": "running", "progress": 0, "total": 1, "description": desc})

            try:
                native_client = get_client()

                if req.username and req.filename and native_client:
                    # Direct download via native client
                    transfer = await native_client.download(req.username, req.filename)
                    result = {"status": "downloading", "username": req.username, "filename": req.filename, "size": transfer.total_bytes}
                    dl_username = req.username
                    dl_filename = req.filename
                else:
                    from backend.services.soulseek import search_and_download
                    result = await search_and_download(req.artist, req.track)
                    dl_username = result.get("username", "")
                    dl_filename = result.get("filename", "")

                initiated = result.get("ok") or result.get("status") == "downloading"
                if not initiated:
                    job.status = "failed"
                    job.result = json.dumps(result)
                    job.tracks = json.dumps([{"artist": req.artist, "track": req.track, "status": "failed"}])
                else:
                    # Store download details
                    short_name = dl_filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] if dl_filename else ""
                    detail = {**result, "short_filename": short_name}
                    job.result = json.dumps(detail)
                    job.tracks = json.dumps([{
                        "artist": req.artist, "track": req.track, "status": "transferring",
                        "username": dl_username, "filename": short_name,
                        "size": result.get("size", 0),
                    }])
                    await db.merge(job)
                    await db.commit()
                    await broadcast_job_update({"id": job_id, "type": "download", "status": "running", "progress": 0, "total": 1, "description": f"{desc} — from {dl_username}"})

                    # Poll native transfer status until complete or timeout (5 min)
                    final_status = "completed"
                    for _ in range(60):
                        await asyncio.sleep(5)
                        # Check if job was cancelled
                        await db.refresh(job)
                        if job.status == "failed":
                            final_status = "failed"
                            break

                        if native_client:
                            transfer = native_client.transfers.get_transfer(dl_username, dl_filename)
                            if not transfer:
                                continue
                            state = transfer.state
                            if state == TransferState.COMPLETED:
                                final_status = "completed"
                                detail["save_path"] = transfer.save_path
                                break
                            elif state in (TransferState.FAILED, TransferState.DENIED):
                                final_status = "failed"
                                detail["transfer_error"] = transfer.error or state
                                break
                        else:
                            continue
                    else:
                        final_status = "completed"
                        detail["note"] = "Transfer monitoring timed out"

                    job.status = final_status
                    job.result = json.dumps(detail)
                    job.tracks = json.dumps([{
                        "artist": req.artist, "track": req.track,
                        "status": "downloaded" if final_status == "completed" else "failed",
                        "username": dl_username, "filename": short_name,
                    }])
            except Exception as e:
                job.status = "failed"
                job.result = json.dumps({"error": str(e)})
            finally:
                job.finished_at = datetime.utcnow()
                await db.merge(job)
                await db.commit()
                await broadcast_job_update({"id": job_id, "type": "download", "status": job.status, "progress": 1, "total": 1, "description": desc})

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
            await broadcast_job_update({"id": job_id, "type": "bulk_download", "status": "running", "progress": 0, "total": len(req.tracks)})

            from backend.services.soulseek import search_and_download
            from backend.config import get_settings
            import asyncio

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
                            if ok:
                                track_statuses[idx]["status"] = "downloading"
                                track_statuses[idx]["username"] = result.get("username", "")
                                fn = result.get("filename", "")
                                track_statuses[idx]["filename"] = fn.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] if fn else ""
                                track_statuses[idx]["size"] = result.get("size", 0)
                            else:
                                track_statuses[idx]["status"] = "failed"
                                track_statuses[idx]["error"] = result.get("message", "")
                    except Exception as e:
                        track_statuses[idx]["status"] = "failed"
                        track_statuses[idx]["error"] = str(e)

                    job.progress = sum(1 for s in track_statuses if s["status"] not in ("pending",))
                    job.tracks = json.dumps(track_statuses)
                    await db.merge(job)
                    await db.commit()
                    await broadcast_job_update({"id": job_id, "type": "bulk_download", "status": "running", "progress": job.progress, "total": len(req.tracks)})

            tasks = [download_one(i, t) for i, t in enumerate(req.tracks)]
            await asyncio.gather(*tasks, return_exceptions=True)

            job.status = "completed"
            job.finished_at = datetime.utcnow()
            job.tracks = json.dumps(track_statuses)
            await db.merge(job)
            await db.commit()
            await broadcast_job_update({"id": job_id, "type": "bulk_download", "status": "completed", "progress": len(req.tracks), "total": len(req.tracks)})

    background_tasks.add_task(do_bulk)
    return {"job_id": job_id, "total": len(req.tracks)}


class CancelTransferRequest(BaseModel):
    username: str
    filename: str


@router.post("/cancel-transfer")
async def cancel_transfer(req: CancelTransferRequest):
    """Cancel an active transfer in the native Soulseek client."""
    from backend.soulseek import get_client
    from backend.soulseek.protocol.types import TransferState
    client = get_client()
    if not client:
        return {"error": "Native client not available"}
    transfer = client.transfers.get_transfer(req.username, req.filename)
    if not transfer:
        return {"error": "Transfer not found"}
    client.transfers.update_state(transfer, TransferState.FAILED, error="Cancelled by user")
    client.transfers.remove_transfer(req.username, req.filename)
    from backend.api.websocket import broadcast_transfer_progress
    await broadcast_transfer_progress(client.transfers.get_all_transfers())
    return {"ok": True}


@router.get("/status")
async def download_status():
    """Get current download status from native Soulseek client."""
    from backend.soulseek import get_client
    client = get_client()
    if client:
        return {
            "downloads": client.transfers.get_all_transfers(),
            "logged_in": client.logged_in,
        }
    return {"downloads": [], "logged_in": False}


# --- Blacklist CRUD ---

class BlacklistEntry(BaseModel):
    artist: str
    track: str | None = None
    reason: str | None = None


@router.get("/blacklist")
async def list_blacklist(db: AsyncSession = Depends(get_db)):
    """Get all blacklist entries."""
    result = await db.execute(
        select(DownloadBlacklist).order_by(DownloadBlacklist.artist, DownloadBlacklist.track)
    )
    entries = result.scalars().all()
    return [
        {
            "id": e.id,
            "artist": e.artist,
            "track": e.track,
            "reason": e.reason,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in entries
    ]


@router.post("/blacklist")
async def add_to_blacklist(entry: BlacklistEntry, db: AsyncSession = Depends(get_db)):
    """Add an artist or track to the download blacklist."""
    bl = DownloadBlacklist(
        id=str(uuid.uuid4()),
        artist=entry.artist.strip(),
        track=entry.track.strip() if entry.track else None,
        reason=entry.reason,
    )
    db.add(bl)
    await db.commit()
    return {"id": bl.id, "artist": bl.artist, "track": bl.track}


@router.delete("/blacklist/{entry_id}")
async def remove_from_blacklist(entry_id: str, db: AsyncSession = Depends(get_db)):
    """Remove a blacklist entry."""
    result = await db.execute(select(DownloadBlacklist).where(DownloadBlacklist.id == entry_id))
    entry = result.scalar_one_or_none()
    if not entry:
        return {"error": "Not found"}
    await db.delete(entry)
    await db.commit()
    return {"ok": True}
