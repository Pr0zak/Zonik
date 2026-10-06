#!/usr/bin/env python3
"""Put the music library back the way a library-tidy backup recorded it.

Run on CT 228 against a backup made before a tidy (a directory holding tracks.csv.gz and
favorites.json, under /opt/zonik/data/backups/). It only reports what it would do unless
given --apply.

    python3 tidy-restore.py /opt/zonik/data/backups/library-tidy-YYYYMMDD-HHMM            # preview
    python3 tidy-restore.py /opt/zonik/data/backups/library-tidy-YYYYMMDD-HHMM --apply    # do it

Files: for every track in the backup, finds where it is now (by track ID in the live database)
and moves it back to its recorded path, updating the database row, then removes folders left
empty. A track whose file is not where the database says is reported and skipped.

Favorites: re-adds any favorite in the backup that the live database no longer has, matching
the track by ID, then by recorded path, then by size + duration + title.

Stop zonik-web and zonik-worker first (`systemctl stop zonik-web zonik-worker`) so a scan does
not run halfway through, and start them again after.
"""
from __future__ import annotations

import csv
import gzip
import json
import os
import re
import sqlite3
import sys
import uuid

MUSIC = "/music"
DB = "/opt/zonik/data/zonik.db"


def norm(s):
    return re.sub(r"\W+", "", (s or "").lower())


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    backup = sys.argv[1]
    apply = "--apply" in sys.argv
    db = sqlite3.connect(DB)
    db.execute("PRAGMA foreign_keys = ON")

    with gzip.open(os.path.join(backup, "tracks.csv.gz"), "rt", encoding="utf-8") as f:
        recorded = list(csv.DictReader(f))
    live = {tid: path for tid, path in db.execute("SELECT id, file_path FROM tracks")}

    # --- Files ---
    moves, missing, blocked = [], [], []
    for row in recorded:
        tid, want = row["track_id"], row["file_path"]
        now = live.get(tid)
        if now is None or now == want:
            continue
        src, dst = os.path.join(MUSIC, now), os.path.join(MUSIC, want)
        if not os.path.exists(src):
            missing.append((tid, now))
        elif os.path.exists(dst):
            blocked.append((tid, now, want))
        else:
            moves.append((tid, now, want))
    print(f"files: {len(moves)} to move back, {len(missing)} missing on disk, {len(blocked)} blocked (target exists)")
    for tid, now, want in moves[:20]:
        print(f"  {now}  ->  {want}")
    for tid, now, want in blocked[:10]:
        print(f"  BLOCKED {now}  ->  {want} (something already there)")
    for tid, now in missing[:10]:
        print(f"  MISSING {now}")

    # --- Favorites ---
    favs = json.load(open(os.path.join(backup, "favorites.json"), encoding="utf-8"))
    have_t = {r[0] for r in db.execute("SELECT track_id FROM favorites WHERE track_id IS NOT NULL")}
    have_a = {r[0] for r in db.execute("SELECT album_id FROM favorites WHERE album_id IS NOT NULL")}
    have_r = {r[0] for r in db.execute("SELECT artist_id FROM favorites WHERE artist_id IS NOT NULL")}
    by_path = {p: t for t, p in live.items()}
    by_shape = {}
    for tid, size, dur, title in db.execute("SELECT id, file_size, duration_seconds, title FROM tracks"):
        if size and dur:
            by_shape.setdefault((size, round(dur)), []).append((tid, norm(title)))
    readd, unmatched = [], []
    for fv in favs:
        if fv.get("track_id"):
            tid = fv["track_id"] if fv["track_id"] in live else by_path.get(fv.get("file_path"))
            if tid is None and fv.get("file_size") and fv.get("duration_seconds"):
                hits = [t for t, tt in by_shape.get((fv["file_size"], round(fv["duration_seconds"])), []) if tt == norm(fv.get("title"))]
                tid = hits[0] if len(hits) == 1 else None
            if tid is None:
                unmatched.append(fv)
            elif tid not in have_t:
                readd.append(("track_id", tid, fv))
                have_t.add(tid)
        elif fv.get("album_id") and fv["album_id"] not in have_a:
            readd.append(("album_id", fv["album_id"], fv))
        elif fv.get("artist_id") and fv["artist_id"] not in have_r:
            readd.append(("artist_id", fv["artist_id"], fv))
    print(f"favorites: {len(favs)} in backup, {len(readd)} to re-add, {len(unmatched)} with no matching track")
    for fv in unmatched[:10]:
        print(f"  NO MATCH {fv.get('artist')} - {fv.get('title')} ({fv.get('file_path')})")

    if not apply:
        print("\nPreview only. Re-run with --apply to make these changes.")
        return 0

    done = 0
    for tid, now, want in moves:
        src, dst = os.path.join(MUSIC, now), os.path.join(MUSIC, want)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.rename(src, dst)
        db.execute("UPDATE tracks SET file_path = ? WHERE id = ?", (want, tid))
        db.commit()
        done += 1
        d = os.path.dirname(src)
        while d != MUSIC and os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d)
            d = os.path.dirname(d)
    for col, val, fv in readd:
        db.execute(f"INSERT INTO favorites (id, user_id, {col}, starred_at) VALUES (?, ?, ?, ?)",
                   (uuid.uuid4().hex, fv["user_id"], val, fv["starred_at"]))
    db.commit()
    print(f"\nMoved {done} files back and re-added {len(readd)} favorites. Run a library scan to refresh.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
