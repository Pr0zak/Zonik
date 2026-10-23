"""WebSocket endpoint for real-time job progress."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from backend.auth.resolve import websocket_allowed
from backend.database import async_session
from backend.models.job import Job

router = APIRouter()

# Connected clients — each WS carries metadata for the Live view.
_clients: dict[WebSocket, dict] = {}


def get_ws_clients() -> list[dict]:
    """Snapshot of connected WS clients, sorted newest-first."""
    out: list[dict] = []
    for meta in _clients.values():
        out.append({
            "client_id": meta.get("client_id"),
            "user_agent": meta.get("user_agent"),
            "ip": meta.get("ip"),
            "connected_at": meta["connected_at"].isoformat() if meta.get("connected_at") else None,
        })
    out.sort(key=lambda m: m.get("connected_at") or "", reverse=True)
    return out


async def broadcast_job_update(job_data: dict):
    """Broadcast a job update to all connected WebSocket clients."""
    message = json.dumps({"type": "job_update", "job": job_data})
    disconnected = []
    for ws in list(_clients.keys()):
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        _clients.pop(ws, None)


async def broadcast_log(log_data: dict):
    """Broadcast a log entry to all connected WebSocket clients."""
    message = json.dumps({"type": "log_entry", "entry": log_data})
    disconnected = []
    for ws in list(_clients.keys()):
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        _clients.pop(ws, None)


async def broadcast_transfer_progress(transfers: list[dict]):
    """Broadcast transfer progress to all connected WebSocket clients."""
    message = json.dumps({"type": "transfer_progress", "transfers": transfers})
    disconnected = []
    for ws in list(_clients.keys()):
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        _clients.pop(ws, None)


async def broadcast_upload_progress(uploads: list[dict]):
    """Broadcast the uploads we are serving to peers. A message type of its own,
    so the download transfer list (transfer_progress) never carries an upload."""
    message = json.dumps({"type": "upload_progress", "uploads": uploads})
    disconnected = []
    for ws in list(_clients.keys()):
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        _clients.pop(ws, None)


def _download_replay_fields(tracks_json: str | None) -> dict:
    """description ("Artist — Track"), stage and stage_since of a download row
    for the on-connect replay, read from its tracks[0] (parsed inline so this
    module doesn't import the jobs/download routers)."""
    try:
        tracks = json.loads(tracks_json) if tracks_json else None
    except (TypeError, ValueError):
        tracks = None
    first = tracks[0] if isinstance(tracks, list) and tracks and isinstance(tracks[0], dict) else {}
    artist, track = first.get("artist") or "", first.get("track") or ""
    out: dict = {"stage": first.get("stage"), "stage_since": first.get("stage_since")}
    if artist or track:
        out["description"] = f"{artist} — {track}" if artist and track else (artist or track)
    return out


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # Same caller resolution as /api (cookie, Bearer, apiKey, Subsonic u/t/s query params).
    # Grace mode lets anonymous sockets in; enforce mode closes them before the handshake.
    if not await websocket_allowed(websocket):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    fwd = websocket.headers.get("x-forwarded-for")
    ip = fwd.split(",")[0].strip() if fwd else (websocket.client.host if websocket.client else None)
    _clients[websocket] = {
        "client_id": str(uuid.uuid4()),
        "user_agent": websocket.headers.get("user-agent"),
        "ip": ip,
        "connected_at": datetime.utcnow(),
    }
    try:
        # Send current active jobs on connect
        async with async_session() as db:
            result = await db.execute(
                select(Job).where(Job.status.in_(["pending", "running"]))
            )
            active_jobs = result.scalars().all()
            for job in active_jobs:
                payload = {
                    "id": job.id,
                    "type": job.type,
                    "status": job.status,
                    "progress": job.progress,
                    "total": job.total,
                    "card": job.card,
                }
                if job.type == "download":
                    payload.update(_download_replay_fields(job.tracks))
                await websocket.send_text(json.dumps({
                    "type": "job_update",
                    "job": payload,
                }))

        # Send current transfers on connect
        try:
            from backend.soulseek import get_client
            client = get_client()
            if client:
                transfers = client.transfers.get_all_transfers()
                if transfers:
                    await websocket.send_text(json.dumps({
                        "type": "transfer_progress",
                        "transfers": transfers,
                    }))
                uploads = client.transfers.get_all_uploads()
                if uploads:
                    await websocket.send_text(json.dumps({
                        "type": "upload_progress",
                        "uploads": uploads,
                    }))
        except Exception:
            pass

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
        _clients.pop(websocket, None)
