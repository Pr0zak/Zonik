"""Batches API (DC-21): the download runs the web process is working through.

Mounted at /api/download/batches. A batch is one download_tracked_many run that
carries a batch (bulk "Download all", playlist import, recommendations); the
registry lives in backend.services.auto_download, in memory, so only runs started
in this process are listed — the scheduler's batches run in the worker and are
not, and a restart forgets every entry (and the items it had not submitted yet).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.services import auto_download

router = APIRouter()


@router.get("")
async def list_batches():
    """{items: [{id, label, kind, source, total, submitted, done, failed, skipped,
    live, pending, pending_titles (≤10), started_at, finished_at, cancelled}]} —
    running batches first, newest first; a finished one stays listed 10 minutes."""
    return {"items": [b.to_dict() for b in auto_download.list_batches()]}


@router.post("/{batch_id}/cancel")
async def cancel_batch(batch_id: str):
    """Stop submitting the batch's remaining items (they count as skipped);
    downloads already started run to their end. {cancelled: true, remaining: n}."""
    remaining = auto_download.cancel_batch(batch_id)
    if remaining is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    return {"cancelled": True, "remaining": remaining}
