"""Download API routes - Soulseek search and download triggers."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime

log = logging.getLogger(__name__)

# Module-level download queue — limits concurrent download jobs
_download_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    """Lazy-init semaphore with configured max_concurrent_downloads."""
    global _download_semaphore
    if _download_semaphore is None:
        from backend.config import get_settings
        limit = get_settings().soulseek.max_concurrent_downloads
        _download_semaphore = asyncio.Semaphore(limit)
        log.info(f"[download] Queue initialized: max {limit} concurrent downloads")
    return _download_semaphore


def reset_download_semaphore():
    """Reset semaphore after config change. New limit takes effect for next downloads."""
    global _download_semaphore
    _download_semaphore = None


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

        # Fetch reputation scores for sorting (recently-failed peers sort last)
        for r in results:
            r["rep_score"] = await client.reputation.get_score_adjustment(r["username"])

        # Sort: reputation + format + slots + size
        format_order = {"flac": 0, "wav": 1, "alac": 1, "mp3": 2, "m4a": 3, "ogg": 3, "opus": 3}
        results.sort(key=lambda r: (format_order.get(r["extension"], 9), -r.get("rep_score", 0), not r["slots_free"], -r["size"]))

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
        from backend.services.scanner import import_downloaded_file
        async with async_session() as db:
            desc = f"{req.artist} — {req.track}"
            sem = _get_semaphore()

            # If semaphore is full, show as queued
            if sem.locked():
                job = Job(
                    id=job_id, type="download", card="dl", status="pending",
                    started_at=datetime.utcnow(),
                    tracks=json.dumps([{"artist": req.artist, "track": req.track, "status": "queued"}]),
                )
                db.add(job)
                await db.commit()
                await broadcast_job_update({"id": job_id, "type": "download", "status": "pending", "progress": 0, "total": 1, "description": f"Queued: {desc}"})
                async with sem:
                    job.status = "running"
                    await db.merge(job)
                    await db.commit()
                    await broadcast_job_update({"id": job_id, "type": "download", "status": "running", "progress": 0, "total": 1, "description": desc})
                    await _do_download_inner(db, job, job_id, desc, req)
            else:
                job = Job(
                    id=job_id, type="download", card="dl", status="running",
                    started_at=datetime.utcnow(),
                    tracks=json.dumps([{"artist": req.artist, "track": req.track, "status": "pending"}]),
                )
                db.add(job)
                await db.commit()
                await broadcast_job_update({"id": job_id, "type": "download", "status": "running", "progress": 0, "total": 1, "description": desc})
                async with sem:
                    await _do_download_inner(db, job, job_id, desc, req)

    background_tasks.add_task(do_download)
    return {"job_id": job_id}


async def _do_download_inner(db, job, job_id, desc, req):
    """Core download logic — runs inside the download semaphore."""
    import asyncio
    from backend.soulseek import get_client
    from backend.soulseek.protocol.types import TransferState
    from backend.services.scanner import import_downloaded_file

    def _file_size(path):
        """Get file size in bytes, or 0 if unavailable."""
        try:
            import os
            return os.path.getsize(path) if path else 0
        except Exception:
            return 0

    async def poll_transfer(client, username, filename, timeout_polls=150, queue_timeout=120, stall_timeout=60, check_cancel=True):
        """Poll transfer until terminal state. Returns (status, save_path, error)."""
        import time
        last_bytes = 0
        stall_start = None
        queue_start = time.monotonic()
        for _ in range(timeout_polls):
            await asyncio.sleep(2)
            if check_cancel:
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
                # check_cancel=False: parallel sources share the outer db session
                status, save_path, error = await poll_transfer(native_client, dl_username, dl_filename, check_cancel=False)
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
                source_errors = []
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
                        else:
                            source_errors.append({"user": cand["username"], "error": error or status})
                    if winner:
                        for t in pending:
                            t.cancel()
                        break

                if winner:
                    cand, save_path = winner
                    short = cand["filename"].rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
                    fsize = _file_size(save_path)
                    track_id = await import_downloaded_file(db, save_path, artist_hint=req.artist)
                    job.status = "completed"
                    job.result = json.dumps({"username": cand["username"], "filename": cand["filename"], "save_path": save_path, "file_size": fsize, "sources_tried": len(batch), "strategy": "first", "track_id": track_id})
                    job.tracks = json.dumps([{"artist": req.artist, "track": req.track, "status": "downloaded", "username": cand["username"], "filename": short, "file_size": fsize, "track_id": track_id}])
                else:
                    failed_users = [c["username"] for c in batch]
                    last_err = source_errors[-1]["error"] if source_errors else "unknown"
                    job.status = "failed"
                    job.result = json.dumps({"message": f"All {len(batch)} parallel sources failed", "last_error": last_err, "strategy": "first", "failed_sources": failed_users, "source_errors": source_errors})
                    job.tracks = json.dumps([{"artist": req.artist, "track": req.track, "status": "failed", "error": last_err}])

            else:
                # "best" strategy — wait for all, keep highest quality
                results_all = await asyncio.gather(*[try_source(c) for c in batch], return_exceptions=True)
                completed = []
                source_errors = []
                for r in results_all:
                    if isinstance(r, Exception):
                        source_errors.append({"user": "unknown", "error": str(r)})
                        continue
                    cand, status, save_path, error = r
                    if status == "completed" and save_path:
                        completed.append((cand, save_path))
                    else:
                        source_errors.append({"user": cand["username"], "error": error or status})

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
                    track_id = await import_downloaded_file(db, best_path, artist_hint=req.artist)
                    job.status = "completed"
                    job.result = json.dumps({"username": best_cand["username"], "filename": best_cand["filename"], "save_path": best_path, "file_size": fsize, "sources_tried": len(batch), "sources_completed": len(completed), "strategy": "best", "track_id": track_id})
                    job.tracks = json.dumps([{"artist": req.artist, "track": req.track, "status": "downloaded", "username": best_cand["username"], "filename": short, "file_size": fsize, "track_id": track_id}])
                else:
                    failed_users = [c["username"] for c in batch]
                    last_err = source_errors[-1]["error"] if source_errors else "unknown"
                    job.status = "failed"
                    job.result = json.dumps({"message": f"All {len(batch)} parallel sources failed", "last_error": last_err, "strategy": "best", "failed_sources": failed_users, "source_errors": source_errors})
                    job.tracks = json.dumps([{"artist": req.artist, "track": req.track, "status": "failed", "error": last_err}])

        elif candidates and native_client:
            # === Sequential download (parallel_sources == 1, original behavior) ===
            last_error = ""
            source_errors = []  # [(username, error), ...]
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
                except (asyncio.TimeoutError, ConnectionRefusedError, OSError) as e:
                    # Transient network errors — don't penalize reputation
                    log.warning(f"[download] Transient connection error to {dl_username}: {e}")
                    last_error = f"Connection timeout: {e}"
                    source_errors.append({"user": dl_username, "error": last_error})
                    continue
                except Exception as e:
                    log.warning(f"[download] Failed to connect to {dl_username}: {e}")
                    last_error = f"Connection failed: {e}"
                    source_errors.append({"user": dl_username, "error": last_error})
                    await native_client.reputation.record_failure(dl_username)
                    continue

                status, save_path, error = await poll_transfer(native_client, dl_username, dl_filename)
                log.info(f"[download] Result: {dl_username} / {short_name} → {status} ({error or 'ok'})")

                if status == "completed":
                    await native_client.reputation.record_success(dl_username)
                    fsize = _file_size(save_path)
                    track_id = await import_downloaded_file(db, save_path, artist_hint=req.artist)
                    job.status = "completed"
                    job.result = json.dumps({"username": dl_username, "filename": dl_filename, "save_path": save_path, "file_size": fsize, "attempt": i + 1, "sources_tried": len(source_errors) + 1, "track_id": track_id})
                    job.tracks = json.dumps([{"artist": req.artist, "track": req.track, "status": "downloaded", "username": dl_username, "filename": short_name, "file_size": fsize, "track_id": track_id}])
                    break
                elif status == "cancelled":
                    job.status = "failed"
                    job.result = json.dumps({"error": "Cancelled by user"})
                    job.tracks = json.dumps([{"artist": req.artist, "track": req.track, "status": "failed"}])
                    break
                else:
                    await native_client.reputation.record_failure(dl_username)
                    last_error = error or status
                    source_errors.append({"user": dl_username, "error": last_error})

            else:
                if candidates and job.status != "failed":
                    failed_users = [c["username"] for c in candidates]
                    job.status = "failed"
                    err_detail = last_error or "unknown"
                    job.result = json.dumps({
                        "message": f"All {len(candidates)} sources failed",
                        "last_error": err_detail,
                        "failed_sources": failed_users,
                        "source_errors": source_errors,
                    })
                    job.tracks = json.dumps([{"artist": req.artist, "track": req.track, "status": "failed", "error": err_detail}])

    except Exception as e:
        log.warning(f"[download] Job {job_id} exception: {e}", exc_info=True)
        job.status = "failed"
        job.result = json.dumps({"error": str(e)})
    finally:
        job.finished_at = datetime.utcnow()
        await db.merge(job)
        await db.commit()
        await broadcast_job_update({"id": job_id, "type": "download", "status": job.status, "progress": 1, "total": 1, "description": desc})
        # Clean up zero-byte and non-audio leftovers in download dir
        try:
            from backend.services.scanner import cleanup_download_dir
            cleanup_download_dir()
        except Exception as e:
            log.debug(f"[download] Cleanup skipped: {e}")

async def enqueue_download(artist: str, track: str) -> str:
    """Create an individual download job with semaphore queuing. Returns job_id."""
    job_id = str(uuid.uuid4())
    desc = f"{artist} — {track}"
    dl_req = DownloadRequest(artist=artist, track=track)
    sem = _get_semaphore()
    async with async_session() as sess:
        if sem.locked():
            job = Job(
                id=job_id, type="download", card="dl", status="pending",
                started_at=datetime.utcnow(),
                tracks=json.dumps([{"artist": artist, "track": track, "status": "queued"}]),
            )
            sess.add(job)
            await sess.commit()
            await broadcast_job_update({"id": job_id, "type": "download", "status": "pending", "progress": 0, "total": 1, "description": f"Queued: {desc}"})
            async with sem:
                job.status = "running"
                await sess.merge(job)
                await sess.commit()
                await broadcast_job_update({"id": job_id, "type": "download", "status": "running", "progress": 0, "total": 1, "description": desc})
                await _do_download_inner(sess, job, job_id, desc, dl_req)
        else:
            job = Job(
                id=job_id, type="download", card="dl", status="running",
                started_at=datetime.utcnow(),
                tracks=json.dumps([{"artist": artist, "track": track, "status": "pending"}]),
            )
            sess.add(job)
            await sess.commit()
            await broadcast_job_update({"id": job_id, "type": "download", "status": "running", "progress": 0, "total": 1, "description": desc})
            async with sem:
                await _do_download_inner(sess, job, job_id, desc, dl_req)
    return job_id


@router.post("/bulk")
async def bulk_download(req: BulkDownloadRequest, background_tasks: BackgroundTasks):
    """Download multiple tracks as individual download jobs."""
    for t in req.tracks:
        artist = t.get("artist", "")
        track = t.get("track", "")
        if artist and track:
            background_tasks.add_task(enqueue_download, artist, track)

    return {"ok": True, "total": len(req.tracks)}


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


@router.get("/soulseek-stats")
async def soulseek_stats():
    """Get Soulseek client stats — connection, shares, peers, transfers."""
    from backend.soulseek import get_client
    from backend.soulseek.shares import get_share_counts

    client = get_client()
    num_dirs, num_files = get_share_counts()

    import time

    if not client:
        return {
            "connected": False,
            "username": None,
            "peers": 0,
            "shared_folders": num_dirs,
            "shared_files": num_files,
            "listen_port": None,
            "uptime_seconds": 0,
            "reconnects": 0,
            "active_searches": 0,
            "active_transfers": 0,
            "queued_transfers": 0,
            "completed_transfers": 0,
            "failed_transfers": 0,
            "total_bytes_transferred": 0,
            "aggregate_speed": 0,
            "reputation": {"tracked_peers": 0, "peers": []},
        }

    transfers = client.transfers.get_all_transfers()
    active = sum(1 for t in transfers if t.get("state") in ("transferring", "connected"))
    queued = sum(1 for t in transfers if t.get("state") in ("requested", "queued"))
    completed = sum(1 for t in transfers if t.get("state") == "completed")
    failed = sum(1 for t in transfers if t.get("state") in ("failed", "denied"))
    total_bytes = sum(t.get("received_bytes", 0) for t in transfers)
    agg_speed = sum(t.get("speed", 0) for t in transfers if t.get("state") == "transferring")

    uptime = 0.0
    if client.server.connected_since:
        uptime = time.time() - client.server.connected_since

    return {
        "connected": client.logged_in,
        "username": client.username,
        "peers": len(client.peers),
        "shared_folders": num_dirs,
        "shared_files": num_files,
        "listen_port": client.server.listen_port,
        "uptime_seconds": round(uptime),
        "reconnects": client.server.total_reconnects,
        "active_searches": len(client._search_events),
        "active_transfers": active,
        "queued_transfers": queued,
        "completed_transfers": completed,
        "failed_transfers": failed,
        "total_bytes_transferred": total_bytes,
        "aggregate_speed": round(agg_speed),
        "reputation": client.reputation.get_summary(),
    }


@router.get("/soulseek-stats/history")
async def soulseek_stats_history(hours: int = 24, db: AsyncSession = Depends(get_db)):
    """Get historical Soulseek stats for charting."""
    from backend.models.stats import SoulseekSnapshot
    from datetime import timedelta

    cutoff = datetime.utcnow() - timedelta(hours=hours)
    result = await db.execute(
        select(SoulseekSnapshot)
        .where(SoulseekSnapshot.timestamp >= cutoff)
        .order_by(SoulseekSnapshot.timestamp)
    )
    snapshots = result.scalars().all()
    return [
        {
            "timestamp": s.timestamp.isoformat(),
            "connected": s.connected,
            "peers": s.peers,
            "active_transfers": s.active_transfers,
            "completed_transfers": s.completed_transfers,
            "failed_transfers": s.failed_transfers,
            "queued_transfers": s.queued_transfers,
            "bytes_transferred": s.bytes_transferred,
            "speed": s.speed,
            "active_searches": s.active_searches,
        }
        for s in snapshots
    ]


@router.post("/reset-reputation")
async def reset_reputation():
    """Clear all peer reputation data (cooldowns + scores)."""
    from backend.soulseek import get_client

    client = get_client()
    if not client:
        return {"cleared": 0}

    count = await client.reputation.reset_all()
    return {"cleared": count}


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
