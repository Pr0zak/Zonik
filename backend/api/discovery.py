from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/top-tracks")
async def top_tracks():
    """Last.fm top tracks (Phase 2)."""
    return {"status": "not_implemented", "message": "Discovery coming in Phase 2"}


@router.get("/similar")
async def similar_tracks():
    """Similar tracks from favorites (Phase 2)."""
    return {"status": "not_implemented", "message": "Discovery coming in Phase 2"}
