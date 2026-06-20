"""Scheduled task definitions and execution."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime

from sqlalchemy import select
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
        # after rollback/close, the detached object can't refresh attributes
        final_status = job.status
        final_result = job.result
        final_finished = job.finished_at

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
                        finished_at=final_finished,
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
                        await _auto_download_missing(missing, task_name)
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
                    await _auto_download_recommendations(dl_db, min_score, max_downloads)
            except Exception as e:
                log.error(f"Auto-download recommendations failed: {e}")


async def _auto_download_recommendations(db: AsyncSession, min_score: float, max_downloads: int):
    """Auto-download top pending recommendations above score threshold."""
    from sqlalchemy import select
    from backend.models.recommendation import Recommendation

    result = await db.execute(
        select(Recommendation)
        .where(Recommendation.status == "pending", Recommendation.score >= min_score)
        .order_by(Recommendation.score.desc())
        .limit(max_downloads)
    )
    recs = result.scalars().all()
    if not recs:
        log.info(f"No recommendations above {min_score} to auto-download")
        return

    missing = [{"artist": r.artist, "track": r.track, "rec_id": r.id} for r in recs]
    log.info(f"Auto-downloading {len(missing)} recommendations (score >= {min_score})")

    await _auto_download_missing(missing, "recommendation_refresh")

    # Mark downloaded recommendations
    for r in recs:
        r.status = "downloaded"
    await db.commit()


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


async def _auto_download_missing(missing: list[dict], source: str):
    """Trigger individual download jobs for each missing track via enqueue_download.
    Uses enqueue_download which has short-lived DB sessions to avoid pool exhaustion.

    For source="upgrade_scan", entries may carry `upgrade_id` and `track_id`. We
    attach the download job_id to the TrackUpgrade row, bump `attempts`, and on
    job failure mark the row as `failed` so it doesn't sit at `pending` forever.
    Successful uploads are marked `completed` by the scanner during import.
    """
    import asyncio
    import uuid as _uuid
    from sqlalchemy import update as _update
    from backend.api.download import enqueue_download
    from backend.models.upgrade import TrackUpgrade

    total = len(missing)
    log.info(f"Auto-downloading {total} missing tracks from {source}")

    # Circuit-breaker: if the Soulseek download backend is down, skip the whole
    # batch instead of spawning N instantly-failing jobs (which used to pile up
    # hundreds of identical 'connection failed' rows). Leave the queue for next run.
    if not await _download_backend_ready():
        log.warning(f"[auto-download] Soulseek backend not ready — skipping {total} downloads from {source}")
        return

    # Map scheduler source to download source label
    dl_source = {"lastfm_top_tracks": "discovery", "discover_similar": "similar", "remix_discovery": "remix", "recommendation_refresh": "recommendation", "upgrade_scan": "upgrade"}.get(source, "discovery")

    sem = asyncio.Semaphore(4)  # limit concurrency of enqueue calls

    async def download_one(t: dict):
        artist = t.get("artist", "")
        track = t.get("track", "")
        if not artist or not track:
            return

        upgrade_id = t.get("upgrade_id") if source == "upgrade_scan" else None
        job_id = str(_uuid.uuid4())
        target_track_id = None

        # Enforce max_attempts so a permanently-unavailable track isn't retried
        # forever on every scan. Also capture the target track_id so the importer
        # replaces the exact original instead of fuzzy-matching the download's tags.
        if upgrade_id:
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
                        return
            except Exception as e:
                log.debug(f"[auto-download] max_attempts check failed for {upgrade_id}: {e}")

        # Pre-link upgrade row to this job + bump attempts so the pipeline is observable.
        if upgrade_id:
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

        async with sem:
            try:
                returned_job_id = await enqueue_download(artist, track, job_id=job_id, source=dl_source, target_track_id=target_track_id)
            except Exception as e:
                log.warning(f"[auto-download] Failed {artist} — {track}: {e}")
                returned_job_id = job_id

        # If this was an upgrade row that's STILL `downloading`, the scanner never
        # called _mark_upgrade_completed (download failed or imported file wasn't
        # an upgrade). Mark it failed with the job's error message.
        if upgrade_id:
            try:
                async with async_session() as final_db:
                    row = (await final_db.execute(
                        select(TrackUpgrade).where(TrackUpgrade.id == upgrade_id)
                    )).scalar_one_or_none()
                    if not row or row.status != "downloading":
                        return
                    err = "Download failed"
                    job_row = (await final_db.execute(
                        select(Job).where(Job.id == returned_job_id)
                    )).scalar_one_or_none()
                    if job_row and job_row.result:
                        try:
                            err_payload = json.loads(job_row.result)
                            err = (
                                err_payload.get("last_error")
                                or err_payload.get("error")
                                or err_payload.get("message")
                                or err
                            )
                        except (ValueError, TypeError):
                            err = str(job_row.result)[:500]
                    await final_db.execute(
                        _update(TrackUpgrade)
                        .where(TrackUpgrade.id == upgrade_id, TrackUpgrade.status == "downloading")
                        .values(
                            status="failed",
                            error_message=str(err)[:500],
                            updated_at=datetime.utcnow(),
                        )
                    )
                    await final_db.commit()
            except Exception as e:
                log.debug(f"[auto-download] Could not finalize upgrade {upgrade_id}: {e}")

    tasks = [asyncio.create_task(download_one(t)) for t in missing]
    await asyncio.gather(*tasks, return_exceptions=True)


async def _run_lastfm_top_tracks(db: AsyncSession, job: Job, count: int = 50):
    """Pull Last.fm top chart, find missing tracks, store list for download."""
    from backend.services.lastfm import get_top_tracks
    chart = await get_top_tracks(limit=count)
    missing = []
    in_library = 0
    for t in chart:
        result = await db.execute(
            select(Track).join(Artist, Track.artist_id == Artist.id).where(
                Track.title.ilike(t["name"]),
                Artist.name.ilike(t["artist"]),
            ).limit(1)
        )
        if result.scalar_one_or_none():
            in_library += 1
        else:
            missing.append({"artist": t["artist"], "track": t["name"], "status": "missing"})

    job.total = len(chart)
    job.progress = in_library
    job.tracks = json.dumps(missing)
    job.result = json.dumps({
        "total_chart": len(chart),
        "in_library": in_library,
        "missing": len(missing),
    })


async def _run_discover_similar(db: AsyncSession, job: Job, count: int = 10):
    """Find similar tracks from favorites, flag missing ones."""
    from backend.services.lastfm import get_similar_tracks
    from backend.services.soulseek import normalize_text
    favorites = (await db.execute(
        select(Favorite).options(
            selectinload(Favorite.track).selectinload(Track.artist)
        ).where(Favorite.track_id.isnot(None)).limit(count)
    )).scalars().all()

    missing = []
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

            result = await db.execute(
                select(Track).join(Artist, Track.artist_id == Artist.id).where(
                    Track.title.ilike(t["name"]),
                    Artist.name.ilike(t["artist"]),
                ).limit(1)
            )
            if result.scalar_one_or_none():
                in_library += 1
            else:
                missing.append({
                    "artist": t["artist"], "track": t["name"], "status": "missing",
                    "source": f"{fav.track.artist.name} — {fav.track.title}",
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

    query = query.order_by(Track.bitrate.asc().nullslast()).limit(count)
    result = await db.execute(query)
    tracks = result.scalars().all()

    # Create TrackUpgrade records (idempotent — skip existing pending/queued/downloading)
    from backend.models.upgrade import TrackUpgrade
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
        "auto_download": cfg.get("auto_download", False),
    })

    await broadcast_job_update({
        "id": job.id, "type": "upgrade_scan", "status": "running",
        "progress": len(tracks), "total": len(tracks),
        "description": f"Found {len(tracks)} tracks to upgrade",
    })

    log.info(f"Upgrade scan ({mode}): found {len(tracks)} tracks")


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
            # Check if in library
            lib_match = await db.execute(
                select(Track.id).join(Artist, Track.artist_id == Artist.id).where(
                    Track.title.ilike(r["name"]),
                    Artist.name.ilike(r["artist"]),
                ).limit(1)
            )
            in_library = lib_match.scalar_one_or_none() is not None
            if not in_library:
                all_remixes.append({
                    "artist": r["artist"],
                    "track": r["name"],
                    "status": "missing",
                    "version_type": r.get("version_type", "remix"),
                    "source_track": t.title,
                    "source_artist": t.artist.name if t.artist else "",
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
