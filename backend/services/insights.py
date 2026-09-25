"""Listening insights for the Music Map — when you listen, and what you've neglected."""
from __future__ import annotations

import logging
import random
import re
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.taste_profile import TasteProfile
from backend.services.genres import genre_family

log = logging.getLogger(__name__)


async def listening_clock(db: AsyncSession) -> dict:
    """7×24 weekday×hour grid of play counts (+ dominant genre per cell).

    Times use the server's local timezone via SQLite's 'localtime' modifier.
    """
    grid = [[0] * 24 for _ in range(7)]
    total = 0
    mx = 0
    rows = (await db.execute(text(
        "SELECT CAST(strftime('%w', played_at, 'localtime') AS INTEGER) wd, "
        "       CAST(strftime('%H', played_at, 'localtime') AS INTEGER) hr, COUNT(*) c "
        "FROM play_history WHERE played_at IS NOT NULL GROUP BY wd, hr"
    ))).all()
    for wd, hr, c in rows:
        if wd is None or hr is None:
            continue
        grid[wd][hr] = c
        total += c
        mx = max(mx, c)

    # Dominant genre family per cell (most-played).
    genre_grid = [[None] * 24 for _ in range(7)]
    cell_counts: dict[tuple, dict] = {}
    grows = (await db.execute(text(
        "SELECT CAST(strftime('%w', ph.played_at, 'localtime') AS INTEGER) wd, "
        "       CAST(strftime('%H', ph.played_at, 'localtime') AS INTEGER) hr, t.genre, COUNT(*) c "
        "FROM play_history ph JOIN tracks t ON t.id = ph.track_id "
        "WHERE ph.played_at IS NOT NULL AND t.genre IS NOT NULL "
        "GROUP BY wd, hr, t.genre"
    ))).all()
    for wd, hr, genre, c in grows:
        if wd is None or hr is None:
            continue
        g = genre_family(genre)
        if g in ("Unknown", "Other"):
            continue
        cell = cell_counts.setdefault((wd, hr), {})
        cell[g] = cell.get(g, 0) + c
    for (wd, hr), counts in cell_counts.items():
        genre_grid[wd][hr] = max(counts.items(), key=lambda kv: kv[1])[0]

    return {"grid": grid, "genre_grid": genre_grid, "max": mx, "total": total}


# Holiday songs top the "sounds like you" ranking all year round; keep them for
# the season. Matched against title, album and genre.
_HOLIDAY = re.compile(
    r"christmas|xmas|x-mas|holiday|santa|jingle|sleigh|\bnoel\b|navidad|silent night|"
    r"let it snow|mistletoe|rudolph|reindeer|winter wonderland|yuletide|snowman|o holy night",
    re.I,
)
_FEAT = re.compile(r"\s*[\(\[][^\)\]]*(feat\.?|ft\.?|featuring|with|remaster|version|edit|mono|stereo|live|explicit|clean)[^\)\]]*[\)\]]", re.I)
_DASH_SUFFIX = re.compile(r"\s+-\s+.*(remaster|version|edit|mix|live|mono|stereo).*$", re.I)
_BRACKETS = re.compile(r"[\(\[][^\)\]]*[\)\]]")
_NON_WORD = re.compile(r"[^\w]+")

_FORMAT_RANK = {"flac": 3, "alac": 3, "wav": 3, "aiff": 3, "m4a": 1, "aac": 1, "opus": 1, "ogg": 1, "mp3": 0}


def _recording_key(title: str | None, artist: str | None) -> tuple[str, str]:
    """Normalised (title, artist) so FLAC/MP3 copies and '(feat. …)' variants of
    one recording collapse together."""
    t = (title or "").lower()
    t = _FEAT.sub("", t)
    t = _DASH_SUFFIX.sub("", t)
    t = _BRACKETS.sub("", t)
    t = _NON_WORD.sub(" ", t).strip()
    a = (artist or "").lower().split(",")[0].split("&")[0].split(" feat")[0]
    a = _NON_WORD.sub(" ", a).strip()
    return t, a


def _quality(fmt: str | None, bitrate: int | None) -> tuple[int, int]:
    return _FORMAT_RANK.get((fmt or "").lower(), 0), bitrate or 0


def _holiday_season(now: datetime | None = None) -> bool:
    return (now or datetime.now()).month in (11, 12)


async def _ensure_dismissed_table(db: AsyncSession) -> None:
    # Ad-hoc like track_projection: upgrade.sh doesn't run alembic.
    await db.execute(text(
        "CREATE TABLE IF NOT EXISTS gem_dismissed (track_id TEXT PRIMARY KEY, dismissed_at TEXT)"
    ))


async def dismiss_gem(db: AsyncSession, track_id: str) -> dict:
    await _ensure_dismissed_table(db)
    await db.execute(
        text("INSERT OR REPLACE INTO gem_dismissed (track_id, dismissed_at) VALUES (:tid, :at)"),
        {"tid": track_id, "at": datetime.now(timezone.utc).isoformat()},
    )
    await db.commit()
    return {"ok": True}


async def neglected_gems(db: AsyncSession, limit: int = 40) -> dict:
    """Owned-but-never-played tracks, ranked by how close they sound to your taste
    centroid — the stuff you'd probably love but forgot you have.

    Copies of one recording collapse to the best-quality file, and a recording
    you've already played in another copy doesn't count as neglected. Holiday
    songs are held back outside Nov–Dec, and dismissed tracks never return."""
    tp = (await db.execute(select(TasteProfile).limit(1))).scalar_one_or_none()
    centroid = None
    if tp and tp.clap_centroid:
        centroid = np.frombuffer(tp.clap_centroid, dtype=np.float32)
        n = np.linalg.norm(centroid)
        centroid = centroid / n if n else None

    await _ensure_dismissed_table(db)
    rows = (await db.execute(text(
        "SELECT t.id, t.title, ar.name, t.format, t.bitrate, t.album_id, e.embedding, "
        "       t.genre, al.title "
        "FROM tracks t JOIN track_embeddings e ON e.track_id = t.id "
        "LEFT JOIN artists ar ON ar.id = t.artist_id "
        "LEFT JOIN albums al ON al.id = t.album_id "
        "WHERE COALESCE(t.play_count, 0) = 0 "
        "AND t.id NOT IN (SELECT track_id FROM gem_dismissed)"
    ))).all()

    played_keys = {
        _recording_key(r[0], r[1]) for r in (await db.execute(text(
            "SELECT t.title, ar.name FROM tracks t LEFT JOIN artists ar ON ar.id = t.artist_id "
            "WHERE COALESCE(t.play_count, 0) > 0"
        ))).all()
    }

    in_season = _holiday_season()
    hidden_seasonal = 0
    deduped = 0
    best: dict[tuple[str, str], tuple] = {}
    for r in rows:
        if not in_season and any(_HOLIDAY.search(f or "") for f in (r[1], r[7], r[8])):
            hidden_seasonal += 1
            continue
        key = _recording_key(r[1], r[2])
        if key in played_keys:
            deduped += 1
            continue
        cur = best.get(key)
        if cur is None:
            best[key] = r
        else:
            deduped += 1
            if _quality(r[3], r[4]) > _quality(cur[3], cur[4]):
                best[key] = r
    candidates = list(best.values())

    scored = []
    if centroid is not None:
        for r in candidates:
            emb = np.frombuffer(r[6], dtype=np.float32)
            en = np.linalg.norm(emb)
            sim = float(np.dot(emb / en, centroid)) if en else 0.0
            scored.append((sim, r))
        scored.sort(key=lambda x: x[0], reverse=True)
    else:
        scored = [(0.0, r) for r in candidates]

    # Draw a fresh, varied set from the best-matching pool so the mix isn't
    # identical every time (was the deterministic top-N). Pool = the strongest
    # matches; random-sample `limit` from it, then show them best-first.
    pool = scored[:min(len(scored), max(limit * 3, 200))]
    chosen = random.sample(pool, min(limit, len(pool)))
    chosen.sort(key=lambda x: x[0], reverse=True)

    gems = [{
        "track_id": r[0], "title": r[1], "artist": r[2],
        "format": r[3], "bitrate": r[4], "album_id": r[5],
        "match": round(sim, 4),
    } for sim, r in chosen]

    return {
        "gems": gems, "has_centroid": centroid is not None, "pool": len(candidates),
        "deduped": deduped, "hidden_seasonal": hidden_seasonal,
    }


async def audio_features(db: AsyncSession) -> dict:
    """Per-track Essentia features (parallel arrays) — powers the Camelot wheel
    (key/scale/bpm) and the Tempo×Punch grid (bpm/loudness)."""
    rows = (await db.execute(text(
        "SELECT t.id, t.title, ar.name, t.album_id, a.key, a.scale, a.bpm, "
        "       a.loudness, a.danceability, a.energy, t.genre, COALESCE(t.play_count, 0) "
        "FROM tracks t JOIN track_analysis a ON a.track_id = t.id "
        "LEFT JOIN artists ar ON ar.id = t.artist_id "
        "WHERE a.bpm IS NOT NULL AND a.key IS NOT NULL"
    ))).all()
    cols = list(zip(*rows)) if rows else [[]] * 12
    return {
        "count": len(rows),
        "ids": list(cols[0]), "title": list(cols[1]), "artist": list(cols[2]), "album_id": list(cols[3]),
        "key": list(cols[4]), "scale": list(cols[5]), "bpm": list(cols[6]),
        "loudness": list(cols[7]), "danceability": list(cols[8]), "energy": list(cols[9]),
        "family": [genre_family(g) for g in cols[10]], "play_count": list(cols[11]),
    }


async def streak_calendar(db: AsyncSession, days: int = 371) -> dict:
    """Daily play counts for a GitHub-style contribution heatmap (server-local dates)."""
    rows = (await db.execute(text(
        "SELECT date(played_at, 'localtime') d, COUNT(*) c "
        "FROM play_history WHERE played_at IS NOT NULL "
        "AND played_at >= datetime('now', :since) GROUP BY d"
    ), {"since": f"-{days} days"})).all()
    by_day = {r[0]: r[1] for r in rows if r[0]}
    mx = max(by_day.values()) if by_day else 0
    # First play ever recorded, so the calendar can skip the weeks before
    # play tracking began instead of drawing them as empty.
    first_day = (await db.execute(text(
        "SELECT date(MIN(played_at), 'localtime') FROM play_history WHERE played_at IS NOT NULL"
    ))).scalar()
    return {"days": by_day, "max": mx, "total": sum(by_day.values()), "first_day": first_day}
