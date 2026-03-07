"""Recommendations API — AI Music Assistant endpoints."""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db, async_session
from backend.models.recommendation import Recommendation
from backend.models.taste_profile import TasteProfile

router = APIRouter()


@router.get("")
async def list_recommendations(
    limit: int = 25,
    offset: int = 0,
    status: str | None = None,
    source: str | None = None,
    min_score: float = 0.0,
    db: AsyncSession = Depends(get_db),
):
    """Get paginated recommendations sorted by score."""
    query = select(Recommendation).where(Recommendation.score >= min_score)

    if status:
        query = query.where(Recommendation.status == status)
    else:
        query = query.where(Recommendation.status == "pending")

    if source:
        query = query.where(Recommendation.source == source)

    total = (await db.execute(
        select(func.count()).select_from(query.subquery())
    )).scalar() or 0

    query = query.order_by(Recommendation.score.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    recs = result.scalars().all()

    # Load profile stats
    tp = await db.get(TasteProfile, "default")
    profile_stats = None
    if tp:
        try:
            pd = json.loads(tp.profile_data)
            profile_stats = {
                "track_count": tp.track_count,
                "favorite_count": tp.favorite_count,
                "analyzed_count": tp.analyzed_count,
                "top_genres": list(pd.get("genre_distribution", {}).keys())[:5],
            }
        except Exception:
            pass

    return {
        "items": [
            {
                "id": r.id,
                "artist": r.artist,
                "track": r.track,
                "source": r.source,
                "source_detail": r.source_detail,
                "score": r.score,
                "score_breakdown": json.loads(r.score_breakdown) if r.score_breakdown else {},
                "status": r.status,
                "feedback": r.feedback,
                "explanation": r.explanation,
                "lastfm_listeners": r.lastfm_listeners,
                "lastfm_match": r.lastfm_match,
                "image_url": r.image_url,
                "preview_url": r.preview_url,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in recs
        ],
        "total": total,
        "profile_computed_at": tp.computed_at.isoformat() if tp else None,
        "profile_stats": profile_stats,
    }


class RefreshRequest(BaseModel):
    force: bool = False
    limit: int = 100
    use_claude: bool = False


@router.post("/refresh")
async def refresh_recommendations(req: RefreshRequest, background_tasks: BackgroundTasks):
    """Trigger a recommendation refresh (background job)."""
    import uuid
    from backend.models.job import Job
    from backend.api.websocket import broadcast_job_update

    job_id = str(uuid.uuid4())

    async def do_refresh():
        from backend.services.recommender import refresh_recommendations as _refresh

        async with async_session() as db:
            job = Job(
                id=job_id, type="recommendation_refresh", card="rec",
                status="running", started_at=datetime.utcnow(),
            )
            db.add(job)
            await db.commit()
            total_steps = 6 if req.use_claude else 5
            await broadcast_job_update({
                "id": job_id, "type": "recommendation_refresh",
                "status": "running", "progress": 0, "total": total_steps,
                "description": "AI Recommendations",
            })

            try:
                async def on_progress(current, total, desc=""):
                    job.progress = current
                    job.total = total
                    await db.merge(job)
                    await db.commit()
                    await broadcast_job_update({
                        "id": job_id, "type": "recommendation_refresh",
                        "status": "running", "progress": current, "total": total,
                        "description": desc or "AI Recommendations",
                    })

                result = await _refresh(db, limit=req.limit, use_claude=req.use_claude, on_progress=on_progress)
                job.status = "completed"
                job.result = json.dumps(result)
            except Exception as e:
                job.status = "failed"
                job.result = json.dumps({"error": str(e)})
            finally:
                job.finished_at = datetime.utcnow()
                await db.merge(job)
                await db.commit()
                await broadcast_job_update({
                    "id": job_id, "type": "recommendation_refresh",
                    "status": job.status, "progress": total_steps, "total": total_steps,
                    "description": "AI Recommendations",
                })

    background_tasks.add_task(do_refresh)
    return {"ok": True, "job_id": job_id}


class FeedbackRequest(BaseModel):
    recommendation_id: str
    action: str  # thumbs_up, thumbs_down, download, dismiss


@router.post("/feedback")
async def submit_feedback(req: FeedbackRequest, db: AsyncSession = Depends(get_db)):
    """Submit feedback on a recommendation."""
    rec = await db.get(Recommendation, req.recommendation_id)
    if not rec:
        return {"error": "Recommendation not found"}

    if req.action == "thumbs_up":
        rec.feedback = "thumbs_up"
        rec.status = "accepted"
    elif req.action == "thumbs_down":
        rec.feedback = "thumbs_down"
        rec.status = "rejected"
    elif req.action == "download":
        rec.status = "downloaded"
    elif req.action == "dismiss":
        rec.status = "expired"

    await db.commit()
    return {"ok": True}


@router.get("/stats")
async def recommendation_stats(db: AsyncSession = Depends(get_db)):
    """Get recommendation conversion stats."""
    total = (await db.execute(select(func.count(Recommendation.id)))).scalar() or 0
    downloaded = (await db.execute(
        select(func.count(Recommendation.id)).where(Recommendation.status == "downloaded")
    )).scalar() or 0
    thumbs_up = (await db.execute(
        select(func.count(Recommendation.id)).where(Recommendation.feedback == "thumbs_up")
    )).scalar() or 0
    thumbs_down = (await db.execute(
        select(func.count(Recommendation.id)).where(Recommendation.feedback == "thumbs_down")
    )).scalar() or 0

    # By source breakdown
    source_result = await db.execute(
        select(Recommendation.source, func.count(Recommendation.id))
        .group_by(Recommendation.source)
    )
    by_source = {src: cnt for src, cnt in source_result.all() if src}

    # Downloads by source
    dl_source_result = await db.execute(
        select(Recommendation.source, func.count(Recommendation.id))
        .where(Recommendation.status == "downloaded")
        .group_by(Recommendation.source)
    )
    downloads_by_source = {src: cnt for src, cnt in dl_source_result.all() if src}

    return {
        "total": total,
        "downloaded": downloaded,
        "thumbs_up": thumbs_up,
        "thumbs_down": thumbs_down,
        "pending": total - downloaded - thumbs_down,
        "by_source": by_source,
        "downloads_by_source": downloads_by_source,
    }


class BulkDownloadRequest(BaseModel):
    mode: str = "top"  # "top" or "above_score"
    count: int = 20
    min_score: float = 0.7


@router.post("/bulk-download")
async def bulk_download_recs(req: BulkDownloadRequest, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """Download multiple recommendations as individual download jobs."""
    from backend.api.download import enqueue_download

    query = select(Recommendation).where(Recommendation.status == "pending")
    if req.mode == "above_score":
        query = query.where(Recommendation.score >= req.min_score)
    query = query.order_by(Recommendation.score.desc())
    if req.mode == "top":
        query = query.limit(req.count)

    result = await db.execute(query)
    recs = result.scalars().all()

    if not recs:
        return {"ok": False, "error": "No pending recommendations to download"}

    # Mark as downloaded immediately
    for r in recs:
        r.status = "downloaded"
    await db.commit()

    for r in recs:
        background_tasks.add_task(enqueue_download, r.artist, r.track)

    return {"ok": True, "count": len(recs)}


@router.get("/profile")
async def get_profile(db: AsyncSession = Depends(get_db)):
    """Get the current taste profile summary."""
    tp = await db.get(TasteProfile, "default")
    if not tp:
        return {
            "exists": False,
            "message": "No taste profile yet. Run a recommendation refresh to build one.",
        }

    try:
        profile_data = json.loads(tp.profile_data)
    except Exception:
        profile_data = {}

    from backend.config import get_settings
    settings = get_settings()

    return {
        "exists": True,
        "computed_at": tp.computed_at.isoformat() if tp.computed_at else None,
        "track_count": tp.track_count,
        "favorite_count": tp.favorite_count,
        "analyzed_count": tp.analyzed_count,
        "has_clap_centroid": tp.clap_centroid is not None,
        "has_claude_key": bool(settings.assistant.claude_api_key),
        "genre_distribution": profile_data.get("genre_distribution", {}),
        "top_artists": profile_data.get("top_artists", []),
        "favorite_artists": profile_data.get("favorite_artists", []),
        "audio": profile_data.get("audio", {}),
    }
