"""WebSocket endpoint for real-time job progress."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from backend.database import async_session
from backend.models.job import Job

router = APIRouter()

# Connected clients
_clients: set[WebSocket] = set()


async def broadcast_job_update(job_data: dict):
    """Broadcast a job update to all connected WebSocket clients."""
    message = json.dumps({"type": "job_update", "job": job_data})
    disconnected = set()
    for ws in _clients:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.add(ws)
    _clients.difference_update(disconnected)


async def broadcast_log(log_data: dict):
    """Broadcast a log entry to all connected WebSocket clients."""
    message = json.dumps({"type": "log_entry", "entry": log_data})
    disconnected = set()
    for ws in _clients:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.add(ws)
    _clients.difference_update(disconnected)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    _clients.add(websocket)
    try:
        # Send current active jobs on connect
        async with async_session() as db:
            result = await db.execute(
                select(Job).where(Job.status.in_(["pending", "running"]))
            )
            active_jobs = result.scalars().all()
            for job in active_jobs:
                await websocket.send_text(json.dumps({
                    "type": "job_update",
                    "job": {
                        "id": job.id,
                        "type": job.type,
                        "status": job.status,
                        "progress": job.progress,
                        "total": job.total,
                    }
                }))

        # Keep connection alive
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                # Send ping to keep alive
                await websocket.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(websocket)
