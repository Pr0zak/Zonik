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

            job = Job(
                id=job_id, type="audio_analysis", card="an", status="running",
                total=len(tracks), started_at=datetime.utcnow(),
            )
            db.add(job)
            await db.commit()

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
                except Exception as e:
                    pass  # Continue with next track

            job.status = "completed"
            job.finished_at = datetime.utcnow()
            await db.merge(job)
            await db.commit()

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

            job = Job(
                id=job_id, type="vibe_embeddings", card="an", status="running",
                total=len(tracks), started_at=datetime.utcnow(),
            )
            db.add(job)
            await db.commit()

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

            job.status = "completed"
            job.finished_at = datetime.utcnow()
            await db.merge(job)
            await db.commit()

    background_tasks.add_task(run_embeddings)
    return {"job_id": job_id}


@router.post("/enrich")
async def start_enrichment(background_tasks: BackgroundTasks):
    """Run metadata enrichment pipeline on tracks missing metadata."""
    job_id = str(uuid.uuid4())

    async def run_enrichment():
        from backend.services.enrichment import enrich_track

        async with async_session() as db:
            # Find tracks missing genre or cover art
            result = await db.execute(
                select(Track).options(selectinload(Track.artist), selectinload(Track.album))
                .where((Track.genre.is_(None)) | (Track.cover_art_path.is_(None)))
                .limit(200)
            )
            tracks = result.scalars().all()

            job = Job(
                id=job_id, type="enrichment", card="en", status="running",
                total=len(tracks), started_at=datetime.utcnow(),
            )
            db.add(job)
            await db.commit()

            for i, track in enumerate(tracks):
                try:
                    await enrich_track(db, track)
                except Exception:
                    pass

                job.progress = i + 1
                await db.merge(job)
                await db.commit()

            job.status = "completed"
            job.finished_at = datetime.utcnow()
            await db.merge(job)
            await db.commit()

    background_tasks.add_task(run_enrichment)
    return {"job_id": job_id}


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
