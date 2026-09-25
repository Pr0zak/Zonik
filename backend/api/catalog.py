"""Catalog search: tracks from Deezer / Last.fm, marked owned or not."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db

router = APIRouter()


async def _annotate(db: AsyncSession, tracks: list[dict]) -> None:
    """in_library/track_id on every track, job_id on the ones not owned."""
    from backend.api.download import _find_existing_download
    from backend.services.library_match import batch_library_match

    await batch_library_match(db, tracks, name_key="title")
    for t in tracks:
        t["job_id"] = None if t["in_library"] else await _find_existing_download(db, t["artist"], t["title"])


@router.get("/catalog")
async def catalog_search(
    q: str = Query(..., min_length=2),
    limit: int = Query(25, ge=1, le=50),
    ai: bool = Query(False, description="Also ask Claude which songs q describes"),
    db: AsyncSession = Depends(get_db),
):
    """Tracks matching q, each with in_library/track_id, and job_id when a
    download of it is already queued or running.

    Returns {tracks, source, error?, ai_tracks?, ai_available}. `source` says
    which catalog answered ("deezer", or "lastfm" as the fallback); `error` is
    set only when both were unavailable. `ai_tracks` holds songs Claude thinks
    q describes ("the song from the Drive soundtrack"), each with a `reason`:
    fetched when ai=true, or on its own when the catalog finds nothing for a
    query of three or more words.
    """
    from backend.services.ai import track_resolver
    from backend.services.catalog import search_catalog

    result = await search_catalog(q, limit)
    tracks = [dict(t) for t in result["tracks"]]  # the cached list stays clean
    await _annotate(db, tracks)
    out = {**result, "tracks": tracks, "ai_available": track_resolver.enabled()}

    wants_ai = ai or (not tracks and len(q.split()) >= 3)
    if wants_ai and track_resolver.enabled():
        ai_tracks = await track_resolver.resolve(q)
        await _annotate(db, ai_tracks)
        out["ai_tracks"] = ai_tracks
    return out
