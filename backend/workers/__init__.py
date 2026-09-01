"""ARQ worker settings and task registry."""
from __future__ import annotations

import logging
from datetime import datetime

from arq import cron
from arq.connections import RedisSettings

from backend.config import get_settings
from backend.database import async_session

log = logging.getLogger(__name__)


async def reap_stuck_jobs() -> None:
    """Mark jobs that have been running/pending far longer than any real job should
    (> 2h, vs the 1h arq job_timeout) as failed, and reset stuck upgrade rows. The
    web does this once on boot, but long-lived processes accumulate orphans — e.g.
    a task killed by arq's job_timeout never updates its Job row, so it sits
    'running' forever."""
    from sqlalchemy import update as _update
    from datetime import timedelta
    from backend.models.job import Job
    from backend.models.upgrade import TrackUpgrade
    cutoff = datetime.utcnow() - timedelta(hours=2)
    try:
        async with async_session() as db:
            r = await db.execute(
                _update(Job)
                .where(Job.status.in_(["running", "pending"]), Job.started_at < cutoff)
                .values(status="failed", finished_at=datetime.utcnow())
            )
            if r.rowcount:
                await db.commit()
                log.info(f"[reaper] Marked {r.rowcount} stuck jobs as failed")
        async with async_session() as db:
            r = await db.execute(
                _update(TrackUpgrade)
                .where(TrackUpgrade.status.in_(["queued", "downloading"]), TrackUpgrade.updated_at < cutoff)
                .values(status="pending", attempts=0, updated_at=datetime.utcnow())
            )
            if r.rowcount:
                await db.commit()
                log.info(f"[reaper] Reset {r.rowcount} stuck upgrades to pending")
    except Exception as e:
        log.warning(f"[reaper] Failed: {e}")


async def run_scheduled_tasks(ctx: dict):
    """Check schedule_tasks table and run any that are due."""
    from sqlalchemy import select
    from backend.models.schedule import ScheduleTask
    from backend.models.job import Job
    from backend.workers.scheduler import run_task

    # Sweep up orphaned jobs/upgrades before scheduling new work.
    await reap_stuck_jobs()

    # Use a short-lived session to read the schedule — do NOT hold it open during tasks
    async with async_session() as db:
        result = await db.execute(select(ScheduleTask).where(ScheduleTask.enabled.is_(True)))
        tasks = result.scalars().all()

        # Also fetch currently running jobs to skip tasks that are already in progress
        running_types = set(
            (await db.execute(
                select(Job.type).where(Job.status == "running")
            )).scalars().all()
        )

    now = datetime.utcnow()
    due_tasks = []
    for task in tasks:
        # Skip tasks that already have a running job
        if task.task_name in running_types:
            log.info(f"Skipping {task.task_name} — already running")
            continue

        # Check if enough time has passed since last run
        if task.last_run_at:
            hours_since = (now - task.last_run_at).total_seconds() / 3600
            if hours_since < task.interval_hours:
                continue

        # Check run_at time if set
        if task.run_at:
            try:
                run_hour, run_min = map(int, task.run_at.split(":"))
                if now.hour != run_hour or abs(now.minute - run_min) > 5:
                    continue
            except ValueError:
                pass

        due_tasks.append(task.task_name)

    # Run each task with its OWN session to avoid SQLite single-writer deadlocks
    for task_name in due_tasks:
        log.info(f"Running scheduled task: {task_name}")
        try:
            async with async_session() as task_db:
                await run_task(task_name, task_db)
        except Exception as e:
            log.error(f"Scheduled task {task_name} failed: {e}")


async def download_track(ctx: dict, artist: str, track: str):
    """Background download task. Routes through enqueue_download so the worker
    delegates to the web process (which owns the native Soulseek client) instead
    of running a client-less download itself."""
    from backend.api.download import enqueue_download
    return await enqueue_download(artist, track)


async def analyze_track(ctx: dict, track_id: str, file_path: str):
    """Background analysis task."""
    from backend.services.analyzer import analyze_track_async
    from backend.models.analysis import TrackAnalysis

    analysis = await analyze_track_async(file_path)
    if analysis:
        async with async_session() as db:
            await db.merge(TrackAnalysis(track_id=track_id, **analysis))
            await db.commit()
    return analysis


async def enrich_track(ctx: dict, track_id: str):
    """Background enrichment task."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from backend.models.track import Track
    from backend.services.enrichment import enrich_track as _enrich_track
    async with async_session() as db:
        result = await db.execute(
            select(Track).options(selectinload(Track.artist), selectinload(Track.album))
            .where(Track.id == track_id)
        )
        track = result.scalar_one_or_none()
        if not track:
            log.warning(f"enrich_track: track {track_id} not found")
            return None
        return await _enrich_track(db, track)


async def generate_embedding(ctx: dict, track_id: str, file_path: str):
    """
    Background CLAP embedding generation.

    Nothing enqueues this — a repo-wide search for enqueue_job finds no caller — and it could
    not have worked if anything did: it awaited a synchronous function and then called
    .tobytes() on the bytes that came back. Both bugs are fixed here rather than deleting it,
    because it stays registered in WorkerSettings and would otherwise be a trap for whoever
    wires it up. Routine backfill is the vibe_embeddings scheduled task, not this.
    """
    from backend.services.embeddings import generate_embedding_async
    from backend.models.embedding import TrackEmbedding

    embedding = await generate_embedding_async(file_path)
    if embedding is not None:
        async with async_session() as db:
            await db.merge(TrackEmbedding(
                track_id=track_id,
                embedding=embedding,
            ))
            await db.commit()
    return {"ok": embedding is not None}


async def startup(ctx: dict):
    log.info("Zonik worker started — downloads delegate to the web's native Soulseek client")


async def shutdown(ctx: dict):
    log.info("Zonik worker stopping")


def _make_redis_settings() -> RedisSettings:
    settings = get_settings()
    url = settings.redis.url
    parts = url.replace("redis://", "").split("/")
    host_port = parts[0].split(":")
    host = host_port[0] or "localhost"
    port = int(host_port[1]) if len(host_port) > 1 else 6379
    database = int(parts[1]) if len(parts) > 1 else 0
    return RedisSettings(host=host, port=port, database=database)


class WorkerSettings:
    functions = [download_track, analyze_track, enrich_track, generate_embedding]
    cron_jobs = [
        cron(run_scheduled_tasks, minute={0, 15, 30, 45}),  # Check every 15 minutes
    ]
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 10
    job_timeout = 3600  # 60 minutes — scheduled tasks (library_scan, audio_analysis) need time

    redis_settings = _make_redis_settings()
