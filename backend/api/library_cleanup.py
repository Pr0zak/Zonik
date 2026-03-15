"""Library cleanup & organization endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.track import Track

router = APIRouter()


@router.post("/cleanup/orphans/preview")
async def preview_orphans(db: AsyncSession = Depends(get_db)):
    """Preview orphaned tracks (files missing from disk)."""
    from backend.services.cleanup import find_orphaned_tracks
    orphans = await find_orphaned_tracks(db)
    return {"orphans": orphans, "count": len(orphans)}


@router.post("/cleanup/orphans")
async def remove_orphans(db: AsyncSession = Depends(get_db)):
    """Remove orphaned tracks from database."""
    from backend.services.cleanup import remove_orphaned_tracks
    return await remove_orphaned_tracks(db)


@router.get("/duplicates")
async def get_duplicates(db: AsyncSession = Depends(get_db)):
    """Get enriched duplicate groups for the duplicates management page."""
    from backend.services.cleanup import find_duplicates_enriched
    return await find_duplicates_enriched(db)


@router.get("/duplicates/artists")
async def get_duplicate_artist_ids(db: AsyncSession = Depends(get_db)):
    """Get artist IDs that have duplicate tracks (lightweight, for map overlay)."""
    result = await db.execute(
        select(Track.artist_id)
        .where(Track.artist_id.isnot(None))
        .group_by(func.lower(Track.title), Track.artist_id)
        .having(func.count(Track.id) > 1)
    )
    artist_ids = list({r[0] for r in result.all()})
    return {"artist_ids": artist_ids, "count": len(artist_ids)}


@router.post("/duplicates/ai-resolve")
async def ai_resolve_duplicates(db: AsyncSession = Depends(get_db)):
    """Get AI recommendations for which duplicates to keep."""
    from backend.services.cleanup import find_duplicates_enriched
    from backend.services.ai.duplicate_resolver import resolve_duplicates

    result = await find_duplicates_enriched(db)
    groups = result.get("groups", [])
    if not groups:
        return {"recommendations": [], "message": "No duplicates found"}

    return await resolve_duplicates(groups)


@router.post("/cleanup/duplicates/preview")
async def preview_duplicates(db: AsyncSession = Depends(get_db)):
    """Preview duplicate tracks."""
    from backend.services.cleanup import find_duplicates
    groups = await find_duplicates(db)
    total_dupes = sum(len(g["remove"]) for g in groups)
    return {"groups": groups, "total_groups": len(groups), "total_duplicates": total_dupes}


class RemoveDupesRequest(BaseModel):
    remove_ids: list[str]
    delete_files: bool = False


@router.post("/cleanup/duplicates")
async def remove_dupes(
    request: RemoveDupesRequest,
    db: AsyncSession = Depends(get_db),
):
    """Remove specified duplicate tracks."""
    from backend.services.cleanup import remove_duplicates
    if not request.remove_ids:
        return {"error": "No track IDs provided"}
    return await remove_duplicates(db, request.remove_ids, request.delete_files)


@router.post("/cleanup/organize/preview")
async def preview_organize_files(db: AsyncSession = Depends(get_db)):
    """Preview file rename/sort operations."""
    from backend.services.cleanup import preview_organize
    moves = await preview_organize(db)
    return {"moves": moves, "count": len(moves)}


class OrganizeRequest(BaseModel):
    move_ids: list[str] | None = None


@router.post("/cleanup/organize")
async def organize_files(
    request: OrganizeRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Execute file rename/sort. Optional body: {move_ids: [...]}"""
    from backend.services.cleanup import execute_organize
    move_ids = request.move_ids if request else None
    return await execute_organize(db, move_ids)


@router.post("/upgrades/scan")
async def scan_upgradeable_tracks(
    request: dict | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Find tracks that could be upgraded to better quality.

    Body options:
      mode: 'lossy_to_lossless' | 'low_bitrate' | 'all_lossy' | 'opus_to_flac'
      max_bitrate: int (for low_bitrate mode, default 256)
      limit: int (default 100)
    """
    from sqlalchemy.orm import selectinload

    mode = (request or {}).get("mode", "low_bitrate")
    max_bitrate = (request or {}).get("max_bitrate", 256)
    limit_count = (request or {}).get("limit", 100)

    query = select(Track).options(
        selectinload(Track.artist), selectinload(Track.album)
    )

    lossy_formats = ["mp3", "m4a", "ogg", "opus", "aac", "wma"]

    if mode == "opus_to_flac":
        query = query.where(Track.format == "opus")
    elif mode == "lossy_to_lossless":
        query = query.where(Track.format.in_(lossy_formats))
    elif mode == "low_bitrate":
        query = query.where(
            (Track.bitrate.isnot(None)) & (Track.bitrate < max_bitrate * 1000)
        )
    elif mode == "all_lossy":
        query = query.where(Track.format.in_(lossy_formats))
    else:
        query = query.where(
            (Track.bitrate.isnot(None)) & (Track.bitrate < max_bitrate * 1000)
        )

    query = query.order_by(Track.bitrate.asc().nullslast()).limit(limit_count)
    result = await db.execute(query)
    tracks = result.scalars().all()

    return {
        "tracks": [
            {
                "id": t.id,
                "title": t.title,
                "artist": t.artist.name if t.artist else "Unknown",
                "album": t.album.title if t.album else None,
                "format": t.format,
                "bitrate": t.bitrate,
                "bit_depth": t.bit_depth,
                "sample_rate": t.sample_rate,
                "file_size": t.file_size,
                "file_path": t.file_path,
            }
            for t in tracks
        ],
        "count": len(tracks),
        "mode": mode,
    }
