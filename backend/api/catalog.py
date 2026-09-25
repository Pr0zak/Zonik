"""Catalog search: tracks from Deezer / Last.fm, marked owned or not."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db

router = APIRouter()


@router.get("/catalog")
async def catalog_search(
    q: str = Query(..., min_length=2),
    limit: int = Query(25, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """Tracks matching q, each with in_library/track_id, and job_id when a
    download of it is already queued or running.

    Returns {tracks, source, error?}. `source` says which catalog answered
    ("deezer", or "lastfm" as the fallback); `error` is set only when both
    were unavailable.
    """
    from backend.api.download import _find_existing_download
    from backend.services.catalog import search_catalog
    from backend.services.library_match import batch_library_match

    result = await search_catalog(q, limit)
    tracks = [dict(t) for t in result["tracks"]]  # the cached list stays clean
    await batch_library_match(db, tracks, name_key="title")
    for t in tracks:
        t["job_id"] = None if t["in_library"] else await _find_existing_download(db, t["artist"], t["title"])
    return {**result, "tracks": tracks}
