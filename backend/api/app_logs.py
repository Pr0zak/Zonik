"""App log upload and viewing API — accepts logs from Symfonium via Subsonic auth."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.app_log import AppLog
from backend.subsonic.auth import authenticate_subsonic

router = APIRouter()


class LogUploadRequest(BaseModel):
    device: str
    app_version: str
    timestamp: str
    logs: str


# --- Upload (Subsonic auth from query params) ---

@router.post("")
async def upload_log(body: LogUploadRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Accept a log upload from Symfonium. Auth via Subsonic query params."""
    user = await authenticate_subsonic(request)

    log_id = str(uuid.uuid4())
    entry = AppLog(
        id=log_id,
        device=body.device,
        app_version=body.app_version,
        timestamp=body.timestamp,
        logs=body.logs,
        username=user.username,
        created_at=datetime.utcnow(),
    )
    db.add(entry)
    await db.commit()
    return {"id": log_id, "message": "ok"}


# --- Web UI endpoints (no auth, same as other /api/ routes) ---

@router.get("/app")
async def list_app_logs(
    offset: int = 0,
    limit: int = 25,
    db: AsyncSession = Depends(get_db),
):
    """List uploaded app logs (newest first), paginated."""
    total = (await db.execute(select(func.count(AppLog.id)))).scalar() or 0
    result = await db.execute(
        select(
            AppLog.id, AppLog.device, AppLog.app_version,
            AppLog.timestamp, AppLog.username, AppLog.created_at,
            func.length(AppLog.logs).label("log_size"),
        )
        .order_by(desc(AppLog.created_at))
        .offset(offset)
        .limit(limit)
    )
    items = [
        {
            "id": r.id,
            "device": r.device,
            "app_version": r.app_version,
            "timestamp": r.timestamp,
            "username": r.username,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "log_size": r.log_size,
        }
        for r in result.all()
    ]
    return {"items": items, "total": total}


@router.get("/app/{log_id}")
async def get_app_log(log_id: str, db: AsyncSession = Depends(get_db)):
    """Get a single app log with full log text."""
    result = await db.execute(select(AppLog).where(AppLog.id == log_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(404, "Log not found")
    return {
        "id": entry.id,
        "device": entry.device,
        "app_version": entry.app_version,
        "timestamp": entry.timestamp,
        "username": entry.username,
        "logs": entry.logs,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
    }


@router.delete("/app/{log_id}")
async def delete_app_log(log_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a single app log."""
    result = await db.execute(select(AppLog).where(AppLog.id == log_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(404, "Log not found")
    await db.delete(entry)
    await db.commit()
    return {"message": "deleted"}
