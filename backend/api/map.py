"""Music Map API - graph data for library visualization."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db

router = APIRouter()


@router.get("/graph")
async def get_graph(
    max_artists: int = Query(200, le=500),
    min_genre_tracks: int = Query(3, ge=1),
    include_tracks: bool = Query(False),
    max_tracks_per_artist: int = Query(50, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Get graph data for the Music Map visualization."""
    from backend.services.graph_builder import build_graph
    return await build_graph(
        db,
        max_artists=max_artists,
        min_genre_tracks=min_genre_tracks,
        include_tracks=include_tracks,
        max_tracks_per_artist=max_tracks_per_artist,
    )
