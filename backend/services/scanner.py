"""Library file scanner - reads audio files, parses tags, populates DB."""
from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import Path

import mutagen
from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.models.track import Track
from backend.models.artist import Artist
from backend.models.album import Album

log = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {".flac", ".mp3", ".m4a", ".ogg", ".opus", ".wav", ".wma", ".aac"}

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
    result = await db.execute(select(Artist).where(Artist.name == name))
    artist = result.scalar_one_or_none()
    if artist:
        return artist
    artist = Artist(
        id=_stable_id(f"artist:{name.lower()}"),
        name=name,
        sort_name=name,
    )
    db.add(artist)
    return artist


async def get_or_create_album(db: AsyncSession, title: str, artist: Artist | None, year: int | None) -> Album:
    """Get existing album or create new one."""
    key = f"album:{title.lower()}:{artist.name.lower() if artist else 'unknown'}"
    album_id = _stable_id(key)
    result = await db.execute(select(Album).where(Album.id == album_id))
    album = result.scalar_one_or_none()
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


async def scan_library(db: AsyncSession) -> dict:
    """Scan the music directory and update the database."""
    settings = get_settings()
    music_dir = Path(settings.library.music_dir)
    cache_dir = Path(settings.library.cover_cache_dir)

    if not music_dir.exists():
        return {"error": f"Music directory not found: {music_dir}"}

    stats = {"scanned": 0, "added": 0, "updated": 0, "errors": 0}

    # Collect existing file paths
    result = await db.execute(select(Track.file_path))
    existing_paths = {row[0] for row in result.all()}

    for file_path in music_dir.rglob("*"):
        if file_path.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        if not file_path.is_file():
            continue

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

        # Flush periodically
        if stats["scanned"] % 100 == 0:
            await db.flush()

    await db.commit()

    # Update album track counts
    from sqlalchemy import func
    albums = (await db.execute(select(Album))).scalars().all()
    for album in albums:
        count = (await db.execute(
            select(func.count(Track.id)).where(Track.album_id == album.id)
        )).scalar()
        album.track_count = count
    await db.commit()

    log.info(f"Scan complete: {stats}")
    return stats
