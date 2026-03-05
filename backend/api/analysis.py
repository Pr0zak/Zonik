"""Analysis API routes - audio analysis, vibe search, enrichment triggers."""
from __future__ import annotations

import json
import uuid
from datetime import datetime

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

                    job.progress = i + 1
                    await db.merge(job)
                    await db.commit()
                except Exception:
                    pass

                if (i + 1) % 5 == 0 or i + 1 == total:
                    await broadcast_job_update({"id": job_id, "type": "audio_analysis", "status": "running", "progress": i + 1, "total": total})

            job.status = "completed"
            job.finished_at = datetime.utcnow()
            await db.merge(job)
            await db.commit()
            await broadcast_job_update({"id": job_id, "type": "audio_analysis", "status": "completed", "progress": total, "total": total})

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

            for i, (track_id, file_path) in enumerate(tracks):
                try:
                    emb_bytes = await generate_embedding_async(file_path)
                    if emb_bytes:
                        te = TrackEmbedding(
                            track_id=track_id,
                            embedding=emb_bytes,
                        )
                        await db.merge(te)

                    job.progress = i + 1
                    await db.merge(job)
                    await db.commit()
                except Exception:
                    pass

                if (i + 1) % 5 == 0 or i + 1 == total:
                    await broadcast_job_update({"id": job_id, "type": "vibe_embeddings", "status": "running", "progress": i + 1, "total": total})

            job.status = "completed"
            job.finished_at = datetime.utcnow()
            await db.merge(job)
            await db.commit()
            await broadcast_job_update({"id": job_id, "type": "vibe_embeddings", "status": "completed", "progress": total, "total": total})

    background_tasks.add_task(run_embeddings)
    return {"job_id": job_id}


@router.post("/enrich")
async def start_enrichment(background_tasks: BackgroundTasks):
    """Run metadata enrichment pipeline on tracks missing metadata."""
    import asyncio
    job_id = str(uuid.uuid4())

    async def run_enrichment():
        from backend.services.enrichment import enrich_track

        status = "completed"
        progress = 0
        total = 0
        enriched = 0
        errors = 0

        try:
            async with async_session() as db:
                # Find ALL tracks missing genre or cover art (no limit)
                result = await db.execute(
                    select(Track).options(selectinload(Track.artist), selectinload(Track.album))
                    .where((Track.genre.is_(None)) | (Track.cover_art_path.is_(None)))
                )
                tracks = result.scalars().all()

                total = len(tracks)
                job = Job(
                    id=job_id, type="enrichment", card="en", status="running",
                    total=total, started_at=datetime.utcnow(),
                )
                db.add(job)
                await db.commit()
                await broadcast_job_update({"id": job_id, "type": "enrichment", "status": "running", "progress": 0, "total": total})

                for i, track in enumerate(tracks):
                    try:
                        changes = await enrich_track(db, track)
                        if changes:
                            enriched += 1
                    except Exception as e:
                        errors += 1
                        # Rollback if session is in a bad state
                        try:
                            await db.rollback()
                        except Exception:
                            pass

                    progress = i + 1

                    if (i + 1) % 5 == 0 or i + 1 == total:
                        await broadcast_job_update({"id": job_id, "type": "enrichment", "status": "running", "progress": i + 1, "total": total})
                        # Also update DB progress periodically (separate session)
                        try:
                            async with async_session() as prog_db:
                                pjob = (await prog_db.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
                                if pjob:
                                    pjob.progress = i + 1
                                    await prog_db.commit()
                        except Exception:
                            pass

                    # Rate limit: 1.5 sec between tracks to respect MusicBrainz/Deezer limits
                    await asyncio.sleep(1.5)
        except Exception:
            status = "failed"

        # Update job in separate session
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
        except Exception:
            pass
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
