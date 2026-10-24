"""Library dashboard & statistics endpoints."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.track import Track
from backend.models.artist import Artist
from backend.models.album import Album
from backend.models.job import Job
from backend.services.user_data import caller_id

router = APIRouter()

# --- Dashboard cache (5-minute TTL) ---
_dashboard_cache: dict | None = None
_dashboard_cache_time: float = 0
_DASHBOARD_CACHE_TTL = 300  # 5 minutes


@router.get("/stats/dashboard")
async def dashboard_stats(request: Request, db: AsyncSession = Depends(get_db)):
    """Aggregated dashboard data: growth, quality, recent activity, favorites, duplicates.
    The library part is cached for everyone; `favorites` is the caller's, every time."""
    import time as _time
    global _dashboard_cache, _dashboard_cache_time

    user_id = await caller_id(request, db)
    now_ts = _time.monotonic()
    if not (_dashboard_cache and (now_ts - _dashboard_cache_time) < _DASHBOARD_CACHE_TTL):
        _dashboard_cache = await _library_dashboard(db)
        _dashboard_cache_time = now_ts
    return {**_dashboard_cache, "favorites": await _caller_favorites(db, user_id)}


async def _caller_favorites(db: AsyncSession, user_id: str | None) -> dict:
    """The caller's favorite-track count and five most recent stars."""
    from backend.models.favorite import Favorite
    fav_count = (await db.execute(
        select(func.count(Favorite.id)).where(Favorite.user_id == user_id, Favorite.track_id.isnot(None))
    )).scalar() or 0
    recent_favs_result = await db.execute(
        select(Track.title, Artist.name)
        .join(Favorite, Favorite.track_id == Track.id)
        .outerjoin(Artist, Track.artist_id == Artist.id)
        .where(Favorite.user_id == user_id)
        .order_by(Favorite.starred_at.desc())
        .limit(5)
    )
    return {
        "count": fav_count,
        "recent": [{"title": t, "artist": a or "Unknown"} for t, a in recent_favs_result.all()],
    }


async def _library_dashboard(db: AsyncSession) -> dict:
    """The shared (library-wide) part of the dashboard."""

    from datetime import timedelta
    from backend.models.analysis import TrackAnalysis

    now = datetime.utcnow()

    # Library growth: tracks added per day over the last 30 days
    cutoff_30d = now - timedelta(days=30)
    growth_result = await db.execute(
        select(
            func.strftime("%Y-%m-%d", Track.created_at).label("day"),
            func.count(Track.id).label("count"),
        )
        .where(Track.created_at >= cutoff_30d)
        .group_by(func.strftime("%Y-%m-%d", Track.created_at))
        .order_by(func.strftime("%Y-%m-%d", Track.created_at))
    )
    growth = [{"date": d, "count": c} for d, c in growth_result.all()]

    # === Combined quality metrics (5 queries → 1) ===
    lossless_formats = ["flac", "wav", "alac", "aiff"]
    quality_result = await db.execute(
        select(
            func.count(Track.id),
            func.sum(case((Track.format.in_(lossless_formats), 1), else_=0)),
            func.avg(case((Track.bitrate.isnot(None), Track.bitrate), else_=None)),
            func.sum(case((Track.bitrate.isnot(None) & (Track.bitrate < 256000), 1), else_=0)),
        )
    )
    row = quality_result.one()
    total_tracks = row[0] or 0
    lossless_count = int(row[1] or 0)
    avg_bitrate = row[2] or 0
    low_quality_count = int(row[3] or 0)

    analyzed_count = (await db.execute(
        select(func.count(TrackAnalysis.track_id))
    )).scalar() or 0

    pct_lossless = round(lossless_count / max(total_tracks, 1) * 100, 1)
    pct_analyzed = round(analyzed_count / max(total_tracks, 1) * 100, 1)
    pct_low = low_quality_count / max(total_tracks, 1)
    bitrate_score = min(1.0, (avg_bitrate or 0) / 900000)
    quality_score = round(
        (pct_lossless / 100 * 0.5 + bitrate_score * 0.3 + (1 - pct_low) * 0.2) * 100, 1
    )

    # Storage breakdown by format (also gives total_tracks count per format)
    storage_result = await db.execute(
        select(Track.format, func.sum(Track.file_size).label("size"), func.count(Track.id).label("cnt"))
        .group_by(Track.format)
        .order_by(func.sum(Track.file_size).desc())
    )
    storage_by_format = [
        {"format": f or "unknown", "size": int(s or 0), "count": c}
        for f, s, c in storage_result.all()
    ]
    total_size = sum(s["size"] for s in storage_by_format)

    # Recent activity: last 15 completed jobs
    recent_jobs_result = await db.execute(
        select(Job.id, Job.type, Job.status, Job.started_at, Job.finished_at, Job.result)
        .where(Job.finished_at.isnot(None))
        .order_by(Job.finished_at.desc())
        .limit(15)
    )
    recent_activity = []
    for j_id, j_type, j_status, j_started, j_finished, j_result in recent_jobs_result.all():
        recent_activity.append({
            "id": j_id,
            "type": j_type,
            "status": j_status,
            "finished_at": j_finished.isoformat() if j_finished else None,
        })

    # Duplicates summary (lightweight count query instead of full enriched scan)
    try:
        dup_count_result = await db.execute(
            select(func.count())
            .select_from(
                select(func.lower(Track.title), Track.artist_id)
                .where(Track.artist_id.isnot(None))
                .group_by(func.lower(Track.title), Track.artist_id)
                .having(func.count(Track.id) > 1)
                .subquery()
            )
        )
        dup_groups = dup_count_result.scalar() or 0
        # Estimate reclaimable: avg file size × extra tracks
        if dup_groups > 0:
            dup_extra_result = await db.execute(
                select(func.sum(Track.file_size))
                .where(
                    Track.id.notin_(
                        select(func.min(Track.id))
                        .where(Track.artist_id.isnot(None))
                        .group_by(func.lower(Track.title), Track.artist_id)
                        .having(func.count(Track.id) > 1)
                    ),
                    Track.artist_id.isnot(None),
                    func.lower(Track.title).in_(
                        select(func.lower(Track.title))
                        .where(Track.artist_id.isnot(None))
                        .group_by(func.lower(Track.title), Track.artist_id)
                        .having(func.count(Track.id) > 1)
                    ),
                )
            )
            dup_reclaimable = dup_extra_result.scalar() or 0
        else:
            dup_reclaimable = 0
    except Exception:
        dup_groups = 0
        dup_reclaimable = 0

    # Scheduled tasks: next upcoming
    from backend.models.schedule import ScheduleTask
    sched_result = await db.execute(
        select(ScheduleTask).where(ScheduleTask.enabled == True)
    )
    upcoming = []
    for task in sched_result.scalars().all():
        next_run = None
        if task.last_run_at:
            next_run = (task.last_run_at + timedelta(hours=task.interval_hours)).isoformat()
        upcoming.append({
            "task_name": task.task_name,
            "run_at": task.run_at,
            "interval_hours": task.interval_hours,
            "last_run_at": task.last_run_at.isoformat() if task.last_run_at else None,
            "next_run": next_run,
        })

    result = {
        "growth": growth,
        "quality": {
            "score": quality_score,
            "pct_lossless": pct_lossless,
            "pct_analyzed": pct_analyzed,
            "avg_bitrate": int(avg_bitrate or 0),
            "low_quality_count": low_quality_count,
            "total_tracks": total_tracks,
        },
        "storage": {
            "total_size": total_size,
            "by_format": storage_by_format,
        },
        "recent_activity": recent_activity,
        "duplicates": {
            "groups": dup_groups,
            "reclaimable_bytes": dup_reclaimable,
        },
        "upcoming_tasks": upcoming,
    }

    return result


@router.get("/stats/detailed")
async def detailed_stats(request: Request, db: AsyncSession = Depends(get_db)):
    """Detailed library statistics for the stats page."""
    from backend.models.analysis import TrackAnalysis
    from backend.models.embedding import TrackEmbedding
    from backend.models.favorite import Favorite
    from backend.models.playlist import Playlist
    from backend.models.job import Job

    # Basic counts
    track_count = (await db.execute(select(func.count(Track.id)))).scalar() or 0
    artist_count = (await db.execute(select(func.count(Artist.id)))).scalar() or 0
    album_count = (await db.execute(select(func.count(Album.id)))).scalar() or 0
    total_size = (await db.execute(select(func.sum(Track.file_size)))).scalar() or 0
    total_duration = (await db.execute(select(func.sum(Track.duration_seconds)))).scalar() or 0

    # Formats
    formats = {}
    fmt_result = await db.execute(
        select(Track.format, func.count(Track.id)).group_by(Track.format)
    )
    for fmt, count in fmt_result.all():
        formats[fmt or "unknown"] = count

    # Genres (top 20)
    genre_result = await db.execute(
        select(Track.genre, func.count(Track.id))
        .where(Track.genre.isnot(None))
        .group_by(Track.genre)
        .order_by(func.count(Track.id).desc())
        .limit(20)
    )
    genres = [{"name": g, "count": c} for g, c in genre_result.all()]

    # Top artists by track count
    top_artists_result = await db.execute(
        select(Artist.name, func.count(Track.id))
        .join(Track, Track.artist_id == Artist.id)
        .group_by(Artist.id)
        .order_by(func.count(Track.id).desc())
        .limit(15)
    )
    top_artists = [{"name": n, "count": c} for n, c in top_artists_result.all()]

    # Year distribution
    year_result = await db.execute(
        select(Track.year, func.count(Track.id))
        .where(Track.year.isnot(None))
        .group_by(Track.year)
        .order_by(Track.year)
    )
    years = [{"year": y, "count": c} for y, c in year_result.all()]

    # Bitrate distribution
    bitrate_result = await db.execute(
        select(
            case(
                (Track.bitrate < 128, "< 128"),
                (Track.bitrate < 256, "128-255"),
                (Track.bitrate < 320, "256-319"),
                (Track.bitrate == 320, "320"),
                (Track.bitrate > 320, "Lossless"),
                else_="Unknown"
            ).label("range"),
            func.count(Track.id)
        )
        .where(Track.bitrate.isnot(None))
        .group_by("range")
    )
    bitrates = {r: c for r, c in bitrate_result.all()}

    # Analysis / embedding counts
    # Same definitions as the Analysis page: only rows whose track still exists, and
    # failed-analysis stubs (bpm IS NULL) don't count as analyzed.
    analyzed = (await db.execute(
        select(func.count(TrackAnalysis.track_id)).join(Track, Track.id == TrackAnalysis.track_id)
        .where(TrackAnalysis.bpm.isnot(None))
    )).scalar() or 0
    embedded = (await db.execute(
        select(func.count(TrackEmbedding.track_id)).join(Track, Track.id == TrackEmbedding.track_id)
    )).scalar() or 0
    # favorites / most_played are the caller's; favorites_total (all users) feeds total_rows.
    user_id = await caller_id(request, db)
    favorites_total = (await db.execute(select(func.count(Favorite.id)))).scalar() or 0
    favorites = (await db.execute(
        select(func.count(Favorite.id)).where(Favorite.user_id == user_id)
    )).scalar() or 0
    playlists = (await db.execute(select(func.count(Playlist.id)))).scalar() or 0

    # Most played (by the caller)
    from backend.models.user_track_stats import UserTrackStats
    most_played_result = await db.execute(
        select(Track.title, Artist.name, UserTrackStats.play_count)
        .join(UserTrackStats, UserTrackStats.track_id == Track.id)
        .outerjoin(Artist, Track.artist_id == Artist.id)
        .where(UserTrackStats.user_id == user_id, UserTrackStats.play_count > 0)
        .order_by(UserTrackStats.play_count.desc())
        .limit(10)
    )
    most_played = [{"title": t, "artist": a, "plays": p} for t, a, p in most_played_result.all()]

    # Recent jobs
    jobs_result = await db.execute(
        select(Job.type, func.count(Job.id), func.sum(case((Job.status == "completed", 1), else_=0)))
        .group_by(Job.type)
    )
    job_stats = [{"type": t, "total": total, "completed": comp or 0} for t, total, comp in jobs_result.all()]

    # Database & backend stats
    import sys
    import os
    from pathlib import Path
    from backend.config import get_settings
    from backend.database import _is_postgres

    settings = get_settings()
    db_backend = settings.database.backend
    db_info: dict = {"backend": db_backend}

    if not _is_postgres():
        db_path = Path(settings.database.path)
        if db_path.exists():
            db_info["file_size_bytes"] = db_path.stat().st_size
            # WAL file size
            wal_path = Path(str(db_path) + "-wal")
            if wal_path.exists():
                db_info["wal_size_bytes"] = wal_path.stat().st_size
    else:
        # PostgreSQL — get database size
        try:
            pg_size = await db.execute(
                select(func.pg_database_size(func.current_database()))
            )
            db_info["file_size_bytes"] = pg_size.scalar() or 0
        except Exception:
            pass

    # Table row counts for insight
    from backend.models.play_history import PlayHistory
    play_count_total = (await db.execute(select(func.count(PlayHistory.id)))).scalar() or 0
    job_count_total = (await db.execute(select(func.count(Job.id)))).scalar() or 0

    db_info["total_rows"] = track_count + artist_count + album_count + play_count_total + job_count_total + favorites_total + analyzed + embedded

    # Backend info
    backend_info = {
        "python_version": sys.version.split()[0],
        "pid": os.getpid(),
    }

    return {
        "tracks": track_count,
        "artists": artist_count,
        "albums": album_count,
        "total_size_bytes": total_size,
        "total_duration_seconds": total_duration,
        "formats": formats,
        "genres": genres,
        "top_artists": top_artists,
        "years": years,
        "bitrates": bitrates,
        "analyzed": analyzed,
        "embedded": embedded,
        "favorites": favorites,
        "playlists": playlists,
        "most_played": most_played,
        "job_stats": job_stats,
        "database": db_info,
        "backend": backend_info,
    }


@router.get("/stats/insights")
async def get_insights(request: Request, db: AsyncSession = Depends(get_db)):
    """AI-generated insights on the caller's listening this week."""
    from backend.services.ai.insights import generate_insights
    return await generate_insights(db, user_id=await caller_id(request, db))


@router.get("/stats/play-history")
async def play_history_stats(
    request: Request,
    period: str = "7d",
    all_users: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """The caller's play history over time for charting. Periods: 24h, 7d, 30d, 90d, all.
    all_users=true (admins only) charts everyone's plays."""
    from backend.models.play_history import PlayHistory
    from datetime import timedelta

    now = datetime.utcnow()
    period_map = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30), "90d": timedelta(days=90)}
    cutoff = now - period_map.get(period, timedelta(days=7)) if period != "all" else None

    from backend.services.user_scope import caller_is_admin
    conds = []
    if cutoff:
        conds.append(PlayHistory.played_at >= cutoff)
    if not (all_users and caller_is_admin(request)):
        conds.append(PlayHistory.user_id == await caller_id(request, db))

    # Plays over time (group by hour for 24h, by day otherwise)
    if period == "24h":
        time_col = func.strftime("%Y-%m-%d %H:00", PlayHistory.played_at)
    else:
        time_col = func.strftime("%Y-%m-%d", PlayHistory.played_at)

    timeline_q = (
        select(time_col.label("period"), func.count(PlayHistory.id).label("count"))
        .group_by(time_col)
        .order_by(time_col)
    )
    timeline_q = timeline_q.where(*conds)
    timeline = [{"period": p, "count": c} for p, c in (await db.execute(timeline_q)).all()]

    # Top tracks by play count in period
    top_tracks_q = (
        select(Track.title, Artist.name.label("artist"), func.count(PlayHistory.id).label("plays"))
        .join(Track, PlayHistory.track_id == Track.id)
        .outerjoin(Artist, Track.artist_id == Artist.id)
        .group_by(PlayHistory.track_id)
        .order_by(func.count(PlayHistory.id).desc())
        .limit(20)
    )
    top_tracks_q = top_tracks_q.where(*conds)
    top_tracks = [{"title": t, "artist": a, "plays": p} for t, a, p in (await db.execute(top_tracks_q)).all()]

    # Top artists
    top_artists_q = (
        select(Artist.name, func.count(PlayHistory.id).label("plays"))
        .join(Track, PlayHistory.track_id == Track.id)
        .join(Artist, Track.artist_id == Artist.id)
        .group_by(Artist.id)
        .order_by(func.count(PlayHistory.id).desc())
        .limit(15)
    )
    top_artists_q = top_artists_q.where(*conds)
    top_artists = [{"name": n, "plays": p} for n, p in (await db.execute(top_artists_q)).all()]

    # Total plays in period
    total_q = select(func.count(PlayHistory.id))
    total_q = total_q.where(*conds)
    total_plays = (await db.execute(total_q)).scalar() or 0

    # Hourly distribution (plays by hour of day)
    hour_q = (
        select(func.strftime("%H", PlayHistory.played_at).label("hour"), func.count(PlayHistory.id))
        .group_by(func.strftime("%H", PlayHistory.played_at))
        .order_by(func.strftime("%H", PlayHistory.played_at))
    )
    hour_q = hour_q.where(*conds)
    hourly = [{"hour": int(h), "count": c} for h, c in (await db.execute(hour_q)).all()]

    return {
        "timeline": timeline,
        "top_tracks": top_tracks,
        "top_artists": top_artists,
        "hourly_distribution": hourly,
        "total_plays": total_plays,
        "period": period,
    }
