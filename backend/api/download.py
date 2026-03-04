from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.post("/search")
async def search_soulseek(query: str):
    """Search Soulseek for tracks (Phase 2)."""
    return {"status": "not_implemented", "message": "Soulseek search coming in Phase 2"}


@router.post("/trigger")
async def trigger_download(query: str):
    """Trigger a download (Phase 2)."""
    return {"status": "not_implemented", "message": "Downloads coming in Phase 2"}
