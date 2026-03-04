"""Audio tag reading/writing via mutagen."""
from __future__ import annotations

import logging
from pathlib import Path

import mutagen
from mutagen.easyid3 import EasyID3
from mutagen.flac import FLAC
from mutagen.mp4 import MP4
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis

from backend.config import get_settings

log = logging.getLogger(__name__)


def write_tags(file_path: str, tags: dict) -> bool:
    """Write metadata tags to an audio file.

    Supported tags: title, artist, album, tracknumber, date, genre
    Returns True on success.
    """
    settings = get_settings()
    abs_path = Path(settings.library.music_dir) / file_path

    if not abs_path.exists():
        log.warning(f"File not found for tagging: {abs_path}")
        return False

    try:
        audio = mutagen.File(str(abs_path), easy=True)
        if audio is None:
            log.warning(f"Cannot read file for tagging: {abs_path}")
            return False

        tag_map = {
            "title": "title",
            "artist": "artist",
            "album": "album",
            "tracknumber": "tracknumber",
            "date": "date",
            "genre": "genre",
            "albumartist": "albumartist",
        }

        for key, tag_key in tag_map.items():
            if key in tags and tags[key] is not None:
                audio[tag_key] = [str(tags[key])]

        audio.save()
        return True

    except Exception as e:
        log.error(f"Failed to write tags to {file_path}: {e}")
        return False


def read_tags(file_path: str) -> dict | None:
    """Read metadata tags from an audio file."""
    settings = get_settings()
    abs_path = Path(settings.library.music_dir) / file_path

    if not abs_path.exists():
        return None

    try:
        audio = mutagen.File(str(abs_path), easy=True)
        if audio is None:
            return None

        def _get(keys):
            for k in keys:
                val = audio.get(k)
                if val:
                    return str(val[0]) if isinstance(val, list) else str(val)
            return None

        return {
            "title": _get(["title"]),
            "artist": _get(["artist", "albumartist"]),
            "album": _get(["album"]),
            "tracknumber": _get(["tracknumber"]),
            "date": _get(["date", "year"]),
            "genre": _get(["genre"]),
        }
    except Exception as e:
        log.error(f"Failed to read tags from {file_path}: {e}")
        return None
