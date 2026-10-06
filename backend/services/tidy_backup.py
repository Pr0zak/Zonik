"""Library backups for the tidy: a snapshot that a tidy can be undone from.

Each backup is a folder under data/backups/library-tidy-<timestamp>/ holding:

  disk-manifest.tsv.gz   every file and folder on the music share (type, path, size, mtime)
  tracks.csv.gz          every track: ID, path, tags, size, duration, favorite, rating, plays, playlists
  favorites.json         every favorite, with what is needed to re-find its track
  zonik.db               the whole database (SQLite online backup)
  tidy-restore.py        puts files and favorites back (preview by default, --apply to act)
  SUMMARY.json, SHA256SUMS
"""
from __future__ import annotations

import asyncio
import csv
import gzip
import hashlib
import json
import logging
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from backend.config import get_settings

log = logging.getLogger(__name__)

FILES = ("SUMMARY.json", "disk-manifest.tsv.gz", "tracks.csv.gz", "favorites.json", "zonik.db",
         "tidy-restore.py", "SHA256SUMS")
state: dict = {"state": "idle", "error": None, "name": None}
_task: asyncio.Task | None = None


def backups_dir() -> Path:
    return Path(get_settings().database.path).parent / "backups"


def _restore_script() -> Path:
    return Path(__file__).resolve().parents[2] / "scripts" / "tidy-restore.py"


def _snapshot(out: Path) -> dict:
    settings = get_settings()
    music = Path(settings.library.music_dir)
    out.mkdir(parents=True, exist_ok=False)

    n_files = n_dirs = total = 0
    with gzip.open(out / "disk-manifest.tsv.gz", "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["type", "path", "size", "mtime"])
        for root, dirs, files in os.walk(music):
            rel_root = os.path.relpath(root, music)
            for d in sorted(dirs):
                n_dirs += 1
                w.writerow(["dir", os.path.normpath(os.path.join(rel_root, d)), "", ""])
            for name in sorted(files):
                try:
                    st = os.lstat(os.path.join(root, name))
                except OSError:
                    continue
                n_files += 1
                total += st.st_size
                w.writerow(["file", os.path.normpath(os.path.join(rel_root, name)), st.st_size, int(st.st_mtime)])

    src = sqlite3.connect(settings.database.path)
    dst = sqlite3.connect(out / "zonik.db")
    src.backup(dst)
    dst.close()
    src.close()
    db = sqlite3.connect(f"file:{out / 'zonik.db'}?mode=ro", uri=True)

    rows = db.execute("""
        SELECT t.id, t.file_path, t.title, ar.name, al.title, t.track_number, t.disc_number,
               t.file_size, t.duration_seconds, t.rating, t.play_count,
               (SELECT 1 FROM favorites f WHERE f.track_id = t.id),
               (SELECT group_concat(p.name, ' | ') FROM playlist_tracks pt JOIN playlists p ON p.id = pt.playlist_id WHERE pt.track_id = t.id)
        FROM tracks t LEFT JOIN artists ar ON ar.id = t.artist_id LEFT JOIN albums al ON al.id = t.album_id
        ORDER BY t.file_path""").fetchall()
    with gzip.open(out / "tracks.csv.gz", "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["track_id", "file_path", "title", "artist", "album", "track_number", "disc_number", "file_size",
                    "duration_seconds", "rating", "play_count", "favorite", "playlists"])
        w.writerows(rows)

    favs = db.execute("""
        SELECT f.user_id, f.starred_at, f.track_id, t.file_path, t.title, ar.name, al.title, t.file_size,
               t.duration_seconds, f.album_id, al2.title, f.artist_id, ar2.name
        FROM favorites f
        LEFT JOIN tracks t ON t.id = f.track_id LEFT JOIN artists ar ON ar.id = t.artist_id
        LEFT JOIN albums al ON al.id = t.album_id LEFT JOIN albums al2 ON al2.id = f.album_id
        LEFT JOIN artists ar2 ON ar2.id = f.artist_id ORDER BY f.starred_at""").fetchall()
    keys = ["user_id", "starred_at", "track_id", "file_path", "title", "artist", "album", "file_size",
            "duration_seconds", "album_id", "album_title", "artist_id", "artist_name"]
    (out / "favorites.json").write_text(json.dumps([dict(zip(keys, r)) for r in favs], indent=1, ensure_ascii=False, default=str))

    summary = {
        "taken_at": datetime.now(timezone.utc).isoformat(),
        "music_root": str(music),
        "disk": {"files": n_files, "dirs": n_dirs, "bytes": total},
        "db": {
            "tracks": len(rows), "favorites": len(favs),
            "favorite_tracks": sum(1 for r in favs if r[2]),
            "playlists": db.execute("SELECT count(*) FROM playlists").fetchone()[0],
            "playlist_entries": db.execute("SELECT count(*) FROM playlist_tracks").fetchone()[0],
        },
    }
    db.close()
    (out / "SUMMARY.json").write_text(json.dumps(summary, indent=1))
    if _restore_script().exists():
        shutil.copy(_restore_script(), out / "tidy-restore.py")
    for extra in ("zonik.db-shm", "zonik.db-wal"):
        (out / extra).unlink(missing_ok=True)
    sums = []
    for name in FILES[:-1]:
        p = out / name
        if p.exists():
            sums.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {name}")
    (out / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    return summary


async def _run(name: str):
    try:
        state.update(state="running", error=None, name=name)
        await asyncio.to_thread(_snapshot, backups_dir() / name)
        state.update(state="done")
        log.info(f"tidy: backup {name} taken")
    except Exception as e:
        log.exception("tidy: backup failed")
        state.update(state="error", error=str(e))


def start() -> str | None:
    """Starts a backup unless one is running; returns its name."""
    global _task
    if _task and not _task.done():
        return None
    name = "library-tidy-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    _task = asyncio.create_task(_run(name))
    return name


def list_backups() -> list[dict]:
    out = []
    d = backups_dir()
    if not d.exists():
        return out
    for p in sorted(d.iterdir(), reverse=True):
        if not p.is_dir() or not p.name.startswith("library-tidy-"):
            continue
        try:
            summary = json.loads((p / "SUMMARY.json").read_text())
        except (OSError, ValueError):
            summary = None
        size = sum(f.stat().st_size for f in p.iterdir() if f.is_file())
        out.append({"name": p.name, "path": str(p), "size": size, "summary": summary,
                    "files": [f for f in FILES if (p / f).exists()]})
    return out


def file_path(name: str, filename: str) -> Path | None:
    """A file inside a backup, only for the known names (no path tricks)."""
    if filename not in FILES or "/" in name or not name.startswith("library-tidy-"):
        return None
    p = backups_dir() / name / filename
    return p if p.is_file() else None
