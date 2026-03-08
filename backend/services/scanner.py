"""Library file scanner - reads audio files, parses tags, populates DB."""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime
from pathlib import Path

import mutagen
from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.models.track import Track
from backend.models.artist import Artist
from backend.models.album import Album

log = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {".flac", ".mp3", ".m4a", ".ogg", ".opus", ".wav", ".wma", ".aac"}

# Higher = better quality format
FORMAT_QUALITY = {"flac": 10, "wav": 9, "alac": 8, "aiff": 8, "m4a": 5, "ogg": 4, "opus": 4, "mp3": 3, "aac": 3, "wma": 2}

MIME_MAP = {
    ".flac": "audio/flac",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".wav": "audio/wav",
    ".wma": "audio/x-ms-wma",
    ".aac": "audio/aac",
}

FORMAT_MAP = {
    ".flac": "flac",
    ".mp3": "mp3",
    ".m4a": "m4a",
    ".ogg": "ogg",
    ".opus": "opus",
    ".wav": "wav",
    ".wma": "wma",
    ".aac": "aac",
}


def _stable_id(path: str) -> str:
    """Generate a stable ID from the file path."""
    return hashlib.md5(path.encode()).hexdigest()


def _get_tag(audio, keys: list[str], default=None):
    """Extract a tag value trying multiple key names."""
    for key in keys:
        val = audio.get(key)
        if val:
            if isinstance(val, list):
                return str(val[0])
            return str(val)
    return default


def _get_int_tag(audio, keys: list[str], default=None) -> int | None:
    val = _get_tag(audio, keys)
    if val is None:
        return default
    try:
        # Handle "3/12" format
        return int(str(val).split("/")[0])
    except (ValueError, IndexError):
        return default


def parse_audio_file(file_path: Path, music_dir: Path) -> dict | None:
    """Parse tags from an audio file, return a dict of track fields."""
    if file_path.stat().st_size == 0:
        return None  # Skip empty/corrupt files silently
    try:
        audio = mutagen.File(str(file_path), easy=True)
        if audio is None:
            return None
    except Exception as e:
        log.warning(f"Failed to read tags from {file_path}: {e}")
        return None

    rel_path = str(file_path.relative_to(music_dir))
    suffix = file_path.suffix.lower()

    # Get audio info
    info = audio.info if audio.info else None
    duration = info.length if info else None
    bitrate = getattr(info, "bitrate", None)
    sample_rate = getattr(info, "sample_rate", None)
    bit_depth = getattr(info, "bits_per_sample", None)

    title = _get_tag(audio, ["title"]) or file_path.stem
    artist_name = _get_tag(audio, ["artist", "albumartist"])
    album_title = _get_tag(audio, ["album"])
    track_number = _get_int_tag(audio, ["tracknumber"])
    disc_number = _get_int_tag(audio, ["discnumber"], default=1)
    genre = _get_tag(audio, ["genre"])
    year_str = _get_tag(audio, ["date", "year"])
    year = None
    if year_str:
        try:
            year = int(year_str[:4])
        except (ValueError, IndexError):
            pass

    musicbrainz_id = _get_tag(audio, ["musicbrainz_trackid", "musicbrainz_recordingid"])

    # ReplayGain
    rg_track = None
    rg_album = None
    rg_str = _get_tag(audio, ["replaygain_track_gain"])
    if rg_str:
        try:
            rg_track = float(rg_str.replace(" dB", ""))
        except ValueError:
            pass
    rg_str = _get_tag(audio, ["replaygain_album_gain"])
    if rg_str:
        try:
            rg_album = float(rg_str.replace(" dB", ""))
        except ValueError:
            pass

    return {
        "file_path": rel_path,
        "title": title,
        "artist_name": artist_name,
        "album_title": album_title,
        "track_number": track_number,
        "disc_number": disc_number,
        "duration_seconds": duration,
        "file_size": file_path.stat().st_size,
        "format": FORMAT_MAP.get(suffix, suffix.lstrip(".")),
        "bitrate": bitrate,
        "sample_rate": sample_rate,
        "bit_depth": bit_depth,
        "mime_type": MIME_MAP.get(suffix),
        "genre": genre,
        "year": year,
        "musicbrainz_id": musicbrainz_id,
        "replay_gain_track": rg_track,
        "replay_gain_album": rg_album,
    }


def extract_cover_art(file_path: Path, cache_dir: Path) -> str | None:
    """Extract embedded cover art to cache directory. Returns cached path or None."""
    try:
        audio = mutagen.File(str(file_path))
        if audio is None:
            return None

        art_data = None

        if isinstance(audio, FLAC):
            if audio.pictures:
                art_data = audio.pictures[0].data
        elif isinstance(audio, MP3):
            for tag in audio.tags.values() if audio.tags else []:
                if hasattr(tag, "data") and hasattr(tag, "mime"):
                    art_data = tag.data
                    break
        elif isinstance(audio, MP4):
            covr = audio.tags.get("covr") if audio.tags else None
            if covr:
                art_data = bytes(covr[0])
        elif isinstance(audio, (OggVorbis, OggOpus)):
            if hasattr(audio, "pictures") and audio.pictures:
                art_data = audio.pictures[0].data

        if art_data:
            art_hash = hashlib.md5(art_data).hexdigest()
            ext = "jpg"  # Default
            if art_data[:8] == b"\x89PNG\r\n\x1a\n":
                ext = "png"
            art_path = cache_dir / f"{art_hash}.{ext}"
            if not art_path.exists():
                cache_dir.mkdir(parents=True, exist_ok=True)
                art_path.write_bytes(art_data)
            return str(art_path)
    except Exception as e:
        log.debug(f"Failed to extract cover from {file_path}: {e}")
    return None


async def get_or_create_artist(db: AsyncSession, name: str) -> Artist:
    """Get existing artist or create new one."""
    artist_id = _stable_id(f"artist:{name.lower()}")
    # Check identity map first via get(), then DB
    artist = await db.get(Artist, artist_id)
    if artist:
        return artist
    artist = Artist(id=artist_id, name=name, sort_name=name)
    db.add(artist)
    return artist


async def get_or_create_album(db: AsyncSession, title: str, artist: Artist | None, year: int | None) -> Album:
    """Get existing album or create new one."""
    key = f"album:{title.lower()}:{artist.name.lower() if artist else 'unknown'}"
    album_id = _stable_id(key)
    # Check identity map first via get(), then DB
    album = await db.get(Album, album_id)
    if album:
        return album
    album = Album(
        id=album_id,
        title=title,
        artist_id=artist.id if artist else None,
        year=year,
    )
    db.add(album)
    return album


async def scan_library(db: AsyncSession, progress_callback=None) -> dict:
    """Scan the music directory and update the database.

    Args:
        progress_callback: Optional async callable(stats, total_files) called periodically.
    """
    settings = get_settings()
    music_dir = Path(settings.library.music_dir)
    cache_dir = Path(settings.library.cover_cache_dir)

    if not music_dir.exists():
        return {"error": f"Music directory not found: {music_dir}"}

    stats = {"scanned": 0, "added": 0, "updated": 0, "errors": 0}

    # Count total audio files first for progress tracking
    audio_files = [
        f for f in music_dir.rglob("*")
        if f.suffix.lower() in AUDIO_EXTENSIONS and f.is_file()
    ]
    total_files = len(audio_files)

    # Collect existing file paths
    result = await db.execute(select(Track.file_path))
    existing_paths = {row[0] for row in result.all()}

    for file_path in audio_files:
        stats["scanned"] += 1
        parsed = parse_audio_file(file_path, music_dir)
        if not parsed:
            stats["errors"] += 1
            continue

        rel_path = parsed["file_path"]
        track_id = _stable_id(rel_path)

        # Get or create artist
        artist = None
        if parsed["artist_name"]:
            artist = await get_or_create_artist(db, parsed["artist_name"])

        # Get or create album
        album = None
        if parsed["album_title"]:
            album = await get_or_create_album(db, parsed["album_title"], artist, parsed["year"])

        # Extract cover art
        cover_path = extract_cover_art(file_path, cache_dir)

        # Update album cover if we found one
        if cover_path and album and not album.cover_art_path:
            album.cover_art_path = cover_path

        if rel_path in existing_paths:
            # Update existing track
            result = await db.execute(select(Track).where(Track.file_path == rel_path))
            track = result.scalar_one_or_none()
            if track:
                track.title = parsed["title"]
                track.artist_id = artist.id if artist else None
                track.album_id = album.id if album else None
                track.track_number = parsed["track_number"]
                track.disc_number = parsed["disc_number"]
                track.duration_seconds = parsed["duration_seconds"]
                track.file_size = parsed["file_size"]
                track.format = parsed["format"]
                track.bitrate = parsed["bitrate"]
                track.sample_rate = parsed["sample_rate"]
                track.bit_depth = parsed["bit_depth"]
                track.mime_type = parsed["mime_type"]
                track.genre = parsed["genre"]
                track.year = parsed["year"]
                track.musicbrainz_id = parsed["musicbrainz_id"]
                track.replay_gain_track = parsed["replay_gain_track"]
                track.replay_gain_album = parsed["replay_gain_album"]
                if cover_path:
                    track.cover_art_path = cover_path
                stats["updated"] += 1
            existing_paths.discard(rel_path)
        else:
            # New track
            track = Track(
                id=track_id,
                title=parsed["title"],
                artist_id=artist.id if artist else None,
                album_id=album.id if album else None,
                track_number=parsed["track_number"],
                disc_number=parsed["disc_number"],
                duration_seconds=parsed["duration_seconds"],
                file_path=rel_path,
                file_size=parsed["file_size"],
                format=parsed["format"],
                bitrate=parsed["bitrate"],
                sample_rate=parsed["sample_rate"],
                bit_depth=parsed["bit_depth"],
                mime_type=parsed["mime_type"],
                genre=parsed["genre"],
                year=parsed["year"],
                musicbrainz_id=parsed["musicbrainz_id"],
                cover_art_path=cover_path,
                replay_gain_track=parsed["replay_gain_track"],
                replay_gain_album=parsed["replay_gain_album"],
            )
            db.add(track)
            stats["added"] += 1

        # Update FTS index
        from backend.database import update_fts_index
        await update_fts_index(
            db, track_id, parsed["title"],
            parsed["artist_name"], parsed["album_title"],
        )

        # Flush periodically and report progress
        if stats["scanned"] % 50 == 0:
            await db.flush()
            if progress_callback:
                await progress_callback(stats, total_files)

    await db.commit()

    # Remove orphaned tracks (DB entries whose files no longer exist)
    stats["orphans_removed"] = 0
    if existing_paths:
        orphan_result = await db.execute(
            select(Track.id).where(Track.file_path.in_(existing_paths))
        )
        orphan_ids = [row[0] for row in orphan_result.all()]
        if orphan_ids:
            from backend.models.favorite import Favorite
            from backend.models.playlist import PlaylistTrack
            await db.execute(delete(Favorite).where(Favorite.track_id.in_(orphan_ids)))
            await db.execute(delete(PlaylistTrack).where(PlaylistTrack.track_id.in_(orphan_ids)))
            await db.execute(delete(Track).where(Track.id.in_(orphan_ids)))
            stats["orphans_removed"] = len(orphan_ids)
            log.info(f"Removed {len(orphan_ids)} orphaned tracks")

    # Update album track counts + clean up empty albums/artists
    albums = (await db.execute(select(Album))).scalars().all()
    for album in albums:
        count = (await db.execute(
            select(func.count(Track.id)).where(Track.album_id == album.id)
        )).scalar()
        album.track_count = count

    # Remove empty albums and artists
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

    log.info(f"Scan complete: {stats}")
    return stats


def _normalize_title(s: str) -> str:
    """Normalize a title for matching (lowercase, strip parentheticals, non-alphanum)."""
    import re
    if not s:
        return ""
    s = s.lower().strip()
    s = re.sub(r"\s*\(.*?\)\s*", " ", s)
    s = re.sub(r"\s*\[.*?\]\s*", " ", s)
    s = re.sub(r"[^a-z0-9\s]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _quality_rank(fmt: str, file_size: int) -> tuple[int, int]:
    """Return (format_rank, file_size) for quality comparison."""
    return (FORMAT_QUALITY.get(fmt, 0), file_size)


async def _find_existing_track(db: AsyncSession, title: str, artist_name: str) -> Track | None:
    """Find an existing library track with the same normalized title and artist."""
    if not title:
        return None
    norm_title = _normalize_title(title)
    norm_artist = _normalize_title(artist_name)
    if not norm_title:
        return None

    # Search by exact artist+title first
    if norm_artist:
        result = await db.execute(
            select(Track).join(Artist, Track.artist_id == Artist.id).where(
                Track.title.isnot(None),
            )
        )
        for track in result.scalars().all():
            if _normalize_title(track.title) == norm_title:
                artist_obj = await db.get(Artist, track.artist_id) if track.artist_id else None
                if artist_obj and _normalize_title(artist_obj.name) == norm_artist:
                    return track
    return None


async def import_downloaded_file(
    db: AsyncSession,
    save_path: str,
    artist_hint: str = "",
) -> str | None:
    """Move a downloaded file into the music library and index it.

    If a track with the same title+artist already exists and the new file
    is higher quality, replaces the old file (upgrade). Otherwise imports
    as a new track.

    Returns the track ID on success, or None on failure.
    """
    import shutil

    src = Path(save_path)
    if not src.exists():
        log.warning(f"[import] File not found: {save_path}")
        return None
    if src.stat().st_size == 0:
        log.warning(f"[import] Empty file (0 bytes), skipping: {save_path}")
        src.unlink(missing_ok=True)
        return None

    settings = get_settings()
    music_dir = Path(settings.library.music_dir)
    cache_dir = Path(settings.library.cover_cache_dir)

    # Parse tags to get artist name for directory structure
    parsed = parse_audio_file(src, src.parent)
    if not parsed:
        log.warning(f"[import] Could not parse audio tags: {save_path}")
        return None

    new_fmt = parsed["format"] or ""
    new_size = parsed["file_size"] or src.stat().st_size

    # --- Check for existing track (upgrade detection) ---
    existing = await _find_existing_track(db, parsed["title"], parsed["artist_name"] or artist_hint)
    if existing:
        old_quality = _quality_rank(existing.format or "", existing.file_size or 0)
        new_quality = _quality_rank(new_fmt, new_size)
        if new_quality > old_quality:
            # Upgrade — replace the old file
            old_path = music_dir / existing.file_path if existing.file_path else None
            folder_name = parsed["artist_name"] or artist_hint or "Unknown Artist"
            folder_name = "".join(c for c in folder_name if c not in '<>:"/\\|?*').strip() or "Unknown Artist"
            dest_dir = music_dir / folder_name
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / src.name

            if dest.exists() and dest != src:
                stem, ext = dest.stem, dest.suffix
                for i in range(1, 100):
                    dest = dest_dir / f"{stem} ({i}){ext}"
                    if not dest.exists():
                        break

            try:
                shutil.move(str(src), str(dest))
            except Exception as e:
                log.warning(f"[import] Failed to move {src} → {dest}: {e}")
                return None

            # Delete old file
            if old_path and old_path.exists():
                try:
                    old_path.unlink()
                    log.info(f"[import] Upgrade: removed old {old_path.name} ({existing.format}, {existing.file_size or 0} bytes)")
                except Exception as e:
                    log.warning(f"[import] Could not delete old file {old_path}: {e}")

            # Re-parse from new location and update existing track
            parsed = parse_audio_file(dest, music_dir)
            if not parsed:
                return None

            rel_path = parsed["file_path"]
            new_track_id = _stable_id(rel_path)

            # Update the existing track record with new file info
            existing.file_path = rel_path
            existing.file_size = parsed["file_size"]
            existing.format = parsed["format"]
            existing.bitrate = parsed["bitrate"]
            existing.sample_rate = parsed["sample_rate"]
            existing.bit_depth = parsed["bit_depth"]
            existing.mime_type = parsed["mime_type"]
            existing.duration_seconds = parsed["duration_seconds"]

            # If the track ID changed (different file path), we need to update it
            if new_track_id != existing.id:
                # Delete old FTS entry
                from backend.database import update_fts_index
                try:
                    await db.execute(
                        select(Track).where(Track.id == existing.id)
                    )
                except Exception:
                    pass
                # Create new track with new ID, copy relationships
                new_track = Track(
                    id=new_track_id,
                    title=existing.title,
                    artist_id=existing.artist_id,
                    album_id=existing.album_id,
                    track_number=existing.track_number,
                    disc_number=existing.disc_number,
                    duration_seconds=parsed["duration_seconds"],
                    file_path=rel_path,
                    file_size=parsed["file_size"],
                    format=parsed["format"],
                    bitrate=parsed["bitrate"],
                    sample_rate=parsed["sample_rate"],
                    bit_depth=parsed["bit_depth"],
                    mime_type=parsed["mime_type"],
                    genre=existing.genre,
                    year=existing.year,
                    musicbrainz_id=existing.musicbrainz_id,
                    cover_art_path=existing.cover_art_path,
                    replay_gain_track=parsed["replay_gain_track"],
                    replay_gain_album=parsed["replay_gain_album"],
                    play_count=existing.play_count,
                )
                # Migrate favorites to new track ID
                from backend.models.favorite import Favorite
                favs = (await db.execute(
                    select(Favorite).where(Favorite.track_id == existing.id)
                )).scalars().all()
                for fav in favs:
                    fav.track_id = new_track_id

                # Migrate play history to new track ID
                from backend.models.play_history import PlayHistory
                plays = (await db.execute(
                    select(PlayHistory).where(PlayHistory.track_id == existing.id)
                )).scalars().all()
                for play in plays:
                    play.track_id = new_track_id

                # Migrate upgrade records to new track ID
                from backend.models.upgrade import TrackUpgrade
                upgrades = (await db.execute(
                    select(TrackUpgrade).where(TrackUpgrade.track_id == existing.id)
                )).scalars().all()
                for upg in upgrades:
                    upg.track_id = new_track_id

                # Carry over rating
                new_track.rating = existing.rating

                await db.delete(existing)
                await db.flush()
                db.add(new_track)
                await update_fts_index(db, new_track_id, new_track.title, parsed["artist_name"], parsed["album_title"])
                await db.commit()
                log.info(f"[import] Upgraded: {parsed['artist_name']} — {parsed['title']} ({existing.format}→{new_fmt})")
                await _mark_upgrade_completed(db, new_track_id, new_fmt, parsed["bitrate"], parsed["file_size"])
                return new_track_id
            else:
                from backend.database import update_fts_index
                await update_fts_index(db, existing.id, existing.title, parsed["artist_name"], parsed["album_title"])
                await db.commit()
                log.info(f"[import] Upgraded in-place: {parsed['artist_name']} — {parsed['title']} ({existing.format}→{new_fmt})")
                await _mark_upgrade_completed(db, existing.id, new_fmt, parsed["bitrate"], parsed["file_size"])
                return existing.id
        else:
            # Not an upgrade — check if it's a different version (remix etc)
            # by comparing normalized titles more strictly (with parentheticals)
            existing_title = (existing.title or "").lower().strip()
            new_title = (parsed["title"] or "").lower().strip()
            if existing_title == new_title:
                # Exact same title, not an upgrade — skip (duplicate)
                log.info(f"[import] Duplicate skipped (library has equal/better): {parsed['title']}")
                await _mark_upgrade_failed(db, existing.id, "Downloaded file not higher quality")
                src.unlink(missing_ok=True)
                return None
            # Different version (remix, acoustic, live, etc.) — fall through to normal import

    # --- Normal import (new track) ---
    folder_name = parsed["artist_name"] or artist_hint or "Unknown Artist"
    folder_name = "".join(c for c in folder_name if c not in '<>:"/\\|?*').strip()
    if not folder_name:
        folder_name = "Unknown Artist"

    dest_dir = music_dir / folder_name
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name

    # Handle name collision
    if dest.exists() and dest != src:
        stem, ext = dest.stem, dest.suffix
        for i in range(1, 100):
            dest = dest_dir / f"{stem} ({i}){ext}"
            if not dest.exists():
                break

    try:
        shutil.move(str(src), str(dest))
    except Exception as e:
        log.warning(f"[import] Failed to move {src} → {dest}: {e}")
        return None

    # Re-parse from new location
    parsed = parse_audio_file(dest, music_dir)
    if not parsed:
        return None

    rel_path = parsed["file_path"]
    track_id = _stable_id(rel_path)

    artist = None
    if parsed["artist_name"]:
        artist = await get_or_create_artist(db, parsed["artist_name"])

    album = None
    if parsed["album_title"]:
        album = await get_or_create_album(db, parsed["album_title"], artist, parsed["year"])

    cover_path = extract_cover_art(dest, cache_dir)
    if cover_path and album and not album.cover_art_path:
        album.cover_art_path = cover_path

    track = Track(
        id=track_id,
        title=parsed["title"],
        artist_id=artist.id if artist else None,
        album_id=album.id if album else None,
        track_number=parsed["track_number"],
        disc_number=parsed["disc_number"],
        duration_seconds=parsed["duration_seconds"],
        file_path=rel_path,
        file_size=parsed["file_size"],
        format=parsed["format"],
        bitrate=parsed["bitrate"],
        sample_rate=parsed["sample_rate"],
        bit_depth=parsed["bit_depth"],
        mime_type=parsed["mime_type"],
        genre=parsed["genre"],
        year=parsed["year"],
        musicbrainz_id=parsed["musicbrainz_id"],
        cover_art_path=cover_path,
        replay_gain_track=parsed["replay_gain_track"],
        replay_gain_album=parsed["replay_gain_album"],
    )
    db.add(track)

    from backend.database import update_fts_index
    await update_fts_index(
        db, track_id, parsed["title"],
        parsed["artist_name"], parsed["album_title"],
    )
    await db.commit()
    log.info(f"[import] Indexed: {parsed['artist_name']} — {parsed['title']} → {rel_path}")
    return track_id


async def _mark_upgrade_completed(db, track_id: str, fmt: str, bitrate: int | None, file_size: int | None):
    """Mark a TrackUpgrade as completed after successful upgrade import."""
    try:
        from backend.models.upgrade import TrackUpgrade
        from sqlalchemy import update
        result = await db.execute(
            update(TrackUpgrade)
            .where(TrackUpgrade.track_id == track_id, TrackUpgrade.status.in_(["queued", "downloading"]))
            .values(status="completed", upgraded_format=fmt, upgraded_bitrate=bitrate, upgraded_file_size=file_size, completed_at=datetime.utcnow())
        )
        if result.rowcount:
            await db.commit()
            log.info(f"[import] TrackUpgrade for {track_id} marked completed ({result.rowcount} rows)")
        else:
            log.debug(f"[import] No TrackUpgrade found for {track_id}")
    except Exception as e:
        log.debug(f"[import] TrackUpgrade update skipped: {e}")


async def _mark_upgrade_failed(db, track_id: str, message: str):
    """Mark a TrackUpgrade as failed when download is not an upgrade."""
    try:
        from backend.models.upgrade import TrackUpgrade
        from sqlalchemy import update
        result = await db.execute(
            update(TrackUpgrade)
            .where(TrackUpgrade.track_id == track_id, TrackUpgrade.status.in_(["queued", "downloading"]))
            .values(status="failed", error_message=message)
        )
        if result.rowcount:
            await db.commit()
            log.info(f"[import] TrackUpgrade for {track_id} marked failed: {message}")
    except Exception as e:
        log.debug(f"[import] TrackUpgrade update skipped: {e}")


def cleanup_download_dir():
    """Remove zero-byte files and non-audio files from the download directory."""
    settings = get_settings()
    dl_dir = Path(settings.library.download_dir)
    if not dl_dir.exists():
        return

    removed = 0
    for f in dl_dir.iterdir():
        if not f.is_file():
            continue
        # Remove zero-byte files (failed transfers)
        if f.stat().st_size == 0:
            f.unlink(missing_ok=True)
            log.info(f"[cleanup] Removed zero-byte file: {f.name}")
            removed += 1
            continue
        # Remove non-audio files (skip known subdirs)
        ext = f.suffix.lower()
        if ext not in AUDIO_EXTENSIONS:
            f.unlink(missing_ok=True)
            log.info(f"[cleanup] Removed non-audio file: {f.name}")
            removed += 1

    if removed:
        log.info(f"[cleanup] Removed {removed} files from downloads dir")
