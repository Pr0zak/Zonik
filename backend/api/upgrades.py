"""Upgrades API routes — track quality upgrade tracking and management."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db, async_session
from backend.models.track import Track
from backend.models.artist import Artist
from backend.models.upgrade import TrackUpgrade

log = logging.getLogger(__name__)

router = APIRouter()

UPGRADE_SORT_COLUMNS = {"created_at", "status", "original_format", "original_bitrate", "reason", "attempts"}


class ScanRequest(BaseModel):
    modes: list[str] = ["low_bitrate"]
    max_bitrate: int = 256
    limit: int = 200


class StartRequest(BaseModel):
    ids: list[str] | None = None  # None = start all pending


class ClearRequest(BaseModel):
    statuses: list[str] = ["completed"]


@router.get("")
async def list_upgrades(
    status: str | None = None,
    reason: str | None = None,
    offset: int = 0,
    limit: int = 25,
    sort: str = "created_at",
    order: str = "desc",
    db: AsyncSession = Depends(get_db),
):
    """List upgrade records with optional status and reason filters."""
    query = select(TrackUpgrade).options(selectinload(TrackUpgrade.track).selectinload(Track.artist))

    if status:
        query = query.where(TrackUpgrade.status == status)
    if reason:
        query = query.where(TrackUpgrade.reason == reason)

    # Count
    count_q = select(func.count(TrackUpgrade.id))
    if status:
        count_q = count_q.where(TrackUpgrade.status == status)
    if reason:
        count_q = count_q.where(TrackUpgrade.reason == reason)
    total = (await db.execute(count_q)).scalar() or 0

    # Sort
    if sort in UPGRADE_SORT_COLUMNS:
        col = getattr(TrackUpgrade, sort)
        query = query.order_by(col.desc() if order == "desc" else col.asc())
    else:
        query = query.order_by(TrackUpgrade.created_at.desc())

    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    upgrades = result.scalars().all()

    return {
        "items": [_serialize(u) for u in upgrades],
        "total": total,
    }


@router.get("/stats")
async def upgrade_stats(db: AsyncSession = Depends(get_db)):
    """Get counts by status and total size delta for completed upgrades."""
    result = await db.execute(
        select(TrackUpgrade.status, func.count(TrackUpgrade.id))
        .group_by(TrackUpgrade.status)
    )
    counts = {row[0]: row[1] for row in result.all()}

    # Size delta for completed
    size_result = await db.execute(
        select(
            func.sum(TrackUpgrade.upgraded_file_size),
            func.sum(TrackUpgrade.original_file_size),
        ).where(TrackUpgrade.status == "completed")
    )
    row = size_result.one()
    new_size = row[0] or 0
    old_size = row[1] or 0

    return {
        "pending": counts.get("pending", 0),
        "queued": counts.get("queued", 0),
        "downloading": counts.get("downloading", 0),
        "completed": counts.get("completed", 0),
        "failed": counts.get("failed", 0),
        "skipped": counts.get("skipped", 0),
        "total": sum(counts.values()),
        "size_delta": new_size - old_size,
    }


@router.post("/scan")
async def scan_upgrades(req: ScanRequest, db: AsyncSession = Depends(get_db)):
    """Scan library and create TrackUpgrade records for tracks needing upgrades."""
    lossy_formats = ["mp3", "m4a", "ogg", "opus", "aac", "wma"]
    all_track_ids: set[str] = set()
    created = 0

    # Get existing pending/queued/downloading upgrade track_ids to skip
    existing = await db.execute(
        select(TrackUpgrade.track_id).where(
            TrackUpgrade.status.in_(["pending", "queued", "downloading"])
        )
    )
    skip_ids = {r[0] for r in existing.all()}

    for mode in req.modes:
        query = select(Track).options(selectinload(Track.artist))

        if mode == "opus_to_flac":
            query = query.where(Track.format == "opus")
        elif mode == "lossy_to_lossless":
            query = query.where(Track.format.in_(lossy_formats))
        elif mode == "all_lossy":
            query = query.where(Track.format.in_(lossy_formats))
        else:  # low_bitrate
            query = query.where(
                (Track.bitrate.isnot(None)) & (Track.bitrate < req.max_bitrate * 1000)
            )

        query = query.order_by(Track.bitrate.asc().nullslast()).limit(req.limit)
        result = await db.execute(query)
        tracks = result.scalars().all()

        for t in tracks:
            if t.id in skip_ids or t.id in all_track_ids:
                continue
            all_track_ids.add(t.id)
            db.add(TrackUpgrade(
                id=str(uuid.uuid4()),
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
            created += 1

    await db.commit()
    return {"created": created, "skipped": len(skip_ids)}


@router.post("/start")
async def start_upgrades(req: StartRequest, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """Start downloading upgrades (selected or all pending)."""
    query = select(TrackUpgrade).options(
        selectinload(TrackUpgrade.track).selectinload(Track.artist)
    ).where(TrackUpgrade.status == "pending")

    if req.ids:
        query = query.where(TrackUpgrade.id.in_(req.ids))

    result = await db.execute(query)
    upgrades = result.scalars().all()

    started = 0
    for u in upgrades:
        if u.attempts >= u.max_attempts:
            continue
        artist_name = u.track.artist.name if u.track and u.track.artist else "Unknown"
        track_title = u.track.title if u.track else "Unknown"
        u.status = "queued"
        u.attempts += 1
        u.updated_at = datetime.utcnow()
        started += 1

        # Capture values for background task
        upgrade_id = u.id
        background_tasks.add_task(_download_upgrade, upgrade_id, artist_name, track_title)

    await db.commit()
    return {"started": started}


async def _download_upgrade(upgrade_id: str, artist: str, track: str):
    """Download an upgrade and link the job_id back."""
    from backend.api.download import enqueue_download
    job_id = await enqueue_download(artist, track)
    async with async_session() as db:
        result = await db.execute(
            select(TrackUpgrade).where(TrackUpgrade.id == upgrade_id)
        )
        u = result.scalar_one_or_none()
        if u:
            u.job_id = job_id
            u.status = "downloading"
            u.updated_at = datetime.utcnow()
            await db.commit()


@router.post("/{upgrade_id}/retry")
async def retry_upgrade(upgrade_id: str, db: AsyncSession = Depends(get_db)):
    """Reset a failed upgrade back to pending."""
    result = await db.execute(
        select(TrackUpgrade).where(TrackUpgrade.id == upgrade_id)
    )
    u = result.scalar_one_or_none()
    if not u:
        return {"error": "Not found"}
    if u.status != "failed":
        return {"error": "Only failed upgrades can be retried"}
    u.status = "pending"
    u.error_message = None
    u.updated_at = datetime.utcnow()
    await db.commit()
    return {"ok": True}


@router.post("/{upgrade_id}/skip")
async def skip_upgrade(upgrade_id: str, db: AsyncSession = Depends(get_db)):
    """Mark an upgrade as skipped."""
    result = await db.execute(
        select(TrackUpgrade).where(TrackUpgrade.id == upgrade_id)
    )
    u = result.scalar_one_or_none()
    if not u:
        return {"error": "Not found"}
    u.status = "skipped"
    u.updated_at = datetime.utcnow()
    await db.commit()
    return {"ok": True}


@router.delete("/clear")
async def clear_upgrades(status: str = "completed", db: AsyncSession = Depends(get_db)):
    """Remove upgrade records by status."""
    allowed = {"completed", "failed", "skipped"}
    if status not in allowed:
        return {"error": f"Can only clear: {', '.join(allowed)}"}
    result = await db.execute(
        delete(TrackUpgrade).where(TrackUpgrade.status == status)
    )
    await db.commit()
    return {"deleted": result.rowcount}


def _serialize(u: TrackUpgrade) -> dict:
    artist_name = u.track_artist or ""
    track_title = u.track_title or ""
    album_id = None
    if u.track:
        track_title = u.track.title or track_title
        album_id = u.track.album_id
        if u.track.artist:
            artist_name = u.track.artist.name or artist_name
    return {
        "id": u.id,
        "track_id": u.track_id,
        "artist": artist_name,
        "title": track_title,
        "album_id": album_id,
        "original_format": u.original_format,
        "original_bitrate": u.original_bitrate,
        "original_file_size": u.original_file_size,
        "target_format": u.target_format,
        "status": u.status,
        "upgraded_format": u.upgraded_format,
        "upgraded_bitrate": u.upgraded_bitrate,
        "upgraded_file_size": u.upgraded_file_size,
        "reason": u.reason,
        "error_message": u.error_message,
        "job_id": u.job_id,
        "attempts": u.attempts,
        "max_attempts": u.max_attempts,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "updated_at": u.updated_at.isoformat() if u.updated_at else None,
        "completed_at": u.completed_at.isoformat() if u.completed_at else None,
    }
