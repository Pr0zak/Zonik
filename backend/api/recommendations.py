"""Recommendations API — AI Music Assistant endpoints."""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, BackgroundTasks, Request
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.helpers import paginate
from backend.database import get_db, async_session
from backend.models.recommendation import Recommendation
from backend.models.taste_profile import TasteProfile
from backend.services.user_data import caller, caller_id

router = APIRouter()


def _mine(user_id: str | None):
    """The caller's recommendations (multi-user P2). Rows without a user (only left where
    the migration found no owner) are shown to everyone."""
    if not user_id:
        return Recommendation.user_id.is_(None)
    return (Recommendation.user_id == user_id) | Recommendation.user_id.is_(None)


async def _profile(db: AsyncSession, user_id: str | None) -> TasteProfile | None:
    return await db.get(TasteProfile, user_id or "default")


async def _own_rec(db: AsyncSession, request: Request, rec_id: str) -> Recommendation | None:
    """A recommendation the caller may act on: their own, or any for an admin."""
    rec = await db.get(Recommendation, rec_id)
    if rec is None:
        return None
    user = caller(request)
    if user is None or user.role == "admin" or rec.user_id in (None, user.id):
        return rec
    return None


@router.get("")
async def list_recommendations(
    request: Request,
    limit: int = 25,
    offset: int = 0,
    status: str | None = None,
    source: str | None = None,
    min_score: float = 0.0,
    db: AsyncSession = Depends(get_db),
):
    """Get the caller's recommendations, paginated and sorted by score."""
    user_id = await caller_id(request, db)
    query = select(Recommendation).where(Recommendation.score >= min_score, _mine(user_id))

    if status:
        query = query.where(Recommendation.status == status)
    else:
        query = query.where(Recommendation.status == "pending")

    if source:
        query = query.where(Recommendation.source == source)

    query = query.order_by(Recommendation.score.desc())
    page = await paginate(db, query, offset, limit)
    total = page["total"]
    recs = page["items"]

    # Load profile stats
    tp = await _profile(db, user_id)
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
async def refresh_recommendations(req: RefreshRequest, background_tasks: BackgroundTasks,
                                  request: Request, db: AsyncSession = Depends(get_db)):
    """Trigger a refresh of the caller's recommendations (background job)."""
    import uuid
    from backend.models.job import Job
    from backend.api.websocket import broadcast_job_update

    job_id = str(uuid.uuid4())
    user_id = await caller_id(request, db)

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
                    # Use separate session to avoid concurrent ops on the main db session
                    async with async_session() as progress_db:
                        from sqlalchemy import update
                        await progress_db.execute(
                            update(Job).where(Job.id == job_id).values(
                                progress=current, total=total,
                            )
                        )
                        await progress_db.commit()
                    await broadcast_job_update({
                        "id": job_id, "type": "recommendation_refresh",
                        "status": "running", "progress": current, "total": total,
                        "description": desc or "AI Recommendations",
                    })

                result = await _refresh(db, limit=req.limit, use_claude=req.use_claude, on_progress=on_progress,
                                        user_id=user_id)
                job.status = "completed"
                job.result = json.dumps(result)
            except Exception as e:
                job.status = "failed"
                job.result = json.dumps({"error": str(e)})
            finally:
                job.finished_at = datetime.utcnow()
                await db.commit()
                # Final status update with separate session to be safe
                async with async_session() as final_db:
                    from sqlalchemy import update
                    await final_db.execute(
                        update(Job).where(Job.id == job_id).values(
                            status=job.status, result=job.result,
                            finished_at=job.finished_at,
                        )
                    )
                    await final_db.commit()
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
async def submit_feedback(req: FeedbackRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Submit feedback on one of the caller's recommendations."""
    rec = await _own_rec(db, request, req.recommendation_id)
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
async def recommendation_stats(request: Request, db: AsyncSession = Depends(get_db)):
    """The caller's recommendation conversion stats."""
    mine = _mine(await caller_id(request, db))
    total = (await db.execute(select(func.count(Recommendation.id)).where(mine))).scalar() or 0
    downloaded = (await db.execute(
        select(func.count(Recommendation.id)).where(mine, Recommendation.status == "downloaded")
    )).scalar() or 0
    thumbs_up = (await db.execute(
        select(func.count(Recommendation.id)).where(mine, Recommendation.feedback == "thumbs_up")
    )).scalar() or 0
    thumbs_down = (await db.execute(
        select(func.count(Recommendation.id)).where(mine, Recommendation.feedback == "thumbs_down")
    )).scalar() or 0
    # Count pending and failed directly. The old "total - downloaded - thumbs_down"
    # subtraction lumped accepted, rejected, expired and (since the scheduler stopped
    # marking failed downloads as downloaded) failed rows in with pending.
    pending = (await db.execute(
        select(func.count(Recommendation.id)).where(mine, Recommendation.status == "pending")
    )).scalar() or 0
    failed = (await db.execute(
        select(func.count(Recommendation.id)).where(mine, Recommendation.status == "failed")
    )).scalar() or 0

    # By source breakdown
    source_result = await db.execute(
        select(Recommendation.source, func.count(Recommendation.id))
        .where(mine)
        .group_by(Recommendation.source)
    )
    by_source = {src: cnt for src, cnt in source_result.all() if src}

    # Downloads by source
    dl_source_result = await db.execute(
        select(Recommendation.source, func.count(Recommendation.id))
        .where(mine, Recommendation.status == "downloaded")
        .group_by(Recommendation.source)
    )
    downloads_by_source = {src: cnt for src, cnt in dl_source_result.all() if src}

    return {
        "total": total,
        "downloaded": downloaded,
        "thumbs_up": thumbs_up,
        "thumbs_down": thumbs_down,
        "pending": pending,
        "failed": failed,
        "by_source": by_source,
        "downloads_by_source": downloads_by_source,
    }


class BulkDownloadRequest(BaseModel):
    mode: str = "top"  # "top" or "above_score"
    count: int = 20
    min_score: float = 0.7


@router.post("/bulk-download")
async def bulk_download_recs(req: BulkDownloadRequest, background_tasks: BackgroundTasks, request: Request,
                             db: AsyncSession = Depends(get_db)):
    """Download several of the caller's recommendations through the tracked path. Each
    rec's status follows its own outcome once its download ends (see _download_recs).
    The downloads themselves are ordinary global jobs, tagged with the caller as origin."""
    user = caller(request)
    query = select(Recommendation).where(Recommendation.status == "pending",
                                         _mine(await caller_id(request, db)))
    if req.mode == "above_score":
        query = query.where(Recommendation.score >= req.min_score)
    query = query.order_by(Recommendation.score.desc())
    if req.mode == "top":
        query = query.limit(req.count)

    result = await db.execute(query)
    recs = result.scalars().all()

    if not recs:
        return {"ok": False, "error": "No pending recommendations to download"}

    origin = f"recommendations:{user.username}" if user is not None else None
    background_tasks.add_task(_download_recs, [r.id for r in recs], origin)
    return {"ok": True, "count": len(recs)}


async def _download_recs(rec_ids: list[str], origin: str | None = None) -> None:
    """Download the given recs (backoff, duration gate, outcome recorded), then set
    each one's status the way the scheduled auto-download does: "downloaded" on
    success, "failed" (error kept on source_detail) on failure, left pending when
    the outcome is unknown or the track was skipped for backoff."""
    from backend.services.auto_download import download_tracked_many
    from backend.services.download_attempts import attempt_key

    async with async_session() as db:
        recs = (await db.execute(select(Recommendation).where(Recommendation.id.in_(rec_ids)))).scalars().all()
        items = [{"artist": r.artist, "track": r.track} for r in recs]

    outcomes = await download_tracked_many(items, source="recommendation", label="Recommendations",
                                           kind="recommendation", origin=origin)
    by_key = {attempt_key(o["artist"], o["track"]): o for o in outcomes}

    async with async_session() as db:
        recs = (await db.execute(select(Recommendation).where(Recommendation.id.in_(rec_ids)))).scalars().all()
        for r in recs:
            o = by_key.get(attempt_key(r.artist, r.track))
            if o is None or o["ok"] is None or r.status != "pending":
                continue
            if o["ok"]:
                r.status = "downloaded"
            else:
                r.status = "failed"
                r.source_detail = ((r.source_detail or "") + f" | download failed: {o['error'] or 'unknown'}")[:2000]
        await db.commit()


@router.post("/{rec_id}/explain")
async def explain(rec_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Get AI explanation for why a track was recommended (against the caller's taste)."""
    rec = await _own_rec(db, request, rec_id)
    if not rec:
        return {"error": "Recommendation not found"}

    # Get taste profile for context: the profile the rec was made for
    tp = await _profile(db, rec.user_id or await caller_id(request, db))
    profile_summary = {}
    if tp:
        try:
            profile_summary = json.loads(tp.profile_data)
        except Exception:
            pass

    from backend.services.ai.explainer import explain_recommendation
    result = await explain_recommendation(
        track_artist=rec.artist,
        track_title=rec.track,
        score=rec.score,
        source=rec.source,
        profile_summary=profile_summary,
    )
    return result


@router.get("/profile")
async def get_profile(request: Request, db: AsyncSession = Depends(get_db)):
    """The caller's taste profile summary."""
    tp = await _profile(db, await caller_id(request, db))
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
