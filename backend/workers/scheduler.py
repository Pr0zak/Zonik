"""Scheduled task definitions and execution."""
from __future__ import annotations

import json
import logging
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import async_session
from backend.models.job import Job
from backend.models.schedule import ScheduleTask
from backend.models.track import Track
from backend.models.artist import Artist
from backend.models.favorite import Favorite
from backend.models.playlist import Playlist, PlaylistTrack
from backend.api.websocket import broadcast_job_update
from backend.services.library_match import batch_library_match
from backend.services.download_attempts import keys_in_backoff, attempt_key, upgrade_skip_ids
from backend.services.auto_download import is_infra_error, download_job_outcome

log = logging.getLogger(__name__)

# Friendly labels for task names (used in WebSocket broadcasts)
_TASK_LABELS = {
    "lastfm_top_tracks": "Top Charts Scan",
    "discover_similar": "Similar Tracks Scan",
    "discover_artists": "Similar Artists Scan",
    "library_scan": "Library Scan",
    "enrichment": "Enrichment",
    "audio_analysis": "Audio Analysis",

    "recommendation_refresh": "AI Recommendations",
    "upgrade_scan": "Quality Upgrade Scan",
    "remix_discovery": "Remix Discovery",
    "download_cleanup": "Download Cleanup",
    "job_cleanup": "Job History Cleanup",
}


async def run_task(task_name: str, db: AsyncSession, job_id: str | None = None):
    """Execute a scheduled task by name."""
    # Load task config for count
    task_row = (await db.execute(
        select(ScheduleTask).where(ScheduleTask.task_name == task_name)
    )).scalar_one_or_none()
    count = task_row.count if task_row and task_row.count else None
    task_config = {}
    if task_row and task_row.config:
        try:
            task_config = json.loads(task_row.config)
        except (ValueError, TypeError):
            pass

    if not job_id:
        job_id = str(uuid.uuid4())
    job = Job(
        id=job_id, type=task_name, card="sched", status="running",
        started_at=datetime.utcnow(),
    )
    db.add(job)
    await db.commit()
    desc = _TASK_LABELS.get(task_name, task_name)
    await broadcast_job_update({"id": job_id, "type": task_name, "status": "running", "progress": 0, "total": 1, "description": desc})

    try:
        if task_name == "library_scan":
            from backend.services.scanner import scan_library
            result = await scan_library(db)
            job.result = json.dumps(result)

        elif task_name == "enrichment":
            from backend.services.enrichment import enrich_batch
            query = select(Track.id).where(
                (Track.genre.is_(None)) | (Track.cover_art_path.is_(None))
            )
            tracks = (await db.execute(query)).scalars().all()
            result = await enrich_batch(db, tracks)
            job.result = json.dumps(result)

        elif task_name == "lastfm_top_tracks":
            await _run_lastfm_top_tracks(db, job, count=count or 50)

        elif task_name == "discover_similar":
            await _run_discover_similar(db, job, count=count or 10)

        elif task_name == "lastfm_sync":
            await _run_lastfm_loved_sync(db, job)

        elif task_name == "playlist_weekly_top":
            await _run_auto_playlist(db, "Weekly Top Tracks", "lastfm_top", count=count or 50)

        elif task_name == "playlist_weekly_discover":
            await _run_auto_playlist(db, "Weekly Discover", "discover", count=count or 30)

        elif task_name == "playlist_favorites":
            await _run_favorites_playlist(db)

        elif task_name == "playlist_unfavorites":
            await _run_unfavorites_playlist(db)

        elif task_name == "vibe_embeddings":
            from backend.services.embeddings import generate_embedding_async
            from backend.models.embedding import TrackEmbedding
            batch_limit = count or 200
            embedded_ids = select(TrackEmbedding.track_id)
            # Recently-played first. Coverage stalled at roughly half the library, and the
            # missing half skews towards what is actually being listened to — so filling the
            # backlog in play order makes vibe search and the Sound Atlas useful long before
            # the whole library is done.
            tracks = (await db.execute(
                select(Track.id, Track.file_path)
                .where(Track.id.notin_(embedded_ids))
                .order_by(Track.last_played_at.desc().nullslast(), Track.created_at.desc())
                .limit(batch_limit)
            )).all()
            embedded_count = 0
            failed_count = 0
            consecutive_fails = 0
            failed_files = []
            for i, (track_id, file_path) in enumerate(tracks):
                try:
                    emb_bytes = await generate_embedding_async(file_path)
                    if emb_bytes:
                        await db.merge(TrackEmbedding(track_id=track_id, embedding=emb_bytes))
                        embedded_count += 1
                        consecutive_fails = 0
                    else:
                        failed_count += 1
                        consecutive_fails += 1
                except Exception as e:
                    failed_count += 1
                    consecutive_fails += 1
                    short = (file_path or "").rsplit("/", 1)[-1]
                    failed_files.append(f"{short}: {e}")
                    log.warning(f"[scheduler] Embedding failed for {file_path}: {e}")
                # Commit in batches so a timeout cannot throw away the whole run — which is
                # exactly how the manual path lost five months of progress when a deploy
                # restarted the web process mid-flight.
                if (i + 1) % 10 == 0:
                    await db.commit()
                # The CLAP model failing to load looks like every track failing in a row.
                if consecutive_fails >= 20:
                    log.error("[scheduler] Vibe embeddings aborting: %d consecutive failures", consecutive_fails)
                    break
            await db.commit()
            remaining = (await db.execute(
                select(func.count(Track.id)).where(Track.id.notin_(select(TrackEmbedding.track_id)))
            )).scalar() or 0
            job.result = json.dumps({
                "embedded": embedded_count,
                "failed": failed_count,
                "batch": len(tracks),
                "remaining": remaining,
                "errors": failed_files[:5],
            })

        elif task_name == "audio_analysis":
            from backend.services.analyzer import analyze_track_async
            from backend.models.analysis import TrackAnalysis
            batch_limit = count or 200
            analyzed_ids = (await db.execute(select(TrackAnalysis.track_id))).scalars().all()
            tracks = (await db.execute(
                select(Track.id, Track.file_path).where(Track.id.notin_(analyzed_ids)).limit(batch_limit)
            )).all()
            analyzed_count = 0
            skipped_count = 0
            consecutive_fails = 0
            failed_files = []
            for i, (track_id, file_path) in enumerate(tracks):
                try:
                    analysis = await analyze_track_async(file_path)
                    if analysis:
                        await db.merge(TrackAnalysis(track_id=track_id, **analysis))
                        analyzed_count += 1
                        consecutive_fails = 0
                    else:
                        # Insert stub row so this track is excluded from future batches
                        await db.merge(TrackAnalysis(track_id=track_id))
                        skipped_count += 1
                        consecutive_fails += 1
                except Exception as e:
                    await db.merge(TrackAnalysis(track_id=track_id))
                    skipped_count += 1
                    consecutive_fails += 1
                    short = (file_path or "").rsplit("/", 1)[-1]
                    failed_files.append(f"{short}: {e}")
                    log.warning(f"[scheduler] Analysis failed for {file_path}: {e}")
                # Commit every 10 tracks to avoid losing progress on timeout
                if (i + 1) % 10 == 0:
                    await db.commit()
                # Abort if pool is persistently broken
                if consecutive_fails >= 20:
                    log.error("[scheduler] Audio analysis aborting: %d consecutive failures", consecutive_fails)
                    break
            await db.commit()
            job.result = json.dumps({
                "analyzed": analyzed_count,
                "skipped": skipped_count,
                "batch": len(tracks),
                "errors": failed_files[:5],
            })

        elif task_name == "recommendation_refresh":
            from backend.services.recommender import refresh_recommendations
            async def on_progress(current, total, description=""):
                # Use separate session to avoid concurrent ops on the main db session
                async with async_session() as progress_db:
                    from sqlalchemy import update as _update
                    await progress_db.execute(
                        _update(Job).where(Job.id == job_id).values(
                            progress=current, total=total,
                        )
                    )
                    await progress_db.commit()
                await broadcast_job_update({
                    "id": job_id, "type": "recommendation_refresh",
                    "status": "running", "progress": current, "total": total,
                    "description": description or "Music Discovery AI",
                })
            result = await refresh_recommendations(db, on_progress=on_progress)
            job.result = json.dumps(result)

        elif task_name == "upgrade_scan":
            await _run_upgrade_scan(db, job, count=count or 50, config=task_config)

        elif task_name == "remix_discovery":
            await _run_remix_discovery(db, job, count=count or 30, config=task_config)

        elif task_name == "download_cleanup":
            from backend.services.scanner import cleanup_download_dir
            max_age = task_config.get("max_age_hours", 24) if task_config else 24
            result = cleanup_download_dir(max_age_hours=max_age)
            job.result = json.dumps(result)

        elif task_name == "job_cleanup":
            result = await _run_job_cleanup(db, job, config=task_config)
            job.result = json.dumps(result)

        job.status = "completed"
    except Exception as e:
        log.error(f"Scheduled task {task_name} failed: {e}")
        job.status = "failed"
        job.result = json.dumps({"error": str(e)})
    finally:
        job.finished_at = datetime.utcnow()

        # Capture values from ORM object BEFORE closing session —
        # after rollback/close, the detached object can't refresh attributes.
        #
        # `tracks` in particular is load-bearing and was missing here: task handlers assign it
        # after their last commit, the rollback below then discards it, and the auto-download
        # stage at the end of this function re-reads it from the database and finds NULL. That
        # silently disabled auto-download for every task that hands work over this way —
        # lastfm_top_tracks, discover_similar, upgrade_scan and remix_discovery — while each
        # one went on reporting "completed" with a healthy-looking tracks_found in its result.
        # `total` and `progress` are captured for the same reason: they were being dropped, so
        # every scheduled job displayed 0/0 in the UI regardless of what it actually did.
        final_status = job.status
        final_result = job.result
        final_finished = job.finished_at
        final_tracks = job.tracks
        final_total = job.total
        final_progress = job.progress

        # Close the main session FIRST to release the SQLite write lock,
        # then use a fresh session for final updates
        try:
            await db.rollback()
        except Exception:
            pass
        try:
            await db.close()
        except Exception:
            pass
        try:
            from sqlalchemy import update as _update
            async with async_session() as final_db:
                await final_db.execute(
                    _update(ScheduleTask).where(ScheduleTask.task_name == task_name).values(
                        last_run_at=datetime.utcnow(),
                    )
                )
                await final_db.execute(
                    _update(Job).where(Job.id == job_id).values(
                        status=final_status, result=final_result,
                        finished_at=final_finished, tracks=final_tracks,
                        total=final_total, progress=final_progress,
                    )
                )
                await final_db.commit()
        except Exception as fin_err:
            log.error(f"Failed to save final job status for {task_name}: {fin_err}")
        await broadcast_job_update({"id": job_id, "type": task_name, "status": final_status, "progress": 1, "total": 1, "description": desc})

        # Auto-download missing tracks if configured
        if (
            final_status == "completed"
            and task_config.get("auto_download")
            and task_name in ("lastfm_top_tracks", "discover_similar", "upgrade_scan", "remix_discovery")
        ):
            try:
                tracks_json = json.loads(final_result or "{}").get("tracks") if final_result else None
                # tracks were stored on job.tracks — read from a fresh session
                async with async_session() as dl_db:
                    row = (await dl_db.execute(
                        select(Job.tracks).where(Job.id == job_id)
                    )).scalar_one_or_none()
                if row:
                    missing = json.loads(row)
                    if missing:
                        await _auto_download_missing(missing, task_name, batch_id=job_id)
            except Exception as e:
                log.error(f"Auto-download after {task_name} failed: {e}")

        # Auto-download top recommendations if configured
        if (
            final_status == "completed"
            and task_config.get("auto_download")
            and task_name == "recommendation_refresh"
        ):
            try:
                min_score = task_config.get("min_score", 0.5)
                max_downloads = task_config.get("max_downloads", 10)
                async with async_session() as dl_db:
                    await _auto_download_recommendations(dl_db, min_score, max_downloads, batch_id=job_id)
            except Exception as e:
                log.error(f"Auto-download recommendations failed: {e}")


async def _auto_download_recommendations(db: AsyncSession, min_score: float, max_downloads: int,
                                         batch_id: str | None = None):
    """Auto-download top pending recommendations above score threshold. batch_id:
    the scheduled job's id, stamped into each download as its batch (DC-21)."""
    from sqlalchemy import select
    from backend.models.recommendation import Recommendation

    result = await db.execute(
        select(Recommendation)
        .where(Recommendation.status == "pending", Recommendation.score >= min_score)
        .order_by(Recommendation.score.desc())
    )
    # Tracks whose search failed recently stay pending and must not eat download slots.
    backoff_keys = await keys_in_backoff(db)
    recs = [
        r for r in result.scalars().all()
        if attempt_key(r.artist, r.track) not in backoff_keys
    ][:max_downloads]
    if not recs:
        log.info(f"No recommendations above {min_score} to auto-download")
        return

    missing = [{"artist": r.artist, "track": r.track, "rec_id": r.id} for r in recs]
    log.info(f"Auto-downloading {len(missing)} recommendations (score >= {min_score})")

    outcomes = await _auto_download_missing(missing, "recommendation_refresh", batch_id=batch_id)
    by_key = {attempt_key(o["artist"], o["track"]): o for o in outcomes}

    # Only recs whose download actually succeeded are "downloaded"; failures become "failed"
    # (error kept on source_detail) so they stop looking like library additions. Recs with no
    # outcome (backend down, skipped) stay pending and are retried by the next run.
    n_ok = n_failed = 0
    for r in recs:
        o = by_key.get(attempt_key(r.artist, r.track))
        if o is None:
            continue
        if o["ok"] is None:
            continue  # unknown (still running / infrastructure failure): stay pending
        if o["ok"]:
            r.status = "downloaded"
            n_ok += 1
        else:
            r.status = "failed"
            r.source_detail = ((r.source_detail or "") + f" | download failed: {o['error'] or 'unknown'}")[:2000]
            n_failed += 1
    await db.commit()
    log.info(f"Auto-download recommendations: {n_ok} downloaded, {n_failed} failed, "
             f"{len(recs) - n_ok - n_failed} left pending")


async def _download_backend_ready() -> bool:
    """True if the native Soulseek client (in the web process) is logged in. Checks
    the in-process client first (when called from the web), else asks the web's
    /api/download/status endpoint (when called from the worker)."""
    try:
        from backend.soulseek import get_client
        c = get_client()
        if c is not None:
            return bool(c.logged_in)
    except Exception:
        pass
    try:
        import httpx
        from backend.config import get_settings
        try:
            port = get_settings().server.port
        except Exception:
            port = 3000
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(f"http://127.0.0.1:{port}/api/download/status")
            return bool(r.json().get("logged_in"))
    except Exception:
        return False


# Moved to backend.services.auto_download; the names stay importable from here.
_is_infra_error = is_infra_error


async def _download_job_outcome(job_id: str | None) -> tuple[bool | None, str | None]:
    """download_job_outcome read through this module's session factory."""
    return await download_job_outcome(job_id, session_factory=async_session)


# A batch of automatic downloads must finish inside the arq worker's job timeout
# (job_timeout = 3600 s in backend/workers/__init__.py) together with the task that
# found the tracks. Downloads still running at the deadline keep running in the web
# process; the batch just stops waiting and reports them as unknown (ok=None).
AUTO_DOWNLOAD_BATCH_MINUTES = 45
# Downloads submitted to the web and not yet finished. More are submitted as these
# finish, so the web's pending queue stays short and the order stays sensible.
AUTO_DOWNLOAD_MAX_OUTSTANDING = 25
# Seconds between two looks at the outstanding job rows.
AUTO_DOWNLOAD_POLL_SECONDS = 10

# One arq job (run_scheduled_tasks) runs every due task in turn, all inside the same
# 60-minute job_timeout. It sets this deadline when it starts (start + 50 min);
# every auto-download batch in that tick stops by it, and a batch that would start
# after it doesn't start at all. None outside a scheduler tick (e.g. "run now").
TICK_MINUTES = 50
_tick_deadline: ContextVar[float | None] = ContextVar("zonik_tick_deadline", default=None)


def start_tick() -> None:
    """Mark the start of a scheduler tick (called by run_scheduled_tasks)."""
    _tick_deadline.set(time.monotonic() + TICK_MINUTES * 60)


def tick_deadline() -> float | None:
    return _tick_deadline.get()


async def _auto_download_missing(missing: list[dict], source: str, batch_id: str | None = None) -> list[dict]:
    """Download each missing track through the tracked path (backoff, duration gate,
    outcome recording — backend.services.auto_download) without blocking on any one.

    Every track is submitted with wait=False (the web creates the job and runs it in
    the background), at most AUTO_DOWNLOAD_MAX_OUTSTANDING at a time; the job rows are
    then polled every AUTO_DOWNLOAD_POLL_SECONDS and each outcome is recorded as its
    job settles, until all are done or AUTO_DOWNLOAD_BATCH_MINUTES have passed.

    For source="upgrade_scan", entries may carry `upgrade_id` and `track_id`. We
    attach the download job_id to the TrackUpgrade row, bump `attempts`, and settle
    the row afterwards (finalize_upgrade) so it doesn't sit at `downloading` forever.
    Successful upgrades are marked `completed` by the scanner during import.

    Returns one outcome per attempted track: [{artist, track, job_id, ok, error, skipped}].
    Tracks skipped for backoff, tracks not submitted before the deadline, or the whole
    batch when the Soulseek backend is down, produce no outcome (callers must leave
    those untouched). `ok` is True (done), False (the search failed) or None (unknown:
    still running at the deadline, or an infrastructure failure) — None is never
    recorded in download_attempts. Upgrade entries return no outcomes.

    batch_id (the scheduled task's own job id) is stamped into every download as
    tracks[0].batch = {id, label: the task's label, kind: "scheduled"} (DC-21).
    """
    import asyncio
    import uuid as _uuid
    from backend.services.auto_download import (
        submit_tracked, finish_tracked, finalize_upgrade, unsettled_jobs, submission_outcome,
    )

    total = len(missing)
    # The batch's own deadline starts now (submissions count against it), capped by
    # the scheduler tick's: several tasks share one 60-minute arq job.
    deadline = time.monotonic() + AUTO_DOWNLOAD_BATCH_MINUTES * 60
    tick = tick_deadline()
    if tick is not None:
        if time.monotonic() >= tick:
            log.warning(f"[auto-download] {source}: scheduler tick deadline passed — leaving "
                        f"{total} tracks for the next run")
            return []
        deadline = min(deadline, tick)
    log.info(f"Auto-downloading {total} missing tracks from {source}")

    # Circuit-breaker: if the Soulseek download backend is down, skip the whole
    # batch instead of spawning N instantly-failing jobs (which used to pile up
    # hundreds of identical 'connection failed' rows). Leave the queue for next run.
    if not await _download_backend_ready():
        log.warning(f"[auto-download] Soulseek backend not ready — skipping {total} downloads from {source}")
        return []

    # Map scheduler source to download source label
    dl_source = {"lastfm_top_tracks": "discovery", "discover_similar": "similar", "remix_discovery": "remix", "recommendation_refresh": "recommendation", "upgrade_scan": "upgrade"}.get(source, "discovery")

    if source != "upgrade_scan":
        # Two entries that normalise to the same attempt key would race on the
        # download_attempts INSERT; one download serves both.
        seen_keys: set[str] = set()
        unique = []
        for t in missing:
            k = attempt_key(t.get("artist", ""), t.get("track", ""))
            if k in seen_keys:
                continue
            seen_keys.add(k)
            unique.append(t)
        missing = unique

    queue = [t for t in missing if t.get("artist") and t.get("track")]
    outcomes: list[dict] = []
    outstanding: list[dict] = []  # submitted, job not settled: {artist, track, job_id, upgrade_id, error}
    skipped_backoff = 0
    sem = asyncio.Semaphore(4)  # concurrent submissions (backoff check, Last.fm, web call)
    # (not "batch": the submit loop below uses that name for its slice of the queue)
    run_batch = ({"id": batch_id, "label": _TASK_LABELS.get(source, source), "kind": "scheduled"}
                 if batch_id else None)

    async def submit(t: dict) -> dict | None:
        """Submit one track. Returns its in-flight record, or None when not started."""
        nonlocal skipped_backoff
        artist, track = t["artist"], t["track"]
        upgrade_id = t.get("upgrade_id") if source == "upgrade_scan" else None
        job_id = str(_uuid.uuid4())
        target_track_id = None
        async with sem:
            # Enforce max_attempts so a permanently-unavailable track isn't retried
            # forever on every scan. Also capture the target track_id so the importer
            # replaces the exact original instead of fuzzy-matching the download's tags.
            if upgrade_id:
                go, target_track_id = await _prepare_upgrade(upgrade_id, job_id)
                if not go:
                    return None
            sub_kw = {"batch": run_batch} if run_batch else {}
            sub = await submit_tracked(artist, track, source=dl_source, target_track_id=target_track_id,
                                       job_id=job_id, wait=False, **sub_kw)
        if sub["skipped"]:
            skipped_backoff += 1
            if upgrade_id:
                # _prepare_upgrade already moved the row to "downloading"; a skip (the
                # track is blacklisted) starts no job, so put it back to pending with
                # the attempt refunded instead of leaving it stuck until the reaper.
                await finalize_upgrade(upgrade_id, None, None)
            return None
        return {"artist": artist, "track": track, "job_id": sub["job_id"],
                "upgrade_id": upgrade_id, "error": sub["error"], "deduped": sub["deduped"]}

    async def finish(item: dict) -> None:
        if item["upgrade_id"]:
            ok, err = await submission_outcome(item["job_id"], item["error"])
            await finalize_upgrade(item["upgrade_id"], ok, err)
            return
        outcomes.append(await finish_tracked(item["job_id"], item["artist"], item["track"], dl_source,
                                             enqueue_error=item["error"], deduped=item["deduped"]))

    while True:
        # Top up the in-flight set while there is time left.
        room = AUTO_DOWNLOAD_MAX_OUTSTANDING - len(outstanding)
        if room > 0 and queue and time.monotonic() < deadline:
            batch, queue = queue[:room], queue[room:]
            submitted = await asyncio.gather(*(submit(t) for t in batch), return_exceptions=True)
            for t, r in zip(batch, submitted):
                if isinstance(r, BaseException):
                    log.warning(f"[auto-download] Could not submit {t['artist']} — {t['track']}: {r}")
                elif r is not None:
                    outstanding.append(r)

        # Settled ones: a skipped/failed submission (no job, or an enqueue error) and
        # any job whose row is no longer pending/running.
        try:
            running = await unsettled_jobs([i["job_id"] for i in outstanding if i["job_id"] and not i["error"]])
        except Exception as e:
            log.debug(f"[auto-download] could not poll job rows: {e}")
            running = {i["job_id"] for i in outstanding}
        still: list[dict] = []
        for item in outstanding:
            if item["job_id"] in running and not item["error"]:
                still.append(item)
            else:
                await finish(item)
        outstanding = still

        if not outstanding and (not queue or time.monotonic() >= deadline):
            break
        if time.monotonic() >= deadline:
            break
        await asyncio.sleep(AUTO_DOWNLOAD_POLL_SECONDS)

    if outstanding:
        log.warning(
            f"[auto-download] {source}: batch deadline reached with "
            f"{len(outstanding)} download(s) still running — outcome unknown, left to finish in the web: "
            + ", ".join(f"{i['artist']} — {i['track']}" for i in outstanding[:10])
        )
        for item in outstanding:
            # Still pending/running: finish() reads ok=None, which records nothing and
            # puts an upgrade row back to pending with its attempt refunded.
            await finish(item)
    if queue:
        log.warning(f"[auto-download] {source}: {len(queue)} track(s) not submitted before the batch deadline")

    log.info(f"[auto-download] {source}: {total} candidates, skipped_backoff={skipped_backoff}, "
             f"outcomes={len(outcomes)}")
    return outcomes


async def _prepare_upgrade(upgrade_id: str, job_id: str) -> tuple[bool, str | None]:
    """Upgrade bookkeeping before its download. Returns (go, target_track_id): a row
    past max_attempts is retired and not downloaded (go False); otherwise the row is
    linked to the job and the attempt counted."""
    from sqlalchemy import update as _update
    from backend.models.upgrade import TrackUpgrade
    target_track_id = None
    try:
        async with async_session() as att_db:
            row = (await att_db.execute(
                select(TrackUpgrade).where(TrackUpgrade.id == upgrade_id)
            )).scalar_one_or_none()
            if row:
                target_track_id = row.track_id
            if row and row.status == "pending" and row.attempts >= (row.max_attempts or 3):
                await att_db.execute(
                    _update(TrackUpgrade)
                    .where(TrackUpgrade.id == upgrade_id)
                    .values(status="failed", error_message="Max attempts exhausted",
                            updated_at=datetime.utcnow())
                )
                await att_db.commit()
                log.info(f"[auto-download] Upgrade {upgrade_id} exhausted max_attempts — skipping")
                return False, None
    except Exception as e:
        log.debug(f"[auto-download] max_attempts check failed for {upgrade_id}: {e}")

    # Pre-link upgrade row to this job + bump attempts so the pipeline is observable.
    try:
        async with async_session() as link_db:
            await link_db.execute(
                _update(TrackUpgrade)
                .where(TrackUpgrade.id == upgrade_id, TrackUpgrade.status == "pending")
                .values(
                    status="downloading",
                    job_id=job_id,
                    attempts=TrackUpgrade.attempts + 1,
                    updated_at=datetime.utcnow(),
                )
            )
            await link_db.commit()
    except Exception as e:
        log.debug(f"[auto-download] Could not pre-link upgrade {upgrade_id}: {e}")
    return True, target_track_id


async def _run_lastfm_top_tracks(db: AsyncSession, job: Job, count: int = 50):
    """Pull Last.fm top chart, find missing tracks, store list for download."""
    from backend.services.lastfm import get_top_tracks
    chart = await get_top_tracks(limit=count)
    # Shared library matcher (same rule as the trigger API and recommender sourcing).
    await batch_library_match(db, chart, name_key="name", artist_key="artist")
    in_library = sum(1 for t in chart if t.get("in_library"))
    missing = [
        {"artist": t["artist"], "track": t["name"], "status": "missing"}
        for t in chart if not t.get("in_library")
    ]

    # Gate the global chart through the taste profile: it was the worst-engaging source
    # (8/51 played, 0 favorited). Reads the stored profile (building one is expensive);
    # no stored profile means no gate.
    skipped_low_score = 0
    profile = await _load_stored_taste_profile(db)
    if profile and missing:
        from backend.services.recommender import score_candidate, _fetch_candidate_tags
        min_score = await _chart_min_score(db)
        listeners = {(t["artist"], t["name"]): t.get("listeners", 0) for t in chart}
        cands = [{
            "artist": m["artist"], "track": m["track"], "source": "trending",
            "source_detail": "Last.fm trending",
            "lastfm_listeners": listeners.get((m["artist"], m["track"]), 0),
            "lastfm_match": 0.0,
        } for m in missing]
        # Chart entries carry no tags, so without this genre_match is 0 for all of them and
        # nothing can clear the bar. Rate-limited inside the lastfm client.
        await _fetch_candidate_tags(cands)
        kept = []
        for m, c in zip(missing, cands):
            score, _ = score_candidate(c, profile)
            if score >= min_score:
                m["score"] = score
                kept.append(m)
            else:
                skipped_low_score += 1
        missing = kept

    job.total = len(chart)
    job.progress = in_library
    job.tracks = json.dumps(missing)
    job.result = json.dumps({
        "total_chart": len(chart),
        "in_library": in_library,
        "missing": len(missing),
        "skipped_low_score": skipped_low_score,
        "kept": len(missing),
    })


async def _load_stored_taste_profile(db: AsyncSession) -> dict | None:
    from backend.models.taste_profile import TasteProfile
    try:
        tp = await db.get(TasteProfile, "default")
        return json.loads(tp.profile_data) if tp and tp.profile_data else None
    except (ValueError, TypeError):
        return None


async def _chart_min_score(db: AsyncSession) -> float:
    """Chart-specific bar: `chart_min_score` in the lastfm_top_tracks task config, else
    AssistantConfig.chart_min_score. (Not the recommendation threshold: chart entries have
    no Last.fm similarity, so their ceiling is much lower.)"""
    from backend.config import get_settings
    default = get_settings().assistant.chart_min_score
    row = (await db.execute(
        select(ScheduleTask.config).where(ScheduleTask.task_name == "lastfm_top_tracks")
    )).scalar_one_or_none()
    try:
        return float((json.loads(row) if row else {}).get("chart_min_score", default))
    except (ValueError, TypeError, AttributeError):
        return default


async def _run_discover_similar(db: AsyncSession, job: Job, count: int = 10):
    """Find similar tracks from favorites, flag missing ones."""
    from backend.services.lastfm import get_similar_tracks
    from backend.services.soulseek import normalize_text
    favorites = (await db.execute(
        select(Favorite).options(
            selectinload(Favorite.track).selectinload(Track.artist)
        ).where(Favorite.track_id.isnot(None)).order_by(func.random()).limit(count)
    )).scalars().all()

    missing = []
    found: list[dict] = []
    in_library = 0
    seen: set[str] = set()

    for fav in favorites:
        if not fav.track or not fav.track.artist:
            continue
        similar = await get_similar_tracks(fav.track.artist.name, fav.track.title, limit=5)
        for t in similar:
            key = normalize_text(f"{t['artist']} {t['name']}")
            if key in seen:
                continue
            seen.add(key)

            found.append({
                "artist": t["artist"], "name": t["name"],
                "source": f"{fav.track.artist.name} — {fav.track.title}",
            })

    await batch_library_match(db, found, name_key="name", artist_key="artist")
    for t in found:
        if t["in_library"]:
            in_library += 1
        else:
            missing.append({
                "artist": t["artist"], "track": t["name"], "status": "missing",
                "source": t["source"],
            })

    job.total = len(seen)
    job.progress = in_library
    job.tracks = json.dumps(missing)
    job.result = json.dumps({
        "favorites_checked": len(favorites),
        "similar_found": len(seen),
        "in_library": in_library,
        "missing": len(missing),
    })


async def _run_auto_playlist(db: AsyncSession, name: str, source: str, count: int = 50):
    """Create/replace an auto-generated playlist."""
    # Delete existing playlist with same name
    from sqlalchemy import delete
    existing = (await db.execute(select(Playlist).where(Playlist.name == name))).scalar_one_or_none()
    if existing:
        await db.execute(delete(PlaylistTrack).where(PlaylistTrack.playlist_id == existing.id))
        await db.execute(delete(Playlist).where(Playlist.id == existing.id))

    # Get track IDs based on source
    track_ids = []
    if source == "lastfm_top":
        from backend.services.lastfm import get_top_tracks
        chart = await get_top_tracks(limit=count)
        for t in chart:
            result = await db.execute(
                select(Track.id).where(Track.title.ilike(f"%{t['name']}%")).limit(1)
            )
            tid = result.scalar_one_or_none()
            if tid:
                track_ids.append(tid)
    elif source == "discover":
        # Use random selection of library tracks for now
        from sqlalchemy import func
        result = await db.execute(select(Track.id).order_by(func.random()).limit(count))
        track_ids = result.scalars().all()

    if not track_ids:
        return

    playlist = Playlist(id=str(uuid.uuid4()), name=name, is_public=True)
    db.add(playlist)
    await db.flush()
    for i, tid in enumerate(track_ids):
        db.add(PlaylistTrack(id=str(uuid.uuid4()), playlist_id=playlist.id, track_id=tid, position=i))
    await db.commit()


async def _run_favorites_playlist(db: AsyncSession):
    """Create/replace Favorites playlist from all starred tracks."""
    from sqlalchemy import delete
    existing = (await db.execute(select(Playlist).where(Playlist.name == "Favorites"))).scalar_one_or_none()
    if existing:
        await db.execute(delete(PlaylistTrack).where(PlaylistTrack.playlist_id == existing.id))
        await db.execute(delete(Playlist).where(Playlist.id == existing.id))
        await db.commit()

    # Join with Track to exclude stale favorite references to deleted tracks
    favorites = (await db.execute(
        select(Favorite.track_id)
        .join(Track, Track.id == Favorite.track_id)
        .where(Favorite.track_id.isnot(None))
    )).scalars().all()

    if not favorites:
        return

    playlist = Playlist(id=str(uuid.uuid4()), name="Favorites", is_public=True)
    db.add(playlist)
    await db.flush()
    for i, tid in enumerate(favorites):
        db.add(PlaylistTrack(id=str(uuid.uuid4()), playlist_id=playlist.id, track_id=tid, position=i))
    await db.commit()


async def _run_unfavorites_playlist(db: AsyncSession):
    """Create/replace Unfavorites playlist from all tracks NOT starred."""
    from sqlalchemy import delete

    existing = (await db.execute(select(Playlist).where(Playlist.name == "Unfavorites"))).scalar_one_or_none()
    if existing:
        await db.execute(delete(PlaylistTrack).where(PlaylistTrack.playlist_id == existing.id))
        await db.execute(delete(Playlist).where(Playlist.id == existing.id))
        await db.commit()

    fav_ids = (await db.execute(
        select(Favorite.track_id).where(Favorite.track_id.isnot(None))
    )).scalars().all()

    query = select(Track.id).order_by(Track.title)
    if fav_ids:
        query = query.where(Track.id.notin_(fav_ids))
    unfav_tracks = (await db.execute(query)).scalars().all()

    if not unfav_tracks:
        return

    playlist = Playlist(id=str(uuid.uuid4()), name="Unfavorites", is_public=True)
    db.add(playlist)
    await db.flush()
    for i, tid in enumerate(unfav_tracks):
        db.add(PlaylistTrack(id=str(uuid.uuid4()), playlist_id=playlist.id, track_id=tid, position=i))
    await db.commit()


async def _run_lastfm_loved_sync(db: AsyncSession, job: Job):
    """Sync Zonik favorites → Last.fm loved tracks."""
    from backend.config import get_settings
    from backend.services.scrobbler import sync_loved_tracks

    settings = get_settings()
    session_key = settings.lastfm.session_key
    if not session_key:
        job.total = 1
        job.progress = 1
        job.result = json.dumps({"error": "No Last.fm session key. Authenticate via Settings > Last.fm."})
        raise Exception("No Last.fm session key. Authenticate via Settings > Last.fm.")

    username = settings.lastfm.username

    async def on_progress(current, total):
        # Use separate session to avoid concurrent ops on the main db session
        if current % 10 == 0 or current == total:
            async with async_session() as progress_db:
                from sqlalchemy import update as _update
                await progress_db.execute(
                    _update(Job).where(Job.id == job.id).values(
                        progress=current, total=total,
                    )
                )
                await progress_db.commit()
        await broadcast_job_update({
            "id": job.id, "type": "lastfm_sync", "status": "running",
            "progress": current, "total": total,
            "description": "Last.fm Favorites Sync",
        })

    result = await sync_loved_tracks(session_key, username=username, on_progress=on_progress)
    job.total = result["total"]
    job.progress = result["synced"] + result["skipped"]
    job.result = json.dumps(result)


async def _run_upgrade_scan(db: AsyncSession, job: Job, count: int = 50, config: dict | None = None):
    """Find low-quality tracks and queue them for re-download from Soulseek."""
    from sqlalchemy import func as sqlfunc

    cfg = config or {}
    mode = cfg.get("mode", "low_bitrate")
    max_bitrate = cfg.get("max_bitrate", 256)

    query = select(Track).options(
        selectinload(Track.artist)
    )

    lossy_formats = ["mp3", "m4a", "ogg", "opus", "aac", "wma"]

    if mode == "opus_to_flac":
        query = query.where(Track.format == "opus")
    elif mode == "lossy_to_lossless":
        query = query.where(Track.format.in_(lossy_formats))
    elif mode == "all_lossy":
        query = query.where(Track.format.in_(lossy_formats))
    else:  # low_bitrate (default)
        query = query.where(
            (Track.bitrate.isnot(None)) & (Track.bitrate < max_bitrate * 1000)
        )

    # Per-track failure history across ALL TrackUpgrade rows. Each scan used to insert a
    # fresh row with attempts=0, so max_attempts never tripped for a track that kept failing.
    from backend.models.upgrade import TrackUpgrade
    max_attempts = int(cfg.get("max_attempts", 3))
    retired_ids, backoff_ids = await upgrade_skip_ids(db, max_attempts)

    # Over-fetch by the size of the skip set so skipped tracks don't starve the batch.
    query = query.order_by(Track.bitrate.asc().nullslast()).limit(count + len(retired_ids) + len(backoff_ids))
    result = await db.execute(query)
    candidates = result.scalars().all()
    skipped_retired = sum(1 for t in candidates if t.id in retired_ids)
    skipped_backoff = sum(1 for t in candidates if t.id in backoff_ids)
    tracks = [t for t in candidates if t.id not in retired_ids and t.id not in backoff_ids][:count]

    # Create TrackUpgrade records (idempotent — skip existing pending/queued/downloading)
    existing_upgrades = await db.execute(
        select(TrackUpgrade.track_id).where(
            TrackUpgrade.status.in_(["pending", "queued", "downloading"])
        )
    )
    skip_ids = {r[0] for r in existing_upgrades.all()}

    # Lookup any existing pending upgrade rows so we can pass their IDs through
    # to the auto-download path (used to update status/job_id/attempts on failure).
    existing_pending_rows = (await db.execute(
        select(TrackUpgrade.track_id, TrackUpgrade.id).where(
            TrackUpgrade.track_id.in_([t.id for t in tracks]),
            TrackUpgrade.status == "pending",
        )
    )).all()
    pending_by_track = {tid: uid for tid, uid in existing_pending_rows}

    upgrade_list = []
    for t in tracks:
        artist_name = t.artist.name if t.artist else "Unknown"
        if t.id in skip_ids and t.id in pending_by_track:
            upgrade_id = pending_by_track[t.id]
        elif t.id not in skip_ids:
            upgrade_id = str(uuid.uuid4())
            db.add(TrackUpgrade(
                id=upgrade_id,
                track_id=t.id,
                track_title=t.title,
                track_artist=t.artist.name if t.artist else None,
                original_format=t.format or "unknown",
                original_bitrate=t.bitrate,
                original_file_size=t.file_size,
                reason=mode,
                status="pending",
                created_at=datetime.utcnow(),
            ))
        else:
            # In skip_ids but no pending row (queued/downloading) — skip auto-download
            continue
        upgrade_list.append({
            "artist": artist_name,
            "track": t.title,
            "status": "missing",  # Expected by _auto_download_missing
            "format": t.format,
            "bitrate": t.bitrate,
            "upgrade_id": upgrade_id,
            "track_id": t.id,
        })

    # Commit the new TrackUpgrade rows now — the run_task wrapper rolls back
    # the main session at the end, so without this the rows would be discarded
    # and the auto-download phase would have nothing to link to. (This was a
    # silent pre-existing bug: the scheduler appeared to scan but produced no
    # `track_upgrades` rows from its scheduled runs — only manual /scan calls
    # via the API persisted any.)
    await db.commit()

    job.total = len(tracks)
    job.progress = 0
    job.tracks = json.dumps(upgrade_list)
    job.result = json.dumps({
        "mode": mode,
        "max_bitrate": max_bitrate if mode == "low_bitrate" else None,
        "tracks_found": len(tracks),
        "skipped_retired": skipped_retired,
        "skipped_backoff": skipped_backoff,
        "auto_download": cfg.get("auto_download", False),
    })

    await broadcast_job_update({
        "id": job.id, "type": "upgrade_scan", "status": "running",
        "progress": len(tracks), "total": len(tracks),
        "description": f"Found {len(tracks)} tracks to upgrade",
    })

    log.info(
        f"Upgrade scan ({mode}): found {len(tracks)} tracks "
        f"(skipped {skipped_retired} retired, {skipped_backoff} in backoff)"
    )


async def _run_remix_discovery(db: AsyncSession, job: Job, count: int = 30, config: dict | None = None):
    """Find remixes of popular library tracks via Last.fm search."""
    import asyncio
    from backend.services.remix_discovery import find_remixes as _find_remixes
    from backend.services.soulseek import normalize_text

    cfg = config or {}
    source = cfg.get("source", "popular")

    # Pick source tracks
    from sqlalchemy import func as sqlfunc
    if source == "favorites":
        result = await db.execute(
            select(Track).options(selectinload(Track.artist))
            .join(Favorite, Favorite.track_id == Track.id)
            .order_by(sqlfunc.random())
            .limit(count)
        )
    else:  # popular (default)
        result = await db.execute(
            select(Track).options(selectinload(Track.artist))
            .where(Track.play_count > 0)
            .order_by(Track.play_count.desc())
            .limit(count)
        )
    source_tracks = result.scalars().all()

    sem = asyncio.Semaphore(3)
    all_remixes = []
    remix_candidates: list[dict] = []
    seen: set[str] = set()

    async def scan_one(t):
        if not t.artist:
            return []
        async with sem:
            return await _find_remixes(t.artist.name, t.title, limit=5)

    tasks = [scan_one(t) for t in source_tracks]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for t, remix_list in zip(source_tracks, results):
        if isinstance(remix_list, Exception):
            continue
        for r in remix_list:
            key = normalize_text(f"{r['artist']} {r['name']}")
            if key in seen:
                continue
            seen.add(key)
            remix_candidates.append({
                "artist": r["artist"], "name": r["name"],
                "version_type": r.get("version_type", "remix"),
                "source_track": t.title,
                "source_artist": t.artist.name if t.artist else "",
            })

    # strict_title: "Song (X Remix)" must not match the library's "Song".
    await batch_library_match(db, remix_candidates, name_key="name", artist_key="artist", strict_title=True)
    for r in remix_candidates:
        if not r["in_library"]:
            all_remixes.append({
                "artist": r["artist"],
                "track": r["name"],
                "status": "missing",
                "version_type": r["version_type"],
                "source_track": r["source_track"],
                "source_artist": r["source_artist"],
            })

    job.total = len(source_tracks)
    job.progress = len(source_tracks)
    job.tracks = json.dumps(all_remixes[:100])
    job.result = json.dumps({
        "source": source,
        "tracks_scanned": len(source_tracks),
        "remixes_found": len(all_remixes),
    })

    log.info(f"Remix discovery ({source}): scanned {len(source_tracks)} tracks, found {len(all_remixes)} remixes")


async def _run_job_cleanup(db: AsyncSession, job: Job, config: dict | None = None) -> dict:
    """Prune old rows from the jobs table.

    Defaults: drop completed/failed/cancelled jobs older than 30 days, and any
    job (including stuck running/pending) older than 90 days. Both thresholds
    are overridable via task config (`terminal_age_days`, `hard_age_days`).
    """
    from datetime import timedelta
    from sqlalchemy import delete as _delete, or_, and_

    cfg = config or {}
    terminal_days = int(cfg.get("terminal_age_days", 30))
    hard_days = int(cfg.get("hard_age_days", 90))

    now = datetime.utcnow()
    terminal_cutoff = now - timedelta(days=terminal_days)
    hard_cutoff = now - timedelta(days=hard_days)

    # 1) Delete terminal-status jobs older than terminal_cutoff. Compare against
    #    finished_at when present, otherwise fall back to started_at.
    terminal_result = await db.execute(
        _delete(Job).where(
            Job.status.in_(("completed", "failed", "cancelled")),
            or_(
                and_(Job.finished_at.isnot(None), Job.finished_at < terminal_cutoff),
                and_(Job.finished_at.is_(None), Job.started_at < terminal_cutoff),
            ),
        )
    )
    terminal_deleted = terminal_result.rowcount or 0

    # 2) Hard cap — delete anything (including stuck running/pending) older than
    #    hard_cutoff so the table can't grow unbounded.
    hard_result = await db.execute(
        _delete(Job).where(
            or_(
                and_(Job.finished_at.isnot(None), Job.finished_at < hard_cutoff),
                and_(Job.finished_at.is_(None), Job.started_at < hard_cutoff),
            )
        )
    )
    hard_deleted = hard_result.rowcount or 0
    await db.commit()

    job.total = 1
    job.progress = 1
    log.info(
        f"[job_cleanup] Deleted {terminal_deleted} terminal jobs "
        f"older than {terminal_days}d and {hard_deleted} jobs older than {hard_days}d"
    )
    return {
        "terminal_deleted": terminal_deleted,
        "hard_deleted": hard_deleted,
        "terminal_age_days": terminal_days,
        "hard_age_days": hard_days,
    }
