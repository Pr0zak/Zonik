"""Library cleanup services: orphan removal, deduplication, file organization."""
from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
from pathlib import Path

from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.config import get_settings
from backend.models.track import Track
from backend.models.artist import Artist
from backend.models.album import Album

log = logging.getLogger(__name__)


# --- Orphan Cleanup ---

async def find_orphaned_tracks(db: AsyncSession) -> list[dict]:
    """Find DB tracks whose files no longer exist on disk."""
    settings = get_settings()
    music_dir = Path(settings.library.music_dir)
    result = await db.execute(select(Track.id, Track.title, Track.file_path))
    orphans = []
    for track_id, title, file_path in result.all():
        full_path = music_dir / file_path
        if not full_path.exists():
            orphans.append({"id": track_id, "title": title, "file_path": file_path})
    return orphans


async def remove_orphaned_tracks(db: AsyncSession) -> dict:
    """Remove DB entries for tracks whose files no longer exist."""
    orphans = await find_orphaned_tracks(db)
    if not orphans:
        return {"removed": 0}

    orphan_ids = [o["id"] for o in orphans]

    # Delete related records first
    from backend.models.favorite import Favorite
    from backend.models.playlist import PlaylistTrack
    await db.execute(delete(Favorite).where(Favorite.track_id.in_(orphan_ids)))
    await db.execute(delete(PlaylistTrack).where(PlaylistTrack.track_id.in_(orphan_ids)))

    # Delete FTS entries
    from backend.database import engine
    from sqlalchemy import text
    async with engine.begin() as conn:
        for tid in orphan_ids:
            await conn.execute(text("DELETE FROM tracks_fts WHERE rowid IN (SELECT rowid FROM tracks_fts WHERE tracks_fts MATCH :tid)"), {"tid": tid})

    # Delete tracks
    await db.execute(delete(Track).where(Track.id.in_(orphan_ids)))

    # Clean up empty albums and artists
    empty_albums = (await db.execute(
        select(Album.id).outerjoin(Track, Track.album_id == Album.id)
        .group_by(Album.id).having(func.count(Track.id) == 0)
    )).scalars().all()
    if empty_albums:
        await db.execute(delete(Album).where(Album.id.in_(empty_albums)))

    empty_artists = (await db.execute(
        select(Artist.id).outerjoin(Track, Track.artist_id == Artist.id)
        .group_by(Artist.id).having(func.count(Track.id) == 0)
    )).scalars().all()
    if empty_artists:
        await db.execute(delete(Artist).where(Artist.id.in_(empty_artists)))

    await db.commit()
    return {"removed": len(orphan_ids), "albums_cleaned": len(empty_albums), "artists_cleaned": len(empty_artists)}


# --- Deduplication ---

# Quality ranking for formats (higher = better)
FORMAT_QUALITY = {"flac": 100, "wav": 90, "opus": 70, "ogg": 60, "m4a": 55, "mp3": 50, "aac": 45, "wma": 30}


def _track_quality_score(track: Track) -> int:
    """Score a track's quality for dedup comparison. Higher = better."""
    score = FORMAT_QUALITY.get(track.format or "", 0)
    score += (track.bitrate or 0) // 10
    score += (track.bit_depth or 0)
    # Prefer tracks with more metadata
    if track.genre:
        score += 5
    if track.year:
        score += 5
    if track.cover_art_path:
        score += 5
    if track.musicbrainz_id:
        score += 10
    return score


async def find_duplicates(db: AsyncSession) -> list[dict]:
    """Find duplicate tracks (same title + artist, case-insensitive)."""
    # Find title+artist combinations with multiple tracks
    result = await db.execute(
        select(
            func.lower(Track.title),
            Track.artist_id,
            func.count(Track.id),
        )
        .where(Track.artist_id.isnot(None))
        .group_by(func.lower(Track.title), Track.artist_id)
        .having(func.count(Track.id) > 1)
    )
    dupe_groups = result.all()
    if not dupe_groups:
        return []

    groups = []
    for title_lower, artist_id, count in dupe_groups:
        tracks_result = await db.execute(
            select(Track).options(selectinload(Track.artist), selectinload(Track.album))
            .where(func.lower(Track.title) == title_lower, Track.artist_id == artist_id)
            .order_by(Track.bitrate.desc().nullslast())
        )
        tracks = tracks_result.scalars().all()
        if len(tracks) < 2:
            continue

        # Score each track, best first
        scored = sorted(tracks, key=_track_quality_score, reverse=True)
        keep = scored[0]
        remove = scored[1:]

        groups.append({
            "title": keep.title,
            "artist": keep.artist.name if keep.artist else "Unknown",
            "count": len(tracks),
            "keep": {
                "id": keep.id,
                "file_path": keep.file_path,
                "format": keep.format,
                "bitrate": keep.bitrate,
                "file_size": keep.file_size,
                "quality_score": _track_quality_score(keep),
            },
            "remove": [
                {
                    "id": t.id,
                    "file_path": t.file_path,
                    "format": t.format,
                    "bitrate": t.bitrate,
                    "file_size": t.file_size,
                    "quality_score": _track_quality_score(t),
                }
                for t in remove
            ],
        })

    return groups


async def find_duplicates_enriched(db: AsyncSession) -> dict:
    """Find duplicate tracks with full track details for the duplicates page."""
    from backend.models.favorite import Favorite

    # Find title+artist combinations with multiple tracks
    result = await db.execute(
        select(
            func.lower(Track.title),
            Track.artist_id,
            func.count(Track.id),
        )
        .where(Track.artist_id.isnot(None))
        .group_by(func.lower(Track.title), Track.artist_id)
        .having(func.count(Track.id) > 1)
    )
    dupe_groups = result.all()
    if not dupe_groups:
        return {"groups": [], "total_groups": 0, "total_duplicates": 0, "reclaimable_bytes": 0}

    # Get favorite track IDs
    fav_result = await db.execute(
        select(Favorite.track_id).where(Favorite.track_id.isnot(None))
    )
    fav_track_ids = {r[0] for r in fav_result.all()}

    groups = []
    total_dupes = 0
    reclaimable = 0

    for title_lower, artist_id, count in dupe_groups:
        tracks_result = await db.execute(
            select(Track).options(selectinload(Track.artist), selectinload(Track.album))
            .where(func.lower(Track.title) == title_lower, Track.artist_id == artist_id)
            .order_by(Track.bitrate.desc().nullslast())
        )
        tracks = tracks_result.scalars().all()
        if len(tracks) < 2:
            continue

        scored = sorted(tracks, key=_track_quality_score, reverse=True)

        def _track_detail(t, is_best=False):
            return {
                "id": t.id,
                "title": t.title,
                "artist": t.artist.name if t.artist else "Unknown",
                "album": t.album.title if t.album else None,
                "album_id": t.album_id,
                "format": t.format,
                "bitrate": t.bitrate,
                "bit_depth": t.bit_depth,
                "sample_rate": t.sample_rate,
                "file_size": t.file_size,
                "file_path": t.file_path,
                "quality_score": _track_quality_score(t),
                "play_count": t.play_count or 0,
                "rating": t.rating,
                "is_favorite": t.id in fav_track_ids,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "is_best": is_best,
            }

        best = scored[0]
        worst = scored[-1]
        others = scored[1:]
        total_dupes += len(others)
        for t in others:
            reclaimable += t.file_size or 0

        groups.append({
            "title": best.title,
            "artist": best.artist.name if best.artist else "Unknown",
            "artist_id": artist_id,
            "count": len(tracks),
            "best_format": best.format,
            "best_bitrate": best.bitrate,
            "worst_format": worst.format,
            "worst_bitrate": worst.bitrate,
            "tracks": [_track_detail(best, is_best=True)] + [_track_detail(t) for t in others],
        })

    # Sort by group size descending
    groups.sort(key=lambda g: g["count"], reverse=True)

    return {
        "groups": groups,
        "total_groups": len(groups),
        "total_duplicates": total_dupes,
        "reclaimable_bytes": reclaimable,
    }


async def remove_duplicates(db: AsyncSession, remove_ids: list[str], delete_files: bool = False) -> dict:
    """Remove specified duplicate tracks."""
    settings = get_settings()
    music_dir = Path(settings.library.music_dir)

    # Verify all IDs exist
    result = await db.execute(select(Track).where(Track.id.in_(remove_ids)))
    tracks = result.scalars().all()
    if not tracks:
        return {"removed": 0}

    # Delete related records
    from backend.models.favorite import Favorite
    from backend.models.playlist import PlaylistTrack
    await db.execute(delete(Favorite).where(Favorite.track_id.in_(remove_ids)))
    await db.execute(delete(PlaylistTrack).where(PlaylistTrack.track_id.in_(remove_ids)))
    await db.execute(delete(Track).where(Track.id.in_(remove_ids)))

    files_deleted = 0
    if delete_files:
        for track in tracks:
            full_path = music_dir / track.file_path
            if full_path.exists():
                try:
                    full_path.unlink()
                    files_deleted += 1
                except OSError as e:
                    log.warning(f"Failed to delete {full_path}: {e}")

    await db.commit()
    return {"removed": len(tracks), "files_deleted": files_deleted}


# --- File Organization (Rename & Sort) ---

def _sanitize_filename(name: str) -> str:
    """Sanitize a string for use as a filename."""
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = name.strip('. ')
    return name or "Unknown"


def _build_target_path(track: Track, scheme: str) -> str:
    """Build target file path from naming scheme template."""
    artist_name = _sanitize_filename(track.artist.name if track.artist else "Unknown Artist")
    album_title = _sanitize_filename(track.album.title if track.album else "Unknown Album")
    track_num = f"{track.track_number:02d}" if track.track_number else ""
    title = _sanitize_filename(track.title or "Unknown")
    ext = Path(track.file_path).suffix

    path = scheme.format(
        artist=artist_name,
        album=album_title,
        track_number=track_num,
        title=title,
    )
    # Clean up empty segments from missing track_number (e.g. " - Title" -> "Title")
    path = re.sub(r'(?:^|/)[ -]+', lambda m: m.group().rsplit('/', 1)[0] + '/' if '/' in m.group() else '', path)
    # Sanitize each path segment
    parts = [_sanitize_filename(p) for p in path.split('/') if p.strip()]
    return '/'.join(parts) + ext


async def preview_organize(db: AsyncSession) -> list[dict]:
    """Preview what file renames/moves would happen."""
    settings = get_settings()
    music_dir = Path(settings.library.music_dir)
    scheme = settings.library.naming_scheme

    result = await db.execute(
        select(Track).options(selectinload(Track.artist), selectinload(Track.album))
    )
    tracks = result.scalars().all()

    moves = []
    for track in tracks:
        current_path = track.file_path
        target_path = _build_target_path(track, scheme)

        if current_path != target_path:
            artist_name = track.artist.name if track.artist else "Unknown Artist"
            moves.append({
                "track_id": track.id,
                "title": track.title,
                "artist": artist_name,
                "current_path": current_path,
                "target_path": target_path,
                "exists": (music_dir / target_path).exists(),
            })

    return moves


async def execute_organize(db: AsyncSession, move_ids: list[str] | None = None) -> dict:
    """Rename and sort files into Artist/Album/Track structure."""
    settings = get_settings()
    music_dir = Path(settings.library.music_dir)
    scheme = settings.library.naming_scheme

    query = select(Track).options(selectinload(Track.artist), selectinload(Track.album))
    if move_ids:
        query = query.where(Track.id.in_(move_ids))
    result = await db.execute(query)
    tracks = result.scalars().all()

    moved = 0
    errors = 0
    for track in tracks:
        current_path = track.file_path
        target_path = _build_target_path(track, scheme)

        if current_path == target_path:
            continue

        src = music_dir / current_path
        dst = music_dir / target_path

        if not src.exists():
            errors += 1
            continue

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))

            # Update DB: file_path and track ID (MD5 of path)
            new_id = hashlib.md5(target_path.encode()).hexdigest()
            track.file_path = target_path
            track.id = new_id
            moved += 1

            # Clean up empty source directories
            src_dir = src.parent
            while src_dir != music_dir:
                try:
                    if not any(src_dir.iterdir()):
                        src_dir.rmdir()
                        src_dir = src_dir.parent
                    else:
                        break
                except OSError:
                    break

        except Exception as e:
            log.error(f"Failed to move {current_path} -> {target_path}: {e}")
            errors += 1

    await db.commit()

    # Update FTS index for moved tracks
    from backend.database import update_fts_index
    for track in tracks:
        if track.file_path != current_path:
            await update_fts_index(
                db, track.id, track.title,
                track.artist.name if track.artist else None,
                track.album.title if track.album else None,
            )
    await db.commit()

    return {"moved": moved, "errors": errors}
