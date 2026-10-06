"""Library tidy planner: where every track's file should go, as a dry run.

Reads each file's tags (cached by path, size and mtime, since a full read over NFS takes
minutes), groups tracks into albums, applies tidy_rules, and records the result in
data/tidy-plan.json for the Library Tidy page to review. Nothing on disk changes here; moving
is a separate, journalled step (plans/library-tidy.md).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import mutagen
from sqlalchemy import func, select

from backend.config import get_settings
from backend.database import async_session
from backend.models.artist import Artist
from backend.models.favorite import Favorite
from backend.models.playlist import PlaylistTrack
from backend.models.track import Track
from backend.services.tidy_rules import (
    AlbumInfo, TrackTags, clean_album, clean_segment, is_various, main_artist, target_path,
)

log = logging.getLogger(__name__)

# Shown on the page while a plan is being built. One process, one planner at a time.
state: dict = {"state": "idle", "done": 0, "total": 0, "error": None, "started_at": None}
_task: asyncio.Task | None = None


def _data_dir() -> Path:
    return Path(get_settings().database.path).parent


def plan_path() -> Path:
    return _data_dir() / "tidy-plan.json"


def _cache_path() -> Path:
    return _data_dir() / "tidy-tags-cache.json"


def _first(audio, key):
    v = audio.get(key)
    if not v:
        return None
    return str(v[0] if isinstance(v, list) else v).strip() or None


def _int(v):
    try:
        return int(str(v).split("/")[0])
    except (TypeError, ValueError):
        return None


def read_tags(path: Path) -> dict | None:
    """The tags the rules need, straight from the file (the database folds the album artist
    into the track artist, and its titles can be guesses from the file name)."""
    try:
        audio = mutagen.File(str(path), easy=True)
    except Exception:
        return None
    if audio is None:
        return None
    disc_raw = _first(audio, "discnumber")
    disc_total = _int(_first(audio, "disctotal") or _first(audio, "totaldiscs")
                      or (disc_raw.split("/")[1] if disc_raw and "/" in disc_raw else None))
    comp = (_first(audio, "compilation") or "").lower() in ("1", "true", "yes")
    return {
        "title": _first(audio, "title"),
        "artist": _first(audio, "artist"),
        "albumartist": _first(audio, "albumartist"),
        "album": _first(audio, "album"),
        "track": _int(_first(audio, "tracknumber")),
        "disc": _int(disc_raw),
        "disctotal": disc_total,
        "compilation": comp,
    }


def _read_all(music_dir: Path, rel_paths: list[str]) -> dict[str, dict | None]:
    """Tags for every path, from the cache where the file has not changed. Runs in a thread."""
    try:
        cache = json.loads(_cache_path().read_text())
    except (OSError, ValueError):
        cache = {}
    out: dict[str, dict | None] = {}
    fresh: dict[str, dict] = {}
    for i, rel in enumerate(rel_paths):
        p = music_dir / rel
        try:
            st = p.stat()
        except OSError:
            out[rel] = None
            state["done"] = i + 1
            continue
        key = f"{st.st_size}:{int(st.st_mtime)}"
        hit = cache.get(rel)
        tags = hit["tags"] if hit and hit.get("key") == key else read_tags(p)
        out[rel] = tags
        fresh[rel] = {"key": key, "tags": tags}
        state["done"] = i + 1
    try:
        _cache_path().write_text(json.dumps(fresh))
    except OSError as e:
        log.warning(f"tidy: could not write tag cache: {e}")
    return out


async def build_plan() -> dict:
    settings = get_settings()
    music_dir = Path(settings.library.music_dir)
    async with async_session() as db:
        tracks = (await db.execute(select(Track.id, Track.file_path))).all()
        favs = {r[0] for r in (await db.execute(select(Favorite.track_id).where(Favorite.track_id.is_not(None)))).all()}
        in_pl = dict((await db.execute(
            select(PlaylistTrack.track_id, func.count()).group_by(PlaylistTrack.track_id))).all())
        artist_names = {r[0].lower() for r in (await db.execute(select(Artist.name))).all() if r[0]}

    state.update(total=len(tracks), done=0)
    tags_by_path = await asyncio.to_thread(_read_all, music_dir, [t.file_path for t in tracks])

    # Names that stand alone as an artist, so a comma list is only split at a real one.
    known = {n for n in artist_names if "," not in n}
    for tg in tags_by_path.values():
        if tg and tg.get("albumartist") and "," not in tg["albumartist"]:
            known.add(tg["albumartist"].lower())

    # Pass 1: per-track facts the album grouping needs.
    rows = []
    for tid, rel in tracks:
        tg = tags_by_path.get(rel)
        tt = TrackTags(
            title=tg and tg["title"], artist=tg and tg["artist"], albumartist=tg and tg["albumartist"],
            album=tg and tg["album"], track=tg and tg["track"], disc=tg and tg["disc"],
            compilation=bool(tg and tg["compilation"]),
        )
        album = clean_album(tt.album)
        lead = main_artist(tt.artist or tt.albumartist or "", known) if (tt.artist or tt.albumartist) else ""
        folder_artist = tt.albumartist if tt.albumartist and not is_various(tt.albumartist) else lead
        rows.append(dict(id=tid, rel=rel, tags=tt, raw=tg, album=album, lead=lead, folder_artist=folder_artist))

    # Compilations: a folder of one album where the album artist says so, the files say so,
    # or there is no album artist and no single artist has most of the tracks.
    by_folder_album = defaultdict(list)
    for r in rows:
        if r["album"]:
            by_folder_album[(os.path.dirname(r["rel"]), r["album"].lower())].append(r)
    compilation_ids = set()
    for group in by_folder_album.values():
        flagged = any(r["tags"].compilation or is_various(r["tags"].albumartist) for r in group)
        no_aa = not any(r["tags"].albumartist for r in group)
        leads = Counter(r["lead"].lower() for r in group if r["lead"])
        mixed = no_aa and len(group) >= 4 and len(leads) >= 3 and leads.most_common(1)[0][1] / len(group) < 0.5
        if flagged or mixed:
            compilation_ids.update(r["id"] for r in group)

    # Albums as the new layout sees them, for track counts and disc counts.
    album_groups = defaultdict(list)
    for r in rows:
        if r["album"]:
            key = ("~various" if r["id"] in compilation_ids else r["folder_artist"].lower(), r["album"].lower())
            album_groups[key].append(r)
    infos = {}
    for key, group in album_groups.items():
        discs = max([r["tags"].disc or 1 for r in group] + [(r["raw"] or {}).get("disctotal") or 1 for r in group])
        info = AlbumInfo(tracks_in_library=len(group), discs=discs, compilation=key[0] == "~various")
        for r in group:
            infos[r["id"]] = info

    # Pass 2: targets.
    moves = []
    for r in rows:
        ext = os.path.splitext(r["rel"])[1]
        if r["raw"] is None:
            moves.append(dict(r, to=r["rel"], rule="unreadable", status="skip",
                              note="tags could not be read; left where it is"))
            continue
        to, rule = target_path(r["tags"], ext, r["rel"], infos.get(r["id"]), known)
        moves.append(dict(r, to=to, rule=rule, status="move"))

    # One spelling per artist folder: "ILLIT" and "Illit" become whichever has more tracks.
    spellings = defaultdict(Counter)
    for m in moves:
        spellings[m["to"].split("/")[0].lower()][m["to"].split("/")[0]] += 1
    for m in moves:
        head, _, rest = m["to"].partition("/")
        best = spellings[head.lower()].most_common(1)[0][0]
        if best != head:
            m["to"] = f"{best}/{rest}"

    # Conflicts: two tracks heading for one name, or a file already there that is not moving.
    current = {m["rel"].lower() for m in moves}
    staying = {m["rel"].lower() for m in moves if m["to"] == m["rel"]}
    dest = Counter(m["to"].lower() for m in moves if m["status"] == "move")
    for m in moves:
        if m["status"] != "move":
            continue
        if m["to"] == m["rel"]:
            m["status"] = "unchanged"
        elif dest[m["to"].lower()] > 1:
            m["status"], m["note"] = "conflict", "another track would get the same name (often a duplicate copy)"
        elif m["to"].lower() in staying or (m["to"].lower() not in current and (music_dir / m["to"]).exists()):
            m["status"], m["note"] = "conflict", "a file is already at that name"

    out = []
    for m in moves:
        out.append({
            "track_id": m["id"], "from": m["rel"], "to": m["to"], "rule": m["rule"], "status": m["status"],
            "note": m.get("note"), "favorite": m["id"] in favs, "playlists": in_pl.get(m["id"], 0),
            "title": m["tags"].title, "artist": m["tags"].artist, "album": m["tags"].album,
        })
    summary = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "tracks": len(out),
        "status": dict(Counter(m["status"] for m in out)),
        "rule": dict(Counter(m["rule"] for m in out if m["status"] == "move")),
        "favorites_moving": sum(1 for m in out if m["status"] == "move" and m["favorite"]),
    }
    plan = {"summary": summary, "moves": out}
    plan_path().write_text(json.dumps(plan, ensure_ascii=False))
    return summary


async def _run():
    try:
        state.update(state="reading", error=None, started_at=datetime.now(timezone.utc).isoformat())
        await build_plan()
        state.update(state="done")
    except Exception as e:  # surfaced on the page
        log.exception("tidy: plan failed")
        state.update(state="error", error=str(e))


def start() -> bool:
    """Starts building a plan unless one is already being built."""
    global _task
    if _task and not _task.done():
        return False
    _task = asyncio.create_task(_run())
    return True


def load_plan() -> dict | None:
    try:
        return json.loads(plan_path().read_text())
    except (OSError, ValueError):
        return None
