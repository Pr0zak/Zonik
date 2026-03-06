"""Analysis API routes - audio analysis, vibe search, enrichment triggers."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime

log = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, BackgroundTasks, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db, async_session
from backend.models.track import Track
from backend.models.analysis import TrackAnalysis
from backend.models.embedding import TrackEmbedding
from backend.models.job import Job
from backend.api.websocket import broadcast_job_update

router = APIRouter()


@router.get("/stats")
async def analysis_stats(db: AsyncSession = Depends(get_db)):
    """Get analysis coverage statistics."""
    total_tracks = (await db.execute(select(func.count(Track.id)))).scalar() or 0
    analyzed = (await db.execute(select(func.count(TrackAnalysis.track_id)))).scalar() or 0
    with_embeddings = (await db.execute(select(func.count(TrackEmbedding.track_id)))).scalar() or 0

    return {
        "total_tracks": total_tracks,
        "analyzed": analyzed,
        "with_embeddings": with_embeddings,
        "analysis_pct": round(analyzed / total_tracks * 100, 1) if total_tracks else 0,
        "embedding_pct": round(with_embeddings / total_tracks * 100, 1) if total_tracks else 0,
    }


@router.post("/start")
async def start_analysis(background_tasks: BackgroundTasks, force: bool = False):
    """Queue all unanalyzed tracks for audio analysis."""
    job_id = str(uuid.uuid4())

    async def run_analysis():
        from backend.services.analyzer import analyze_track_async

        async with async_session() as db:
            # Find tracks needing analysis
            if force:
                result = await db.execute(select(Track.id, Track.file_path))
            else:
                analyzed_ids = select(TrackAnalysis.track_id)
                result = await db.execute(
                    select(Track.id, Track.file_path).where(Track.id.notin_(analyzed_ids))
                )
            tracks = result.all()

            total = len(tracks)
            job = Job(
                id=job_id, type="audio_analysis", card="an", status="running",
                total=total, started_at=datetime.utcnow(),
            )
            db.add(job)
            await db.commit()
            await broadcast_job_update({"id": job_id, "type": "audio_analysis", "status": "running", "progress": 0, "total": total})

            try:
                import asyncio as _aio
                for i, (track_id, file_path) in enumerate(tracks):
                    try:
                        analysis = await analyze_track_async(file_path)
                        if analysis:
                            ta = TrackAnalysis(
                                track_id=track_id,
                                bpm=analysis.get("bpm"),
                                key=analysis.get("key"),
                                scale=analysis.get("scale"),
                                energy=analysis.get("energy"),
                                danceability=analysis.get("danceability"),
                                loudness=analysis.get("loudness"),
                            )
                            await db.merge(ta)
                    except Exception as e:
                        log.warning("Analysis failed for track %s: %s", track_id, e)

                    progress = i + 1
                    # Batch DB commits every 10 tracks, WS updates every 5
                    if progress % 10 == 0 or progress == total:
                        job.progress = progress
                        await db.merge(job)
                        await db.commit()
                    if progress % 5 == 0 or progress == total:
                        await broadcast_job_update({"id": job_id, "type": "audio_analysis", "status": "running", "progress": progress, "total": total})
                    # Pause between tracks so CPU-bound Essentia doesn't starve HTTP
                    await _aio.sleep(0.2)

                job.status = "completed"
            except Exception as e:
                log.error("Audio analysis job crashed: %s", e)
                job.status = "failed"
                job.result = json.dumps({"error": str(e)})
            job.finished_at = datetime.utcnow()
            await db.merge(job)
            await db.commit()
            await broadcast_job_update({"id": job_id, "type": "audio_analysis", "status": job.status, "progress": job.progress or 0, "total": total})

    background_tasks.add_task(run_analysis)
    return {"job_id": job_id}


@router.post("/embeddings/start")
async def start_embeddings(background_tasks: BackgroundTasks, force: bool = False):
    """Queue all tracks for CLAP vibe embedding generation."""
    job_id = str(uuid.uuid4())

    async def run_embeddings():
        from backend.services.embeddings import generate_embedding_async

        async with async_session() as db:
            if force:
                result = await db.execute(select(Track.id, Track.file_path))
            else:
                embedded_ids = select(TrackEmbedding.track_id)
                result = await db.execute(
                    select(Track.id, Track.file_path).where(Track.id.notin_(embedded_ids))
                )
            tracks = result.all()

            total = len(tracks)
            job = Job(
                id=job_id, type="vibe_embeddings", card="an", status="running",
                total=total, started_at=datetime.utcnow(),
            )
            db.add(job)
            await db.commit()
            await broadcast_job_update({"id": job_id, "type": "vibe_embeddings", "status": "running", "progress": 0, "total": total})

            try:
                import asyncio as _aio
                for i, (track_id, file_path) in enumerate(tracks):
                    try:
                        emb_bytes = await generate_embedding_async(file_path)
                        if emb_bytes:
                            te = TrackEmbedding(
                                track_id=track_id,
                                embedding=emb_bytes,
                            )
                            await db.merge(te)
                    except Exception as e:
                        log.warning("Embedding failed for track %s: %s", track_id, e)

                    progress = i + 1
                    if progress % 10 == 0 or progress == total:
                        job.progress = progress
                        await db.merge(job)
                        await db.commit()
                    if progress % 5 == 0 or progress == total:
                        await broadcast_job_update({"id": job_id, "type": "vibe_embeddings", "status": "running", "progress": progress, "total": total})
                    await _aio.sleep(0.2)

                job.status = "completed"
            except Exception as e:
                log.error("Vibe embeddings job crashed: %s", e)
                job.status = "failed"
                job.result = json.dumps({"error": str(e)})
            job.finished_at = datetime.utcnow()
            await db.merge(job)
            await db.commit()
            await broadcast_job_update({"id": job_id, "type": "vibe_embeddings", "status": job.status, "progress": job.progress or 0, "total": total})

    background_tasks.add_task(run_embeddings)
    return {"job_id": job_id}


@router.post("/enrich")
async def start_enrichment(background_tasks: BackgroundTasks):
    """Run metadata enrichment pipeline on tracks missing metadata."""
    import asyncio
    job_id = str(uuid.uuid4())

    async def run_enrichment():
        from backend.services.enrichment import enrich_track, ENRICH_TRACK_TIMEOUT
        import logging
        log = logging.getLogger("enrichment")

        status = "completed"
        progress = 0
        total = 0
        enriched = 0
        errors = 0

        try:
            # Step 1: Collect track IDs in one session (lightweight query)
            async with async_session() as db:
                result = await db.execute(
                    select(Track.id)
                    .where((Track.genre.is_(None)) | (Track.cover_art_path.is_(None)))
                )
                track_ids = [row[0] for row in result.all()]
                total = len(track_ids)

                job = Job(
                    id=job_id, type="enrichment", card="en", status="running",
                    total=total, started_at=datetime.utcnow(),
                )
                db.add(job)
                await db.commit()

            await broadcast_job_update({"id": job_id, "type": "enrichment", "status": "running", "progress": 0, "total": total})

            # Step 2: Process each track in its own session (isolation)
            for i, track_id in enumerate(track_ids):
                # Check cancellation every 10 tracks
                if i % 10 == 0:
                    try:
                        async with async_session() as check_db:
                            result = await check_db.execute(select(Job.status).where(Job.id == job_id))
                            job_status = result.scalar_one_or_none()
                            if job_status == "failed":
                                log.info(f"[enrich] Job cancelled at {i+1}/{total}")
                                status = "failed"
                                break
                    except Exception as e:
                        log.debug("Enrichment cancel check failed: %s", e)

                try:
                    async with async_session() as track_db:
                        result = await track_db.execute(
                            select(Track).options(selectinload(Track.artist), selectinload(Track.album))
                            .where(Track.id == track_id)
                        )
                        track = result.scalar_one_or_none()
                        if not track:
                            progress = i + 1
                            continue

                        track_label = f"{track.artist.name if track.artist else '?'} - {track.title}"
                        changes = await asyncio.wait_for(
                            enrich_track(track_db, track),
                            timeout=ENRICH_TRACK_TIMEOUT,
                        )
                        if changes:
                            enriched += 1
                            log.info(f"[enrich] {track_label}: {list(changes.keys())}")
                except asyncio.TimeoutError:
                    errors += 1
                    log.warning(f"[enrich] Timed out ({ENRICH_TRACK_TIMEOUT}s): track {track_id}")
                except Exception as e:
                    errors += 1
                    log.error(f"[enrich] Error on track {track_id}: {e}")

                progress = i + 1

                # WebSocket every track, DB every 10
                await broadcast_job_update({"id": job_id, "type": "enrichment", "status": "running", "progress": progress, "total": total})
                if progress % 10 == 0 or progress == total:
                    try:
                        async with async_session() as prog_db:
                            result = await prog_db.execute(select(Job).where(Job.id == job_id))
                            pjob = result.scalar_one_or_none()
                            if pjob and pjob.status != "failed":
                                pjob.progress = progress
                                await prog_db.commit()
                    except Exception as e:
                        log.debug("Enrichment progress update failed: %s", e)

                # Rate limit between tracks
                await asyncio.sleep(1.5)

        except Exception as e:
            log.error(f"[enrich] Fatal error: {e}", exc_info=True)
            status = "failed"

        # Final job update in clean session
        try:
            async with async_session() as finish_db:
                result = await finish_db.execute(select(Job).where(Job.id == job_id))
                fjob = result.scalar_one_or_none()
                if fjob:
                    fjob.status = status
                    fjob.progress = progress
                    fjob.total = total
                    fjob.result = json.dumps({"enriched": enriched, "errors": errors, "total": total})
                    fjob.finished_at = datetime.utcnow()
                    await finish_db.commit()
        except Exception as e:
            log.error(f"[enrich] Failed to update final job status: {e}")
        await broadcast_job_update({"id": job_id, "type": "enrichment", "status": status, "progress": progress, "total": total})

    background_tasks.add_task(run_enrichment)
    return {"job_id": job_id}


class EchoMatchRequest(BaseModel):
    track_id: str
    limit: int = 20


@router.post("/echo-match")
async def echo_match_endpoint(req: EchoMatchRequest, db: AsyncSession = Depends(get_db)):
    """Find tracks with similar vibes using CLAP embeddings."""
    from backend.services.similarity import echo_match

    results = await echo_match(db, req.track_id, limit=req.limit)
    if not results:
        return {"tracks": []}

    # Resolve track details
    track_ids = [r["track_id"] for r in results]
    tracks_result = await db.execute(
        select(Track).options(selectinload(Track.artist), selectinload(Track.album))
        .where(Track.id.in_(track_ids))
    )
    track_map = {t.id: t for t in tracks_result.scalars().all()}

    tracks_out = []
    for r in results:
        t = track_map.get(r["track_id"])
        if t:
            tracks_out.append({
                "id": t.id,
                "title": t.title,
                "artist": t.artist.name if t.artist else None,
                "album": t.album.title if t.album else None,
                "similarity": r.get("similarity", 0),
            })

    return {"tracks": tracks_out}


class VibeSearchRequest(BaseModel):
    query: str | None = None
    track_id: str | None = None
    limit: int = 20


@router.post("/vibe-search")
async def vibe_search(req: VibeSearchRequest, db: AsyncSession = Depends(get_db)):
    """Search by vibe - either text description or seed track (Echo Match)."""
    if req.track_id:
        from backend.services.similarity import echo_match
        results = await echo_match(db, req.track_id, limit=req.limit)
        return {"results": results, "type": "echo_match"}
    elif req.query:
        from backend.services.similarity import text_vibe_search
        results = await text_vibe_search(db, req.query, limit=req.limit)
        return {"results": results, "type": "text_search"}
    else:
        return {"error": "Provide either query or track_id"}


class SteadyVibesRequest(BaseModel):
    seed_track_id: str
    length: int = 20


@router.post("/steady-vibes")
async def steady_vibes(req: SteadyVibesRequest, db: AsyncSession = Depends(get_db)):
    """Generate a Steady Vibes playlist from a seed track."""
    from backend.services.similarity import steady_vibes_playlist
    playlist = await steady_vibes_playlist(db, req.seed_track_id, length=req.length)
    return {"playlist": playlist}


@router.get("/track/{track_id}")
async def get_track_analysis(track_id: str, db: AsyncSession = Depends(get_db)):
    """Get analysis results for a specific track."""
    result = await db.execute(
        select(TrackAnalysis).where(TrackAnalysis.track_id == track_id)
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        return {"error": "No analysis for this track"}

    has_embedding = (await db.execute(
        select(func.count(TrackEmbedding.track_id)).where(TrackEmbedding.track_id == track_id)
    )).scalar() > 0

    return {
        "track_id": track_id,
        "bpm": analysis.bpm,
        "key": analysis.key,
        "scale": analysis.scale,
        "energy": analysis.energy,
        "danceability": analysis.danceability,
        "loudness": analysis.loudness,
        "has_embedding": has_embedding,
        "analyzed_at": analysis.analyzed_at.isoformat() if analysis.analyzed_at else None,
    }
