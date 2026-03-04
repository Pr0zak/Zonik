"""ARQ worker settings and task registry."""
from __future__ import annotations

import logging
from datetime import datetime

from arq import cron
from arq.connections import RedisSettings

from backend.config import get_settings
from backend.database import async_session

log = logging.getLogger(__name__)


async def run_scheduled_tasks(ctx: dict):
    """Check schedule_tasks table and run any that are due."""
    from sqlalchemy import select
    from backend.models.schedule import ScheduleTask
    from backend.workers.scheduler import run_task

    async with async_session() as db:
        result = await db.execute(select(ScheduleTask).where(ScheduleTask.enabled.is_(True)))
        tasks = result.scalars().all()

        now = datetime.utcnow()
        for task in tasks:
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

            log.info(f"Running scheduled task: {task.task_name}")
            try:
                await run_task(task.task_name, db)
            except Exception as e:
                log.error(f"Scheduled task {task.task_name} failed: {e}")


async def download_track(ctx: dict, artist: str, track: str):
    """Background download task."""
    from backend.services.soulseek import search_and_download
    return await search_and_download(artist, track)


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
    from backend.services.enrichment import enrich_track
    async with async_session() as db:
        return await enrich_track(db, track_id)


async def generate_embedding(ctx: dict, track_id: str, file_path: str):
    """Background CLAP embedding generation."""
    from backend.services.embeddings import generate_embedding
    from backend.models.embedding import TrackEmbedding

    embedding = await generate_embedding(file_path)
    if embedding is not None:
        async with async_session() as db:
            await db.merge(TrackEmbedding(
                track_id=track_id,
                embedding=embedding.tobytes(),
            ))
            await db.commit()
    return {"ok": embedding is not None}


async def startup(ctx: dict):
    log.info("Zonik worker started")


async def shutdown(ctx: dict):
    log.info("Zonik worker stopping")


class WorkerSettings:
    functions = [download_track, analyze_track, enrich_track, generate_embedding]
    cron_jobs = [
        cron(run_scheduled_tasks, minute={0, 15, 30, 45}),  # Check every 15 minutes
    ]
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 10
    job_timeout = 600  # 10 minutes

    @staticmethod
    def redis_settings():
        settings = get_settings()
        # Parse redis URL
        url = settings.redis.url
        # redis://host:port/db
        parts = url.replace("redis://", "").split("/")
        host_port = parts[0].split(":")
        host = host_port[0] or "localhost"
        port = int(host_port[1]) if len(host_port) > 1 else 6379
        database = int(parts[1]) if len(parts) > 1 else 0
        return RedisSettings(host=host, port=port, database=database)
