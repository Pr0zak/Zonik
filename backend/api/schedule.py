"""Schedule API routes - manage scheduled tasks."""
from __future__ import annotations

import json
from datetime import datetime

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
    {"task_name": "library_cleanup", "interval_hours": 168, "run_at": "07:00", "day_of_week": 6},
    {"task_name": "recommendation_refresh", "interval_hours": 24, "run_at": "05:30"},
    {"task_name": "upgrade_scan", "interval_hours": 168, "run_at": "06:00", "day_of_week": 0, "count": 50},
    {"task_name": "remix_discovery", "interval_hours": 168, "run_at": "04:00", "day_of_week": 5, "count": 30},
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
    "library_cleanup": "Orphan Cleanup",
    "recommendation_refresh": "Music Discovery AI",
    "upgrade_scan": "Quality Upgrade Scan",
    "remix_discovery": "Remix Discovery",
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
    "library_cleanup": "Remove orphaned database entries for files that no longer exist on disk.",
    "recommendation_refresh": "Build a taste profile from your library (genres, artists, audio features, Last.fm history), then find and score new tracks via similar artists, genre matching, and trending charts. Optionally re-ranks with Claude AI.",
    "upgrade_scan": "Find low-quality tracks (low bitrate, lossy formats) and search Soulseek for higher-quality replacements.",
    "remix_discovery": "Search for remixes, edits, and alternate versions of popular tracks in your library.",
}


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
