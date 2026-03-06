"""Download API routes - Soulseek search and download triggers."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime

log = logging.getLogger(__name__)

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
    artist: str = ""
    track: str = ""
    query: str = ""


class DownloadRequest(BaseModel):
    artist: str
    track: str
    username: str | None = None
    filename: str | None = None


class BulkDownloadRequest(BaseModel):
    tracks: list[dict]  # [{artist, track}, ...]


@router.post("/search")
async def search_soulseek(req: SearchRequest, db: AsyncSession = Depends(get_db)):
    """Search Soulseek P2P network — returns all results with quality info."""
    # Support single query field or artist+track
    artist = req.artist.strip()
    track = req.track.strip()
    if not artist and not track and req.query.strip():
        # Try to split "Artist - Track" from query
        q = req.query.strip()
        parts = [p.strip() for p in q.split(" - ", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            artist, track = parts[0], parts[1]
        else:
            artist, track = q, ""

    reason = await is_blacklisted(db, artist, track) if artist else None
    if reason:
        return {"results": [], "count": 0, "users": 0, "blacklisted": True, "reason": reason}

    from backend.soulseek import get_client
    client = get_client()

    if client and client.logged_in:
        # Native client — return all results
        query = f"{artist} {track}".strip()
        search_results = await client.search(query, timeout=25, max_responses=100)

        results = []
        users = set()
        min_size = 3 * 1024 * 1024
        for sr in search_results:
            for fi in sr.files:
                fn = fi.filename
                ext = ""
                for e in [".flac", ".wav", ".alac", ".mp3", ".m4a", ".ogg", ".opus"]:
                    if fn.lower().endswith(e):
                        ext = e[1:]
                        break
                if not ext or fi.size < min_size:
                    continue
                # Basic relevance: at least some query words should match
                from backend.services.soulseek import words_match, strip_track_extras
                match_term = track if track else artist
                if not words_match(match_term, fn) and not words_match(strip_track_extras(match_term), fn):
                    continue
                users.add(sr.username)
                results.append({
                    "username": sr.username,
                    "filename": fn,
                    "size": fi.size,
                    "bitrate": fi.bitrate,
                    "extension": ext,
                    "slots_free": sr.slots_free,
                    "speed": sr.avg_speed,
                    "queue_length": sr.queue_length,
                })

        # Mark cooled-down / blocked peers
        for r in results:
            r["on_cooldown"] = await client.reputation.is_blocked(r["username"])

        # Sort: FLAC first, then by size descending, slots_free preferred, cooldown peers last
        format_order = {"flac": 0, "wav": 1, "alac": 1, "mp3": 2, "m4a": 3, "ogg": 3, "opus": 3}
        results.sort(key=lambda r: (r.get("on_cooldown", False), format_order.get(r["extension"], 9), not r["slots_free"], -r["size"]))

        return {"results": results, "count": len(results), "users": len(users)}

    # Legacy slskd fallback — limited results
    candidates = await search_multi_strategy(artist, track)
    return {
        "results": [
            {
                "username": c.get("username", ""),
                "filename": c.get("filename", ""),
                "size": c.get("size", 0),
                "bitrate": c.get("bitRate", 0) or c.get("bitrate", 0),
                "extension": c.get("filename", "").rsplit(".", 1)[-1] if "." in c.get("filename", "") else "",
                "slots_free": True,
                "speed": 0,
                "queue_length": 0,
            }
            for c in candidates
        ],
        "count": len(candidates),
        "users": len(set(c.get("username", "") for c in candidates)),
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

            def _file_size(path):
                """Get file size in bytes, or 0 if unavailable."""
                try:
                    import os
                    return os.path.getsize(path) if path else 0
                except Exception:
                    return 0

            async def poll_transfer(client, username, filename, timeout_polls=150, queue_timeout=120, stall_timeout=60):
                """Poll transfer until terminal state. Returns (status, save_path, error)."""
                import time
                last_bytes = 0
                stall_start = None
                queue_start = time.monotonic()
                for _ in range(timeout_polls):
                    await asyncio.sleep(2)
                    await db.refresh(job)
                    if job.status == "failed":
                        return "cancelled", None, "Cancelled by user"
                    transfer = client.transfers.get_transfer(username, filename)
                    if not transfer:
                        return "failed", None, "Transfer removed"
                    if transfer.state == TransferState.COMPLETED:
                        return "completed", transfer.save_path, None
                    elif transfer.state in (TransferState.FAILED, TransferState.DENIED):
                        return "failed", None, transfer.error or transfer.state

                    # Waiting for peer to accept (REQUESTED/QUEUED) — use queue timeout
                    if transfer.state in (TransferState.REQUESTED, TransferState.QUEUED):
                        if time.monotonic() - queue_start > queue_timeout:
                            client.transfers.update_state(transfer, TransferState.FAILED, error="Peer did not respond")
                            client.transfers.remove_transfer(username, filename)
                            return "failed", None, "Peer did not respond in time"
                        continue  # Don't check stall yet

                    # CONNECTED/TRANSFERRING — detect data stall
                    if transfer.received_bytes > last_bytes:
                        last_bytes = transfer.received_bytes
                        stall_start = None
                    else:
                        if stall_start is None:
                            stall_start = time.monotonic()
                        elif time.monotonic() - stall_start > stall_timeout:
                            client.transfers.update_state(transfer, TransferState.FAILED, error="Stalled (no data)")
                            client.transfers.remove_transfer(username, filename)
                            return "failed", None, "Transfer stalled — no data received"
                return "timeout", None, "Transfer monitoring timed out"

            try:
                native_client = get_client()
                from backend.config import get_settings as _get_settings
                dl_settings = _get_settings()
                parallel_sources = dl_settings.soulseek.parallel_sources
                source_strategy = dl_settings.soulseek.source_strategy

                if req.username and req.filename and native_client:
                    # Direct download — try requested source first, then fall back to search
                    candidates = [{"username": req.username, "filename": req.filename, "size": 0}]
                    try:
                        from backend.soulseek.search import search_multi_strategy_native
                        fallbacks = await search_multi_strategy_native(native_client, req.artist, req.track)
                        # Add fallbacks excluding the already-requested source
                        for fb in fallbacks:
                            if fb["username"] != req.username:
                                candidates.append(fb)
                        candidates = candidates[:5]  # Limit total attempts
                    except Exception as e:
                        log.debug("Fallback search failed: %s", e)
                elif native_client:
                    # Auto-download — get candidates from search
                    from backend.soulseek.search import search_multi_strategy_native
                    candidates = await search_multi_strategy_native(native_client, req.artist, req.track)
                else:
                    from backend.services.soulseek import search_and_download
                    result = await search_and_download(req.artist, req.track)
                    ok = result.get("ok") or result.get("status") == "downloading"
                    job.status = "completed" if ok else "failed"
                    job.result = json.dumps(result)
                    job.tracks = json.dumps([{"artist": req.artist, "track": req.track, "status": "downloaded" if ok else "failed"}])
                    candidates = []  # Skip native loop

                if native_client and not candidates:
                    job.status = "failed"
                    job.result = json.dumps({"message": f"No results for {req.artist} - {req.track}"})
                    job.tracks = json.dumps([{"artist": req.artist, "track": req.track, "status": "failed"}])

                # Filter out blocked peers
                if candidates and native_client:
                    candidates = [c for c in candidates if not await native_client.reputation.is_blocked(c["username"])]

                if candidates and native_client and parallel_sources > 1:
                    # === Multi-source parallel download ===
                    batch = candidates[:parallel_sources]
                    usernames_str = ", ".join(c["username"] for c in batch)
                    job.tracks = json.dumps([{
                        "artist": req.artist, "track": req.track, "status": "downloading",
                        "sources": len(batch),
                    }])
                    await db.merge(job)
                    await db.commit()
                    await broadcast_job_update({"id": job_id, "type": "download", "status": "running", "progress": 0, "total": 1, "description": f"{desc} — {len(batch)} sources"})

                    # Start all downloads concurrently
                    async def try_source(candidate):
                        """Attempt download from one source. Returns (candidate, status, save_path, error)."""
                        dl_username = candidate["username"]
                        dl_filename = candidate["filename"]
                        try:
                            await native_client.download(dl_username, dl_filename)
                            log.info(f"[download] Multi-source queued: {dl_username}")
                        except Exception as e:
                            await native_client.reputation.record_failure(dl_username)
                            return candidate, "failed", None, str(e)
                        status, save_path, error = await poll_transfer(native_client, dl_username, dl_filename)
                        if status == "completed":
                            await native_client.reputation.record_success(dl_username)
                            return candidate, "completed", save_path, None
                        else:
                            await native_client.reputation.record_failure(dl_username)
                            return candidate, status, None, error

                    if source_strategy == "first":
                        # Race — keep first completed, cancel the rest
                        tasks_map = {}
                        for c in batch:
                            task = asyncio.create_task(try_source(c))
                            tasks_map[task] = c

                        winner = None
                        pending = set(tasks_map.keys())
                        while pending:
                            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                            for task in done:
                                cand, status, save_path, error = task.result()
                                if status == "completed" and not winner:
                                    winner = (cand, save_path)
                                elif status == "completed" and winner:
                                    # Duplicate completed — remove the extra file
                                    if save_path:
                                        try:
                                            from pathlib import Path
                                            Path(save_path).unlink(missing_ok=True)
                                        except Exception:
                                            pass
                            if winner:
                                for t in pending:
                                    t.cancel()
                                break

                        if winner:
                            cand, save_path = winner
                            short = cand["filename"].rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
                            fsize = _file_size(save_path)
                            job.status = "completed"
                            job.result = json.dumps({"username": cand["username"], "filename": cand["filename"], "save_path": save_path, "file_size": fsize, "sources_tried": len(batch), "strategy": "first"})
                            job.tracks = json.dumps([{"artist": req.artist, "track": req.track, "status": "downloaded", "username": cand["username"], "filename": short, "file_size": fsize}])
                        else:
                            failed_users = [c["username"] for c in batch]
                            job.status = "failed"
                            job.result = json.dumps({"message": f"All {len(batch)} parallel sources failed", "strategy": "first", "failed_sources": failed_users})
                            job.tracks = json.dumps([{"artist": req.artist, "track": req.track, "status": "failed"}])

                    else:
                        # "best" strategy — wait for all, keep highest quality
                        results_all = await asyncio.gather(*[try_source(c) for c in batch], return_exceptions=True)
                        completed = []
                        for r in results_all:
                            if isinstance(r, Exception):
                                continue
                            cand, status, save_path, error = r
                            if status == "completed" and save_path:
                                completed.append((cand, save_path))

                        if completed:
                            def _quality_score(item):
                                cand, path = item
                                ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
                                fmt_scores = {"flac": 20, "wav": 18, "alac": 18, "mp3": 5, "m4a": 3, "ogg": 3, "opus": 3}
                                score = fmt_scores.get(ext, 0)
                                score += cand.get("bitRate", 0) or 0
                                score += (cand.get("size", 0) or 0) // (1024 * 1024)
                                return score

                            completed.sort(key=_quality_score, reverse=True)
                            best_cand, best_path = completed[0]

                            # Delete the losers
                            for cand, path in completed[1:]:
                                try:
                                    from pathlib import Path
                                    Path(path).unlink(missing_ok=True)
                                except Exception:
                                    pass

                            short = best_cand["filename"].rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
                            fsize = _file_size(best_path)
                            job.status = "completed"
                            job.result = json.dumps({"username": best_cand["username"], "filename": best_cand["filename"], "save_path": best_path, "file_size": fsize, "sources_tried": len(batch), "sources_completed": len(completed), "strategy": "best"})
                            job.tracks = json.dumps([{"artist": req.artist, "track": req.track, "status": "downloaded", "username": best_cand["username"], "filename": short, "file_size": fsize}])
                        else:
                            failed_users = [c["username"] for c in batch]
                            job.status = "failed"
                            job.result = json.dumps({"message": f"All {len(batch)} parallel sources failed", "strategy": "best", "failed_sources": failed_users})
                            job.tracks = json.dumps([{"artist": req.artist, "track": req.track, "status": "failed"}])

                elif candidates and native_client:
                    # === Sequential download (parallel_sources == 1, original behavior) ===
                    last_error = ""
                    for i, candidate in enumerate(candidates):
                        dl_username = candidate["username"]
                        dl_filename = candidate["filename"]
                        short_name = dl_filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] if dl_filename else ""

                        attempt_label = f"attempt {i+1}/{len(candidates)}"
                        job.tracks = json.dumps([{
                            "artist": req.artist, "track": req.track, "status": "downloading",
                            "username": dl_username, "filename": short_name,
                        }])
                        await db.merge(job)
                        await db.commit()
                        await broadcast_job_update({"id": job_id, "type": "download", "status": "running", "progress": 0, "total": 1, "description": f"{desc} — {short_name} ({attempt_label})"})

                        try:
                            await native_client.download(dl_username, dl_filename)
                            log.info(f"[download] Transfer queued: {dl_username} / {short_name}")
                        except Exception as e:
                            log.warning(f"[download] Failed to connect to {dl_username}: {e}")
                            last_error = f"Connection failed: {e}"
                            await native_client.reputation.record_failure(dl_username)
                            continue

                        status, save_path, error = await poll_transfer(native_client, dl_username, dl_filename)
                        log.info(f"[download] Result: {dl_username} / {short_name} → {status} ({error or 'ok'})")

                        if status == "completed":
                            await native_client.reputation.record_success(dl_username)
                            fsize = _file_size(save_path)
                            job.status = "completed"
                            job.result = json.dumps({"username": dl_username, "filename": dl_filename, "save_path": save_path, "file_size": fsize, "attempt": i + 1})
                            job.tracks = json.dumps([{"artist": req.artist, "track": req.track, "status": "downloaded", "username": dl_username, "filename": short_name, "file_size": fsize}])
                            break
                        elif status == "cancelled":
                            job.status = "failed"
                            job.result = json.dumps({"error": "Cancelled by user"})
                            job.tracks = json.dumps([{"artist": req.artist, "track": req.track, "status": "failed"}])
                            break
                        else:
                            await native_client.reputation.record_failure(dl_username)
                            last_error = error or status

                    else:
                        if candidates and job.status != "failed":
                            failed_users = [c["username"] for c in candidates]
                            job.status = "failed"
                            err_detail = last_error or "unknown"
                            job.result = json.dumps({"message": f"All {len(candidates)} sources failed", "last_error": err_detail, "failed_sources": failed_users})
                            job.tracks = json.dumps([{"artist": req.artist, "track": req.track, "status": "failed"}])

            except Exception as e:
                log.warning(f"[download] Job {job_id} exception: {e}", exc_info=True)
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
                                track_statuses[idx]["status"] = "downloaded"
                                track_statuses[idx]["username"] = result.get("username", "")
                                fn = result.get("filename", "")
                                track_statuses[idx]["filename"] = fn.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] if fn else ""
                                track_statuses[idx]["file_size"] = result.get("size", 0)
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
