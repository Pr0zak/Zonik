"""Schedule API routes - manage scheduled tasks."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db, async_session
from backend.models.schedule import ScheduleTask

router = APIRouter()

# Default task definitions
DEFAULT_TASKS = [
    {"task_name": "library_scan", "interval_hours": 24, "run_at": "03:00"},
    {"task_name": "enrichment", "interval_hours": 24, "run_at": "03:30"},
    {"task_name": "lastfm_top_tracks", "interval_hours": 24, "run_at": "04:00", "count": 50},
    {"task_name": "discover_similar", "interval_hours": 48, "run_at": "04:30", "count": 10},
    {"task_name": "discover_artists", "interval_hours": 48, "run_at": "05:00", "count": 10},
    {"task_name": "lastfm_sync", "interval_hours": 24, "run_at": "02:00"},
    {"task_name": "playlist_weekly_top", "interval_hours": 168, "run_at": "06:00", "day_of_week": 0, "count": 50},
    {"task_name": "playlist_weekly_discover", "interval_hours": 168, "run_at": "06:30", "day_of_week": 0, "count": 30},
    {"task_name": "playlist_favorites", "interval_hours": 24, "run_at": "01:00"},
    {"task_name": "playlist_unfavorites", "interval_hours": 24, "run_at": "01:30"},
    {"task_name": "audio_analysis", "interval_hours": 24, "run_at": "02:30"},
    {"task_name": "vibe_embeddings", "interval_hours": 24, "run_at": "02:45", "count": 300},

    {"task_name": "recommendation_refresh", "interval_hours": 24, "run_at": "05:30"},
    {"task_name": "upgrade_scan", "interval_hours": 168, "run_at": "06:00", "day_of_week": 0, "count": 50},
    {"task_name": "remix_discovery", "interval_hours": 168, "run_at": "04:00", "day_of_week": 5, "count": 30},
    {"task_name": "download_cleanup", "interval_hours": 24, "run_at": "01:00"},
    {"task_name": "job_cleanup", "interval_hours": 24, "run_at": "03:00"},
]

TASK_LABELS = {
    "library_scan": "Library Scan",
    "enrichment": "Metadata Enrichment",
    "lastfm_top_tracks": "Top Charts Sync",
    "discover_similar": "Similar Track Discovery",
    "discover_artists": "Similar Artist Discovery",
    "lastfm_sync": "Last.fm Love Sync",
    "playlist_weekly_top": "Weekly Top Playlist",
    "playlist_weekly_discover": "Weekly Discovery Mix",
    "playlist_favorites": "Favorites Playlist",
    "playlist_unfavorites": "Non-Favorites Playlist",
    "audio_analysis": "Audio Analysis",
    "vibe_embeddings": "Vibe Embeddings",

    "recommendation_refresh": "Music Discovery AI",
    "upgrade_scan": "Quality Upgrade Scan",
    "remix_discovery": "Remix Discovery",
    "download_cleanup": "Download Cleanup",
    "job_cleanup": "Job History Cleanup",
}

TASK_DESCRIPTIONS = {
    "library_scan": "Scan your music directory for new, changed, or removed files. Updates tags, artists, albums, and cover art in the database.",
    "enrichment": "Fill in missing metadata (genre, year, cover art) from MusicBrainz, Deezer, and Last.fm for tracks that lack it.",
    "lastfm_top_tracks": "Fetch the current Last.fm global top chart and check which tracks are already in your library.",
    "discover_similar": "Find tracks similar to your starred favorites using Last.fm's recommendation engine.",
    "discover_artists": "Discover new artists related to those in your library via Last.fm's similar artist network.",
    "lastfm_sync": "Sync your Zonik starred tracks to Last.fm as loved tracks. Incremental — only pushes new favorites.",
    "playlist_weekly_top": "Auto-generate a playlist from this week's most-played chart tracks found in your library.",
    "playlist_weekly_discover": "Auto-generate a discovery playlist with a random mix of tracks from your library.",
    "playlist_favorites": "Rebuild the Favorites playlist from all currently starred tracks.",
    "playlist_unfavorites": "Rebuild the Non-Favorites playlist from all tracks that are not starred.",
    "audio_analysis": "Run Essentia audio analysis (BPM, key, energy, danceability) on tracks that haven't been analyzed yet.",
    "vibe_embeddings": "Generate CLAP vibe embeddings for tracks that don't have one yet, most-recently-played first. These power vibe search and the Sound Atlas.",

    "recommendation_refresh": "Build a taste profile from your library (genres, artists, audio features, Last.fm history), then find and score new tracks via similar artists, genre matching, and trending charts. Optionally re-ranks with Claude AI.",
    "upgrade_scan": "Find low-quality tracks (low bitrate, lossy formats) and search Soulseek for higher-quality replacements.",
    "remix_discovery": "Search for remixes, edits, and alternate versions of popular tracks in your library.",
    "download_cleanup": "Remove old downloaded files from the downloads directory. Deletes zero-byte files, non-audio files, and audio files older than 24 hours (already imported into library).",
    "job_cleanup": "Prune the jobs table. Removes completed/failed/cancelled jobs older than 30 days and any job older than 90 days regardless of status, keeping the history small.",
}


# Scheduled tasks that feed the download pipeline, mapped to the `source`
# string their auto-downloads carry (DownloadAttempt.source / Downloads chips).
DOWNLOAD_TASK_SOURCES = {
    "lastfm_top_tracks": "discovery",
    "discover_similar": "similar",
    "remix_discovery": "remix",
    "recommendation_refresh": "recommendation",
    "upgrade_scan": "upgrade",
}


def _naive_utc(dt: datetime) -> datetime:
    """Naive UTC, like the DB columns and the worker's datetime.utcnow()."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _parse_run_at(run_at: str) -> tuple[int, int]:
    """Parse "HH:MM" exactly as the worker does (map(int, split(":"))).
    Raises ValueError where the worker would ignore run_at."""
    run_hour, run_min = map(int, run_at.split(":"))
    return run_hour, run_min


def next_run(task, now: datetime) -> datetime | None:
    """When the worker's scheduler tick will next pick this task up (naive UTC).

    Mirrors ``run_scheduled_tasks`` in ``backend/workers/__init__.py``:
    a task is due once ``interval_hours`` have passed since ``last_run_at``
    (or immediately when it never ran) and, if ``run_at`` "HH:MM" is set, only
    when the UTC wall clock is at that hour:minute (the worker allows ±5 min
    around it and ticks every 15 min). A ``run_at`` the worker cannot parse is
    ignored, as the worker ignores it.

    ``day_of_week`` is deliberately ignored: the worker ignores it too, so a
    weekly task runs on whatever day its interval elapses.

    Returns None when the task is disabled, or when its ``run_at`` hour can
    never match (the worker would never run it).
    """
    if not getattr(task, "enabled", False):
        return None
    now = _naive_utc(now)
    base = now
    last = getattr(task, "last_run_at", None)
    if last is not None:
        interval = getattr(task, "interval_hours", None) or 0
        base = max(now, _naive_utc(last) + timedelta(hours=interval))

    run_at = getattr(task, "run_at", None)
    if not run_at:
        return base
    try:
        hour, minute = _parse_run_at(run_at)
    except ValueError:
        return base  # worker skips the run_at check on a parse error
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None

    if (base.hour, base.minute) == (hour, minute):
        return base
    slot = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if slot < base:
        slot += timedelta(days=1)
    return slot


def next_download_runs(tasks, now: datetime) -> list[dict]:
    """Next run of every download-feeding task, soonest first.

    Items are ``{task_name, label, source, next_run_at}`` with ``next_run_at``
    a naive UTC ISO string; tasks that will not run (disabled) are left out.
    """
    runs = []
    for t in tasks:
        source = DOWNLOAD_TASK_SOURCES.get(t.task_name)
        if source is None:
            continue
        at = next_run(t, now)
        if at is None:
            continue
        runs.append({
            "task_name": t.task_name,
            "label": TASK_LABELS.get(t.task_name, t.task_name),
            "source": source,
            "next_run_at": at,
        })
    runs.sort(key=lambda r: r["next_run_at"])
    for r in runs:
        r["next_run_at"] = r["next_run_at"].isoformat()
    return runs



@router.get("")
async def list_schedule(db: AsyncSession = Depends(get_db)):
    """Get all scheduled tasks with their config."""
    result = await db.execute(select(ScheduleTask).order_by(ScheduleTask.task_name))
    tasks = result.scalars().all()

    # Initialize defaults if needed
    if not tasks:
        for defn in DEFAULT_TASKS:
            task = ScheduleTask(**defn)
            db.add(task)
        await db.commit()
        result = await db.execute(select(ScheduleTask).order_by(ScheduleTask.task_name))
        tasks = result.scalars().all()
    else:
        # Backfill any new default tasks missing from existing DB
        existing_names = {t.task_name for t in tasks}
        added = False
        for defn in DEFAULT_TASKS:
            if defn["task_name"] not in existing_names:
                task = ScheduleTask(**defn)
                db.add(task)
                added = True
        if added:
            await db.commit()
            result = await db.execute(select(ScheduleTask).order_by(ScheduleTask.task_name))
            tasks = result.scalars().all()

    now = datetime.now(timezone.utc)

    def _next_iso(t):
        at = next_run(t, now)
        return at.isoformat() if at else None

    return [
        {
            "task_name": t.task_name,
            "label": TASK_LABELS.get(t.task_name, t.task_name),
            "description": TASK_DESCRIPTIONS.get(t.task_name, ""),
            "enabled": t.enabled,
            "interval_hours": t.interval_hours,
            "run_at": t.run_at,
            "day_of_week": t.day_of_week,
            "count": t.count,
            "config": json.loads(t.config) if t.config else {},
            "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None,
            "next_run_at": _next_iso(t),
            "download_source": DOWNLOAD_TASK_SOURCES.get(t.task_name),
        }
        for t in tasks
    ]


class TaskUpdateRequest(BaseModel):
    enabled: bool | None = None
    interval_hours: int | None = None
    run_at: str | None = None
    day_of_week: int | None = None
    count: int | None = None
    config: dict | None = None


@router.put("/{task_name}")
async def update_task(task_name: str, req: TaskUpdateRequest, db: AsyncSession = Depends(get_db)):
    """Update a scheduled task's configuration."""
    result = await db.execute(select(ScheduleTask).where(ScheduleTask.task_name == task_name))
    task = result.scalar_one_or_none()
    if not task:
        return {"error": "Task not found"}

    if req.enabled is not None:
        task.enabled = req.enabled
    if req.interval_hours is not None:
        task.interval_hours = req.interval_hours
    if req.run_at is not None:
        task.run_at = req.run_at
    if req.day_of_week is not None:
        task.day_of_week = req.day_of_week
    if req.count is not None:
        task.count = req.count
    if req.config is not None:
        existing = json.loads(task.config) if task.config else {}
        existing.update(req.config)
        task.config = json.dumps(existing)

    await db.commit()
    return {"ok": True}


@router.post("/{task_name}/run")
async def run_task_now(task_name: str, background_tasks: BackgroundTasks):
    """Run a scheduled task immediately, returns job_id for polling."""
    import uuid
    from backend.workers.scheduler import run_task

    job_id = str(uuid.uuid4())

    async def do_run():
        async with async_session() as db:
            await run_task(task_name, db, job_id=job_id)

    background_tasks.add_task(do_run)
    return {"ok": True, "task": task_name, "job_id": job_id}
