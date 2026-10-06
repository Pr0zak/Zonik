"""Naming rules for the library tidy: where a track's file belongs, worked out from its tags.

Pure functions, no I/O, so every rule can be tested on the real names found in the library
(tests/test_tidy_rules.py). The planner (services/tidy.py) reads the tags, groups tracks into
albums and calls `target_path` for each.

Layout (decided 2026-10-05, plans/library-tidy.md):

    Artist/Album/NN - Title.ext                      an album track
    Artist/Album/D-NN - Title.ext                    on an album with more than one disc
    Artist/Singles/Title.ext                         no album, or a single tagged as an album of its own name
    Various Artists/Album/NN - Artist - Title.ext    a compilation, kept whole
    _Untagged/<original path>                        no artist tag at all

Names are folded to plain ASCII punctuation, stripped of characters the filesystem or SMB
rejects, of YouTube IDs and "(Official Video)" clutter, and capped in length.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

VARIOUS = "Various Artists"
SINGLES = "Singles"
UNTAGGED = "_Untagged"
MAX_SEGMENT = 120  # characters; well under the 255-byte limit even for multi-byte scripts

_PUNCT = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'", "´": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-",
    "−": "-", "…": "...", " ": " ", " ": " ", " ": " ",
    "​": "", "‌": "", "‍": "", "﻿": "",
})

# Clutter that YouTube and web rips leave in titles.
_YT_ID = re.compile(r"\s*\[[A-Za-z0-9_-]{11}\]")
_VIDEO_NOISE = re.compile(
    r"\s*[\(\[]\s*(official\s+(music\s+|lyric\s+)?(video|audio|visuali[sz]er)|lyric\s+video|lyrics|"
    r"video\s+oficial|audio\s+oficial|official)\s*[\)\]]",
    re.I,
)
_VIDEO_NOISE_BARE = re.compile(r"\s+(official\s+(music\s+|lyric\s+)?(video|audio))\s*$", re.I)

# Release-format clutter in album tags: "(44.1kHz, 16bit, 2ch.)", "[Web, FLAC, 48-23]", "[24BIT-48KHZ]".
_FORMAT_NOISE = re.compile(
    r"\s*[\(\[][^\)\]]*\b(\d+(\.\d+)?\s*khz|\d+\s*-?\s*bit|flac|web|lossless|320|mp3)\b[^\)\]]*[\)\]]",
    re.I,
)
_JUNK_ALBUMS = {"", "flac", "mp3", "web", "unknown", "unknown album", "album", "singles", "single", "various"}
_DOMAIN = re.compile(r"^\S+\.(com|net|org|ru|info|io|co|to|cc)\b", re.I)

_FEAT = re.compile(r"\s+[\(\[]?\s*(feat\.?|ft\.?|featuring|with)\s+.*$", re.I)
_VARIOUS = re.compile(r"^(various(\s+artists?)?|va|v\.a\.)$", re.I)


def fold(s: str) -> str:
    """NFC, ASCII punctuation, no invisible characters."""
    return unicodedata.normalize("NFC", s or "").translate(_PUNCT)


def clean_segment(s: str, *, title: bool = False) -> str:
    """One folder or file name: safe on Linux, SMB and Windows, tidy to read."""
    s = fold(s)
    if title:
        s = _YT_ID.sub("", s)
        s = _VIDEO_NOISE.sub("", s)
        s = _VIDEO_NOISE_BARE.sub("", s)
    s = re.sub(r"[\x00-\x1f\x7f]", "", s)
    s = re.sub(r"\s*:\s*", " - ", s)          # "Haunted Ink: Original…" -> "Haunted Ink - Original…"
    s = re.sub(r"\s*[/\\|]\s*", " - ", s)     # separators between names
    s = s.replace('"', "'")
    s = re.sub(r"[?*<>]", "", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"( - )+", " - ", s)
    s = s.strip(" .-")
    if len(s) > MAX_SEGMENT:
        cut = s[:MAX_SEGMENT]
        s = (cut.rsplit(" ", 1)[0] if " " in cut[MAX_SEGMENT // 2:] else cut).rstrip(" .,-")
    return s or "Unknown"


def clean_album(album: str | None) -> str | None:
    """The album name, or None when the tag is junk (a format, a website, a placeholder)."""
    if not album:
        return None
    a = _FORMAT_NOISE.sub("", fold(album)).strip()
    if a.lower() in _JUNK_ALBUMS or _DOMAIN.match(a):
        return None
    return a


def is_various(name: str | None) -> bool:
    return bool(name and _VARIOUS.match(name.strip()))


def main_artist(artist: str, known: set[str] | None = None) -> str:
    """The artist a track is filed under: guests ("feat. X") dropped, and for a list of
    artists the first one — but only split on commas when that first name is an artist the
    library already knows, so "Tyler, The Creator" stays whole."""
    a = _FEAT.sub("", fold(artist)).strip()
    for sep in (";", " / ", " x ", " X "):
        if sep in a:
            a = a.split(sep)[0].strip()
    if "," in a and known:
        first = a.split(",")[0].strip()
        if first.lower() in known:
            a = first
    return a or fold(artist).strip()


@dataclass
class TrackTags:
    title: str | None
    artist: str | None
    albumartist: str | None
    album: str | None
    track: int | None
    disc: int | None
    compilation: bool = False


@dataclass
class AlbumInfo:
    """What the planner knows about the album a track belongs to."""
    tracks_in_library: int
    discs: int
    compilation: bool


def target_path(t: TrackTags, ext: str, rel_path: str, album: AlbumInfo | None,
                known_artists: set[str] | None = None) -> tuple[str, str]:
    """Where the file belongs, and which rule placed it there."""
    ext = ext.lower()
    if not t.artist and not t.albumartist:
        parts = [clean_segment(p) for p in rel_path.split("/")]
        if parts and parts[0] == UNTAGGED:
            parts = parts[1:]
        stem, _, _ = parts[-1].rpartition(".")
        parts[-1] = (stem or parts[-1]) + ext
        return "/".join([UNTAGGED] + parts), "untagged"

    title = clean_segment(t.title or rel_path.rsplit("/", 1)[-1].rsplit(".", 1)[0], title=True)
    album_name = clean_album(t.album)
    track_artist = main_artist(t.artist or t.albumartist or "", known_artists)

    if album_name and album and album.compilation:
        num = _number(t, album)
        performer = clean_segment(t.artist or track_artist)
        name = f"{num} - {performer} - {title}" if num else f"{performer} - {title}"
        return f"{VARIOUS}/{clean_segment(album_name)}/{name}{ext}", "compilation"

    folder_artist = clean_segment(
        t.albumartist if t.albumartist and not is_various(t.albumartist) else track_artist
    )
    single = (
        album_name is None
        or (album is not None and album.tracks_in_library == 1
            and _same(album_name, t.title or ""))
    )
    if single:
        return f"{folder_artist}/{SINGLES}/{title}{ext}", "single"

    num = _number(t, album)
    name = f"{num} - {title}" if num else title
    return f"{folder_artist}/{clean_segment(album_name)}/{name}{ext}", "album"


def _number(t: TrackTags, album: AlbumInfo | None) -> str:
    if not t.track:
        return ""
    if album and album.discs > 1:
        return f"{t.disc or 1}-{t.track:02d}"
    return f"{t.track:02d}"


def _same(a: str, b: str) -> bool:
    norm = lambda s: re.sub(r"\W+", "", fold(s).lower())
    return norm(a) == norm(b)
