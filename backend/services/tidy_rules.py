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
from dataclasses import asdict, dataclass, field, fields

VARIOUS = "Various Artists"
SINGLES = "Singles"
UNTAGGED = "_Untagged"
MAX_SEGMENT = 120  # characters; well under the 255-byte limit even for multi-byte scripts


@dataclass
class TidyOptions:
    """Everything the Library Tidy page lets you change. Defaults are the decisions of
    2026-10-05 (plans/library-tidy.md)."""
    singles_folder: str = SINGLES
    various_folder: str = VARIOUS
    untagged_folder: str = UNTAGGED
    album_year: bool = False                 # "Album (2021)"
    disc_style: str = "prefix"               # "prefix": 2-03 - Title; "folder": Disc 2/03 - Title
    singles_from_same_name_album: bool = True
    detect_compilations: bool = True
    untagged_mode: str = "folder"            # "folder", "filename" (guess Artist - Title), "leave"
    use_album_artist: bool = True
    drop_featured: bool = True
    split_artist_lists: str = "known"        # "known", "always", "never"
    merge_case_variants: bool = True
    ascii_punctuation: bool = True
    strip_video_clutter: bool = True
    max_name_length: int = MAX_SEGMENT
    exclude_folders: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict | None) -> "TidyOptions":
        """Known keys of the right type; anything else falls back to its default."""
        out = cls()
        for f in fields(cls):
            if d and f.name in d and isinstance(d[f.name], type(getattr(out, f.name))):
                setattr(out, f.name, d[f.name])
        out.max_name_length = max(40, min(out.max_name_length, 200))
        if out.disc_style not in ("prefix", "folder"):
            out.disc_style = "prefix"
        if out.untagged_mode not in ("folder", "filename", "leave"):
            out.untagged_mode = "folder"
        if out.split_artist_lists not in ("known", "always", "never"):
            out.split_artist_lists = "known"
        out.exclude_folders = [x.strip().strip("/") for x in out.exclude_folders if isinstance(x, str) and x.strip()]
        for name in ("singles_folder", "various_folder", "untagged_folder"):
            setattr(out, name, _plain(getattr(out, name)) or getattr(cls, name))
        return out

    def to_dict(self) -> dict:
        return asdict(self)


def _plain(s: str) -> str:
    """A folder name typed on the settings page, made safe."""
    return re.sub(r"[\x00-\x1f/\\:?*<>|\"]", "", s or "").strip(" .")

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


def fold(s: str, ascii_punctuation: bool = True) -> str:
    """NFC, ASCII punctuation (unless turned off), no invisible characters."""
    s = unicodedata.normalize("NFC", s or "")
    if ascii_punctuation:
        return s.translate(_PUNCT)
    return re.sub(r"[\u200b\u200c\u200d\ufeff]", "", s).replace("\u00a0", " ")


def clean_segment(s: str, *, title: bool = False, opts: TidyOptions | None = None) -> str:
    """One folder or file name: safe on Linux, SMB and Windows, tidy to read."""
    o = opts or TidyOptions()
    s = fold(s, o.ascii_punctuation)
    if title and o.strip_video_clutter:
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
    limit = o.max_name_length
    if len(s) > limit:
        cut = s[:limit]
        s = (cut.rsplit(" ", 1)[0] if " " in cut[limit // 2:] else cut).rstrip(" .,-")
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


def main_artist(artist: str, known: set[str] | None = None, opts: TidyOptions | None = None) -> str:
    """The artist a track is filed under: guests ("feat. X") dropped, and for a list of
    artists the first one. With split_artist_lists "known" (the default) a comma list is only
    split when its first name is an artist the library already knows, so "Tyler, The Creator"
    stays whole."""
    o = opts or TidyOptions()
    a = fold(artist).strip()
    if o.drop_featured:
        a = _FEAT.sub("", a).strip()
    if o.split_artist_lists != "never":
        for sep in (";", " / ", " x ", " X "):
            if sep in a:
                a = a.split(sep)[0].strip()
        if "," in a:
            first = a.split(",")[0].strip()
            if o.split_artist_lists == "always" or (known and first.lower() in known):
                a = first
    return a.strip(" ,") or fold(artist).strip()


@dataclass
class TrackTags:
    title: str | None
    artist: str | None
    albumartist: str | None
    album: str | None
    track: int | None
    disc: int | None
    compilation: bool = False
    year: int | None = None


@dataclass
class AlbumInfo:
    """What the planner knows about the album a track belongs to."""
    tracks_in_library: int
    discs: int
    compilation: bool


def folder_artist(t: TrackTags, known: set[str] | None, opts: TidyOptions) -> str:
    """The artist folder: the album-artist tag (cleaned the same way) unless turned off or it
    says "Various", else the track's main artist."""
    if opts.use_album_artist and t.albumartist and not is_various(t.albumartist):
        return main_artist(t.albumartist, known, opts)
    return main_artist(t.artist or t.albumartist or "", known, opts)


def target_path(t: TrackTags, ext: str, rel_path: str, album: AlbumInfo | None,
                known_artists: set[str] | None = None, opts: TidyOptions | None = None) -> tuple[str, str]:
    """Where the file belongs, and which rule placed it there."""
    o = opts or TidyOptions()
    seg = lambda s, title=False: clean_segment(s, title=title, opts=o)
    ext = ext.lower()
    if any(rel_path == x or rel_path.startswith(x + "/") for x in o.exclude_folders):
        return rel_path, "excluded"
    if not t.artist and not t.albumartist:
        guess = _guess_from_filename(rel_path) if o.untagged_mode == "filename" else None
        if guess:
            t = TrackTags(title=guess[1], artist=guess[0], albumartist=None, album=None,
                          track=None, disc=None)
        elif o.untagged_mode == "leave":
            return rel_path, "untagged"
        else:
            parts = [seg(p) for p in rel_path.split("/")]
            if parts and parts[0] == o.untagged_folder:
                parts = parts[1:]
            stem, _, _ = parts[-1].rpartition(".")
            parts[-1] = (stem or parts[-1]) + ext
            return "/".join([o.untagged_folder] + parts), "untagged"

    title = seg(t.title or rel_path.rsplit("/", 1)[-1].rsplit(".", 1)[0], True)
    album_name = clean_album(t.album)
    album_dir = seg(album_name + (f" ({t.year})" if o.album_year and t.year else "")) if album_name else None

    if album_name and album and album.compilation and o.detect_compilations:
        num, disc_dir = _number(t, album, o)
        performer = seg(t.artist or main_artist(t.albumartist or "", known_artists, o))
        name = f"{num} - {performer} - {title}" if num else f"{performer} - {title}"
        return "/".join([o.various_folder, album_dir] + disc_dir + [name + ext]), "compilation"

    artist_dir = seg(folder_artist(t, known_artists, o))
    single = (
        album_name is None
        or (o.singles_from_same_name_album and album is not None and album.tracks_in_library == 1
            and _same(album_name, t.title or ""))
    )
    if single:
        return f"{artist_dir}/{o.singles_folder}/{title}{ext}", "single"

    num, disc_dir = _number(t, album, o)
    name = f"{num} - {title}" if num else title
    return "/".join([artist_dir, album_dir] + disc_dir + [name + ext]), "album"


def _guess_from_filename(rel_path: str) -> tuple[str, str] | None:
    """("Artist", "Title") from a file named "NN - Artist - Title" or "Artist - Title"."""
    stem = rel_path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    stem = re.sub(r"^\d{1,3}[\s.\-]+", "", stem.replace("_", " "))
    parts = re.split(r"\s+[-\u2013\u2014]\s+", stem, maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        return parts[0].strip(), parts[1].strip()
    return None


def _number(t: TrackTags, album: AlbumInfo | None, o: TidyOptions) -> tuple[str, list[str]]:
    """The file's number prefix, and a "Disc N" folder when discs are folders."""
    multi = album is not None and album.discs > 1
    disc_dir = [f"Disc {t.disc or 1}"] if multi and o.disc_style == "folder" else []
    if not t.track:
        return "", disc_dir
    if multi and o.disc_style == "prefix":
        return f"{t.disc or 1}-{t.track:02d}", disc_dir
    return f"{t.track:02d}", disc_dir


def _same(a: str, b: str) -> bool:
    norm = lambda s: re.sub(r"\W+", "", fold(s).lower())
    return norm(a) == norm(b)
