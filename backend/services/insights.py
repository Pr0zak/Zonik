"""Listening insights for the Music Map — when you listen, and what you've neglected."""
from __future__ import annotations

import logging
import random

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.taste_profile import TasteProfile

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

    # Dominant genre per cell (first genre token, most-played).
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
        g = (genre or "").split(";")[0].strip()
        if not g:
            continue
        cell = cell_counts.setdefault((wd, hr), {})
        cell[g] = cell.get(g, 0) + c
    for (wd, hr), counts in cell_counts.items():
        genre_grid[wd][hr] = max(counts.items(), key=lambda kv: kv[1])[0]

    return {"grid": grid, "genre_grid": genre_grid, "max": mx, "total": total}


async def neglected_gems(db: AsyncSession, limit: int = 40) -> dict:
    """Owned-but-never-played tracks, ranked by how close they sound to your taste
    centroid — the stuff you'd probably love but forgot you have."""
    tp = (await db.execute(select(TasteProfile).limit(1))).scalar_one_or_none()
    centroid = None
    if tp and tp.clap_centroid:
        centroid = np.frombuffer(tp.clap_centroid, dtype=np.float32)
        n = np.linalg.norm(centroid)
        centroid = centroid / n if n else None

    rows = (await db.execute(text(
        "SELECT t.id, t.title, ar.name, t.format, t.bitrate, t.album_id, e.embedding "
        "FROM tracks t JOIN track_embeddings e ON e.track_id = t.id "
        "LEFT JOIN artists ar ON ar.id = t.artist_id "
        "WHERE COALESCE(t.play_count, 0) = 0"
    ))).all()

    scored = []
    if centroid is not None:
        for r in rows:
            emb = np.frombuffer(r[6], dtype=np.float32)
            en = np.linalg.norm(emb)
            sim = float(np.dot(emb / en, centroid)) if en else 0.0
            scored.append((sim, r))
        scored.sort(key=lambda x: x[0], reverse=True)
    else:
        scored = [(0.0, r) for r in rows]

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

    return {"gems": gems, "has_centroid": centroid is not None, "pool": len(rows)}


async def audio_features(db: AsyncSession) -> dict:
    """Per-track Essentia features (parallel arrays) — powers the Camelot wheel
    (key/scale/bpm) and the Tempo×Punch grid (bpm/loudness)."""
    rows = (await db.execute(text(
        "SELECT t.id, t.title, ar.name, t.album_id, a.key, a.scale, a.bpm, "
        "       a.loudness, a.danceability, a.energy "
        "FROM tracks t JOIN track_analysis a ON a.track_id = t.id "
        "LEFT JOIN artists ar ON ar.id = t.artist_id "
        "WHERE a.bpm IS NOT NULL AND a.key IS NOT NULL"
    ))).all()
    cols = list(zip(*rows)) if rows else [[]] * 10
    return {
        "count": len(rows),
        "ids": list(cols[0]), "title": list(cols[1]), "artist": list(cols[2]), "album_id": list(cols[3]),
        "key": list(cols[4]), "scale": list(cols[5]), "bpm": list(cols[6]),
        "loudness": list(cols[7]), "danceability": list(cols[8]), "energy": list(cols[9]),
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
    return {"days": by_day, "max": mx, "total": sum(by_day.values())}
