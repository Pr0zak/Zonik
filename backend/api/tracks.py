from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks

log = logging.getLogger(__name__)
from pydantic import BaseModel
from sqlalchemy import select, func, delete, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_db, search_fts
from backend.models.track import Track
from backend.models.artist import Artist
from backend.models.album import Album
from backend.models.analysis import TrackAnalysis

router = APIRouter()

TRACK_SORT_COLUMNS = {"title", "artist_id", "album_id", "genre", "year", "format", "bitrate", "duration_seconds", "file_size", "play_count", "rating", "created_at"}


@router.get("")
async def list_tracks(
    offset: int = 0,
    limit: int = 50,
    sort: str = "title",
    order: str = "asc",
    search: str | None = None,
    genre: str | None = None,
    artist_id: str | None = None,
    album_id: str | None = None,
    analyzed: str | None = None,  # "yes", "no", or None (all)
    rating: str | None = None,  # "1", "flagged" (=1), or None (all)
    db: AsyncSession = Depends(get_db),
):
    # Subquery for analyzed track IDs
    analyzed_ids_sq = select(TrackAnalysis.track_id)

    query = select(Track).options(selectinload(Track.artist), selectinload(Track.album))

    # Use FTS5 for search (searches title, artist, album) with ILIKE fallback
    fts_ids = None
    if search:
        fts_ids = await search_fts(db, search, limit=500)
        if fts_ids:
            query = query.where(Track.id.in_(fts_ids))
        else:
            # Fallback: substring match on title, artist name, or album title
            like = f"%{search}%"
            query = query.where(
                Track.title.ilike(like)
                | Track.artist_id.in_(
                    select(Artist.id).where(Artist.name.ilike(like))
                )
            )
    if genre:
        query = query.where(Track.genre == genre)
    if artist_id:
        query = query.where(Track.artist_id == artist_id)
    if album_id:
        query = query.where(Track.album_id == album_id)
    if analyzed == "no":
        query = query.where(Track.id.notin_(analyzed_ids_sq))
    elif analyzed == "yes":
        query = query.where(Track.id.in_(analyzed_ids_sq))
    if rating == "flagged" or rating == "1":
        query = query.where(Track.rating == 1)

    # Sorting
    if sort == "analyzed":
        # Unanalyzed first (NULL analysis = 0, analyzed = 1)
        has_analysis = select(TrackAnalysis.track_id).where(TrackAnalysis.track_id == Track.id).exists()
        if order == "asc":
            query = query.order_by(has_analysis.asc(), Track.title.asc())
        else:
            query = query.order_by(has_analysis.desc(), Track.title.asc())
    else:
        sort_col = getattr(Track, sort) if sort in TRACK_SORT_COLUMNS else Track.title
        query = query.order_by(sort_col.asc() if order == "asc" else sort_col.desc())
    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    tracks = result.scalars().all()

    # Batch-fetch analyzed status for these tracks
    track_ids = [t.id for t in tracks]
    if track_ids:
        analyzed_result = await db.execute(
            select(TrackAnalysis.track_id).where(TrackAnalysis.track_id.in_(track_ids))
        )
        analyzed_set = set(analyzed_result.scalars().all())
    else:
        analyzed_set = set()

    count_q = select(func.count(Track.id))
    if search:
        if fts_ids:
            count_q = count_q.where(Track.id.in_(fts_ids))
        else:
            like = f"%{search}%"
            count_q = count_q.where(
                Track.title.ilike(like)
                | Track.artist_id.in_(
                    select(Artist.id).where(Artist.name.ilike(like))
                )
            )
    if genre:
        count_q = count_q.where(Track.genre == genre)
    if artist_id:
        count_q = count_q.where(Track.artist_id == artist_id)
    if album_id:
        count_q = count_q.where(Track.album_id == album_id)
    if analyzed == "no":
        count_q = count_q.where(Track.id.notin_(analyzed_ids_sq))
    elif analyzed == "yes":
        count_q = count_q.where(Track.id.in_(analyzed_ids_sq))
    if rating == "flagged" or rating == "1":
        count_q = count_q.where(Track.rating == 1)
    total = (await db.execute(count_q)).scalar() or 0

    return {
        "tracks": [
            {
                "id": t.id,
                "title": t.title,
                "artist": t.artist.name if t.artist else None,
                "artist_id": t.artist_id,
                "album": t.album.title if t.album else None,
                "album_id": t.album_id,
                "track_number": t.track_number,
                "duration": t.duration_seconds,
                "format": t.format,
                "bitrate": t.bitrate,
                "genre": t.genre,
                "year": t.year,
                "file_size": t.file_size,
                "play_count": t.play_count,
                "rating": t.rating,
                "cover_art": t.album_id or t.id,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "analyzed": t.id in analyzed_set,
            }
            for t in tracks
        ],
        "total": total,
    }


@router.get("/{track_id}")
async def get_track(track_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Track)
        .options(selectinload(Track.artist), selectinload(Track.album), selectinload(Track.analysis))
        .where(Track.id == track_id)
    )
    track = result.scalar_one_or_none()
    if not track:
        raise HTTPException(404, "Track not found")
    return {
        "id": track.id,
        "title": track.title,
        "artist": track.artist.name if track.artist else None,
        "artist_id": track.artist_id,
        "album": track.album.title if track.album else None,
        "album_id": track.album_id,
        "track_number": track.track_number,
        "disc_number": track.disc_number,
        "duration": track.duration_seconds,
        "file_path": track.file_path,
        "file_size": track.file_size,
        "format": track.format,
        "bitrate": track.bitrate,
        "sample_rate": track.sample_rate,
        "bit_depth": track.bit_depth,
        "genre": track.genre,
        "year": track.year,
        "play_count": track.play_count,
        "cover_art_path": track.cover_art_path,
        "analysis": {
            "bpm": track.analysis.bpm,
            "key": track.analysis.key,
            "scale": track.analysis.scale,
            "energy": track.analysis.energy,
            "danceability": track.analysis.danceability,
        } if track.analysis else None,
        "created_at": track.created_at.isoformat() if track.created_at else None,
    }


class TrackUpdateRequest(BaseModel):
    title: str | None = None
    genre: str | None = None
    year: int | None = None
    track_number: int | None = None


@router.put("/{track_id}")
async def update_track(track_id: str, req: TrackUpdateRequest, db: AsyncSession = Depends(get_db)):
    """Update track metadata in DB and write tags to file."""
    result = await db.execute(
        select(Track).options(selectinload(Track.artist), selectinload(Track.album))
        .where(Track.id == track_id)
    )
    track = result.scalar_one_or_none()
    if not track:
        raise HTTPException(404, "Track not found")

    if req.title is not None:
        track.title = req.title
    if req.genre is not None:
        track.genre = req.genre
    if req.year is not None:
        track.year = req.year
    if req.track_number is not None:
        track.track_number = req.track_number

    await db.commit()

    # Write tags to file
    try:
        from pathlib import Path
        from backend.config import get_settings
        import mutagen
        from mutagen.easyid3 import EasyID3

        settings = get_settings()
        file_path = Path(settings.library.music_dir) / track.file_path

        if file_path.exists():
            audio = mutagen.File(str(file_path), easy=True)
            if audio is not None:
                if req.title is not None:
                    audio["title"] = req.title
                if req.genre is not None:
                    audio["genre"] = req.genre
                if req.year is not None:
                    audio["date"] = str(req.year)
                if req.track_number is not None:
                    audio["tracknumber"] = str(req.track_number)
                audio.save()
    except Exception as e:
        log.warning("Tag write failed for track %s: %s", track_id, e)

    return {
        "ok": True,
        "track": {
            "id": track.id,
            "title": track.title,
            "genre": track.genre,
            "year": track.year,
            "track_number": track.track_number,
        },
    }


@router.post("/{track_id}/play")
async def record_play(track_id: str, db: AsyncSession = Depends(get_db)):
    """Record a play for a track — increments play_count, updates last_played_at, scrobbles to Last.fm."""
    from datetime import datetime

    result = await db.execute(
        select(Track).options(selectinload(Track.artist)).where(Track.id == track_id)
    )
    track = result.scalar_one_or_none()
    if not track:
        raise HTTPException(404, "Track not found")

    track.play_count = (track.play_count or 0) + 1
    track.last_played_at = datetime.utcnow()
    from backend.models.play_history import PlayHistory
    db.add(PlayHistory(track_id=track_id, played_at=datetime.utcnow(), source="web"))
    await db.commit()

    # Forward scrobble to Last.fm in background
    try:
        from backend.services.scrobbler import forward_scrobble
        await forward_scrobble(
            artist=track.artist.name if track.artist else "Unknown",
            track=track.title,
            album="",
        )
    except Exception as e:
        log.debug("Last.fm scrobble failed: %s", e)

    return {"ok": True, "play_count": track.play_count}


@router.put("/{track_id}/rating")
async def set_rating(track_id: str, rating: int = Query(ge=0, le=5), db: AsyncSession = Depends(get_db)):
    """Set a 0-5 star rating for a track. 0 removes the rating."""
    result = await db.execute(select(Track).where(Track.id == track_id))
    track = result.scalar_one_or_none()
    if not track:
        raise HTTPException(404, "Track not found")

    track.rating = rating if rating > 0 else None
    await db.commit()
    return {"ok": True, "rating": track.rating}


@router.delete("/{track_id}")
async def delete_track(track_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Track).where(Track.id == track_id))
    track = result.scalar_one_or_none()
    if not track:
        raise HTTPException(404, "Track not found")

    from pathlib import Path
    from backend.config import get_settings
    settings = get_settings()
    file_path = Path(settings.library.music_dir) / track.file_path
    if file_path.exists():
        file_path.unlink()

    # Clean up FK-dependent records before deleting track
    from backend.models.favorite import Favorite
    from backend.models.analysis import TrackAnalysis
    from backend.models.embedding import TrackEmbedding
    from backend.models.play_history import PlayHistory
    from backend.models.playlist import PlaylistTrack
    from backend.models.bookmark import Bookmark
    from backend.models.mood import TrackMood
    from backend.models.upgrade import TrackUpgrade
    await db.execute(delete(Favorite).where(Favorite.track_id == track_id))
    await db.execute(delete(TrackAnalysis).where(TrackAnalysis.track_id == track_id))
    await db.execute(delete(TrackEmbedding).where(TrackEmbedding.track_id == track_id))
    await db.execute(delete(PlayHistory).where(PlayHistory.track_id == track_id))
    await db.execute(delete(PlaylistTrack).where(PlaylistTrack.track_id == track_id))
    await db.execute(delete(Bookmark).where(Bookmark.track_id == track_id))
    await db.execute(delete(TrackMood).where(TrackMood.track_id == track_id))
    await db.execute(delete(TrackUpgrade).where(TrackUpgrade.track_id == track_id))
    # Remove FTS entry
    await db.execute(text("DELETE FROM tracks_fts WHERE track_id = :tid"), {"tid": track_id})
    await db.execute(delete(Track).where(Track.id == track_id))
    await db.commit()
    return {"ok": True}


class BulkDeleteRequest(BaseModel):
    track_ids: list[str]


@router.post("/bulk-delete")
async def bulk_delete_tracks(req: BulkDeleteRequest, db: AsyncSession = Depends(get_db)):
    """Delete multiple tracks and their files."""
    import asyncio
    from pathlib import Path
    from backend.config import get_settings
    from sqlalchemy.exc import OperationalError
    settings = get_settings()

    from backend.models.favorite import Favorite
    from backend.models.analysis import TrackAnalysis
    from backend.models.embedding import TrackEmbedding
    from backend.models.play_history import PlayHistory
    from backend.models.playlist import PlaylistTrack
    from backend.models.bookmark import Bookmark
    from backend.models.mood import TrackMood
    from backend.models.upgrade import TrackUpgrade

    # Fetch all tracks to delete files
    result = await db.execute(select(Track).where(Track.id.in_(req.track_ids)))
    tracks = result.scalars().all()
    found_ids = [t.id for t in tracks]

    # Delete files
    for track in tracks:
        file_path = Path(settings.library.music_dir) / track.file_path
        if file_path.exists():
            file_path.unlink()

    if found_ids:
        # Retry up to 3 times on database lock (background jobs may hold write lock)
        for attempt in range(3):
            try:
                await db.execute(delete(Favorite).where(Favorite.track_id.in_(found_ids)))
                await db.execute(delete(TrackAnalysis).where(TrackAnalysis.track_id.in_(found_ids)))
                await db.execute(delete(TrackEmbedding).where(TrackEmbedding.track_id.in_(found_ids)))
                await db.execute(delete(PlayHistory).where(PlayHistory.track_id.in_(found_ids)))
                await db.execute(delete(PlaylistTrack).where(PlaylistTrack.track_id.in_(found_ids)))
                await db.execute(delete(Bookmark).where(Bookmark.track_id.in_(found_ids)))
                await db.execute(delete(TrackMood).where(TrackMood.track_id.in_(found_ids)))
                await db.execute(delete(TrackUpgrade).where(TrackUpgrade.track_id.in_(found_ids)))
                for tid in found_ids:
                    await db.execute(text("DELETE FROM tracks_fts WHERE track_id = :tid"), {"tid": tid})
                await db.execute(delete(Track).where(Track.id.in_(found_ids)))
                await db.commit()
                break
            except OperationalError as e:
                await db.rollback()
                if "database is locked" in str(e) and attempt < 2:
                    log.warning(f"[bulk-delete] Database locked, retrying ({attempt + 1}/3)...")
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise HTTPException(503, "Database is busy — a background job may be running. Try again in a moment.")
    return {"deleted": len(found_ids)}


class AITagRequest(BaseModel):
    track_ids: list[str]


class ApplyTagsRequest(BaseModel):
    tags: list[dict]  # [{track_id, genre}]


@router.post("/ai-tag")
async def ai_tag_tracks(req: AITagRequest, db: AsyncSession = Depends(get_db)):
    """Get AI genre tag suggestions for selected tracks."""
    from backend.services.ai.auto_tagger import suggest_tags
    return await suggest_tags(db, req.track_ids)


@router.post("/ai-tag/apply")
async def apply_ai_tags(req: ApplyTagsRequest, db: AsyncSession = Depends(get_db)):
    """Apply AI-suggested genre tags to tracks."""
    from backend.services.ai.auto_tagger import apply_tags
    return await apply_tags(db, req.tags)


class BulkAnalyzeRequest(BaseModel):
    track_ids: list[str]


@router.post("/bulk-analyze")
async def bulk_analyze_tracks(req: BulkAnalyzeRequest, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    """Queue specific tracks for audio analysis."""
    import uuid
    from datetime import datetime
    from backend.database import async_session
    from backend.models.analysis import TrackAnalysis
    from backend.models.job import Job

    job_id = str(uuid.uuid4())

    # Verify tracks exist and collect file paths
    track_info = []
    for track_id in req.track_ids:
        result = await db.execute(select(Track.id, Track.file_path).where(Track.id == track_id))
        row = result.one_or_none()
        if row:
            track_info.append((row[0], row[1]))

    if not track_info:
        return {"job_id": None, "queued": 0}

    async def run_analysis():
        from backend.services.analyzer import analyze_track_async

        async with async_session() as db_inner:
            job = Job(
                id=job_id, type="audio_analysis", card="an", status="running",
                total=len(track_info), started_at=datetime.utcnow(),
            )
            db_inner.add(job)
            await db_inner.commit()

            for i, (track_id, file_path) in enumerate(track_info):
                try:
                    analysis = await analyze_track_async(file_path)
                    if analysis:
                        ta = TrackAnalysis(
                            track_id=track_id,
                            bpm=analysis.get("bpm"),
                            key=analysis.get("key"),
                            scale=analysis.get("scale"),
                            energy=analysis.get("energy"),
                            danceability=analysis.get("danceability"),
                            loudness=analysis.get("loudness"),
                        )
                        await db_inner.merge(ta)
                    else:
                        # Stub row excludes track from future batches
                        await db_inner.merge(TrackAnalysis(track_id=track_id))

                    job.progress = i + 1
                    await db_inner.merge(job)
                    await db_inner.commit()
                except Exception as e:
                    log.warning("Track analysis progress update failed: %s", e)

            job.status = "completed"
            job.finished_at = datetime.utcnow()
            await db_inner.merge(job)
            await db_inner.commit()

    background_tasks.add_task(run_analysis)
    return {"job_id": job_id, "queued": len(track_info)}


class MoodTagRequest(BaseModel):
    track_ids: list[str]


@router.post("/ai-moods")
async def tag_moods(req: MoodTagRequest):
    """Tag tracks with mood labels using CLAP embeddings."""
    from backend.services.ai.mood_tagger import tag_tracks_with_moods
    return await tag_tracks_with_moods(req.track_ids)


@router.get("/moods")
async def get_moods(track_ids: str | None = None):
    """Get mood tags for tracks. Pass comma-separated IDs or omit for all."""
    from backend.services.ai.mood_tagger import get_track_moods
    ids = track_ids.split(",") if track_ids else None
    return await get_track_moods(ids)


class RepairTagsRequest(BaseModel):
    track_ids: list[str] | None = None  # None = all tracks with missing artist
    dry_run: bool = True


@router.post("/repair-tags")
async def repair_tags(req: RepairTagsRequest, db: AsyncSession = Depends(get_db)):
    """Repair tags by parsing artist/title from filenames for tracks with missing metadata.

    Targets tracks where artist is NULL but the filename contains 'Artist - Title'.
    Also writes corrected tags to the audio file.
    """
    import hashlib
    from pathlib import Path
    from backend.config import get_settings
    from backend.services.scanner import _parse_filename
    from backend.database import update_fts_index

    settings = get_settings()
    music_dir = Path(settings.library.music_dir)

    if req.track_ids:
        result = await db.execute(
            select(Track).options(selectinload(Track.artist))
            .where(Track.id.in_(req.track_ids))
        )
    else:
        # Find all tracks with no artist
        result = await db.execute(
            select(Track).options(selectinload(Track.artist))
            .where(Track.artist_id.is_(None))
        )
    tracks = result.scalars().all()

    repairs = []
    applied = 0

    for t in tracks:
        if not t.file_path:
            continue
        stem = Path(t.file_path).stem
        parsed = _parse_filename(stem)
        if not parsed.get("artist"):
            continue

        new_artist = parsed["artist"]
        new_title = parsed.get("title", t.title)
        old_title = t.title
        old_artist = t.artist.name if t.artist else None

        repair = {
            "track_id": t.id,
            "file_path": t.file_path,
            "old_title": old_title,
            "old_artist": old_artist,
            "new_title": new_title,
            "new_artist": new_artist,
        }
        repairs.append(repair)

        if not req.dry_run:
            # Find or create artist
            artist_key = new_artist.lower().strip()
            artist_id = hashlib.md5(artist_key.encode()).hexdigest()
            existing_artist = await db.get(Artist, artist_id)
            if not existing_artist:
                existing_artist = Artist(id=artist_id, name=new_artist)
                db.add(existing_artist)
                await db.flush()

            t.title = new_title
            t.artist_id = artist_id

            # Write tags to file
            try:
                import mutagen
                full_path = music_dir / t.file_path
                if full_path.exists():
                    audio = mutagen.File(str(full_path), easy=True)
                    if audio is not None:
                        audio["title"] = new_title
                        audio["artist"] = new_artist
                        audio.save()
            except Exception as e:
                log.warning(f"[repair] Could not write tags to {t.file_path}: {e}")

            await update_fts_index(db, t.id, new_title, new_artist, t.album.title if t.album else None)
            applied += 1

    if not req.dry_run and applied:
        await db.commit()

    return {
        "repairs": repairs,
        "total": len(repairs),
        "applied": applied if not req.dry_run else 0,
        "dry_run": req.dry_run,
    }


# ---------------------------------------------------------------------------
# Waveform endpoint — pre-computed amplitude data for seek bar rendering
# ---------------------------------------------------------------------------

WAVEFORM_CACHE_DIR = None  # lazy-init


def _get_waveform_cache_dir():
    global WAVEFORM_CACHE_DIR
    if WAVEFORM_CACHE_DIR is None:
        from backend.config import get_settings
        settings = get_settings()
        base = getattr(settings.library, "cover_cache_dir", "/opt/zonik/cache/covers")
        from pathlib import Path
        WAVEFORM_CACHE_DIR = Path(base).parent / "waveforms"
        WAVEFORM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return WAVEFORM_CACHE_DIR


async def _generate_waveform(file_path: str, bars: int = 200) -> list[float]:
    """Decode audio to PCM via ffmpeg and compute RMS amplitude per segment."""
    import asyncio
    import struct
    import math

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-i", file_path,
        "-f", "s16le", "-acodec", "pcm_s16le",
        "-ac", "1", "-ar", "8000",
        "-v", "quiet", "-",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    pcm_data, _ = await proc.communicate()

    if proc.returncode != 0 or len(pcm_data) < 4:
        return []

    num_samples = len(pcm_data) // 2
    samples = struct.unpack(f"<{num_samples}h", pcm_data)

    samples_per_bar = max(num_samples // bars, 1)
    waveform = []
    for i in range(bars):
        start = i * samples_per_bar
        end = min(start + samples_per_bar, num_samples)
        segment = samples[start:end]
        if not segment:
            waveform.append(0.0)
            continue
        rms = math.sqrt(sum(s * s for s in segment) / len(segment)) / 32768
        waveform.append(rms)

    peak = max(waveform) if waveform else 1.0
    if peak > 0:
        waveform = [round(v / peak, 4) for v in waveform]

    return waveform


@router.get("/{track_id}/waveform")
async def get_waveform(
    track_id: str,
    bars: int = Query(200, ge=10, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """Return pre-computed waveform amplitude data for a track."""
    import json
    from pathlib import Path
    from fastapi.responses import JSONResponse
    from backend.config import get_settings

    result = await db.execute(select(Track).where(Track.id == track_id))
    track = result.scalar_one_or_none()
    if not track:
        raise HTTPException(404, "Track not found")

    settings = get_settings()
    file_path = Path(settings.library.music_dir) / track.file_path
    if not file_path.exists():
        raise HTTPException(404, "Audio file not found")

    # Check cache
    cache_dir = _get_waveform_cache_dir()
    cache_file = cache_dir / f"{track_id}_{bars}.json"

    if cache_file.exists():
        waveform = json.loads(cache_file.read_text())
    else:
        waveform = await _generate_waveform(str(file_path), bars)
        if not waveform:
            raise HTTPException(500, "Failed to decode audio")
        cache_file.write_text(json.dumps(waveform))

    return JSONResponse(
        content={"waveform": waveform},
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
