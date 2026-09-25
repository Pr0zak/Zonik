"""Library-health checks surfaced on the Music Map.

The map only shows what the analysis pipeline has produced, so gaps in that
pipeline (unanalysed tracks, a stale atlas, missing genres, bad loudness
readings) show up as holes or distortions in the plots. This lists them with
enough detail for the page to offer a fix.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.soundscape import _ensure_table

# Essentia reports integrated loudness in dB below full scale; anything above
# zero is a bad reading (clipped decode, broken file), not a loud master.
LOUDNESS_CEILING = 0.0


async def _count(db: AsyncSession, sql: str) -> int:
    return (await db.execute(text(sql))).scalar() or 0


async def map_health(db: AsyncSession) -> dict:
    await _ensure_table(db)
    total = await _count(db, "SELECT COUNT(*) FROM tracks")
    embedded = await _count(db, "SELECT COUNT(*) FROM track_embeddings e JOIN tracks t ON t.id = e.track_id")
    projected = await _count(db, "SELECT COUNT(*) FROM track_projection p JOIN tracks t ON t.id = p.track_id")
    unanalysed = await _count(db,
        "SELECT COUNT(*) FROM tracks t LEFT JOIN track_analysis a ON a.track_id = t.id WHERE a.track_id IS NULL")
    failed = await _count(db,
        "SELECT COUNT(*) FROM track_analysis a JOIN tracks t ON t.id = a.track_id WHERE a.bpm IS NULL")
    no_embedding = total - embedded
    no_genre = await _count(db, "SELECT COUNT(*) FROM tracks WHERE genre IS NULL OR TRIM(genre) = ''")

    rows = (await db.execute(text(
        "SELECT t.id, t.title, ar.name, t.album_id, a.loudness, t.format "
        "FROM track_analysis a JOIN tracks t ON t.id = a.track_id "
        "LEFT JOIN artists ar ON ar.id = t.artist_id "
        "WHERE a.loudness > :ceil ORDER BY a.loudness DESC"
    ), {"ceil": LOUDNESS_CEILING})).all()
    loudness_outliers = [{
        "track_id": r[0], "title": r[1], "artist": r[2], "album_id": r[3],
        "loudness": round(r[4], 1), "format": r[5],
    } for r in rows]

    return {
        "total": total,
        "embedded": embedded,
        "projected": projected,
        # Embedded tracks the atlas doesn't show yet: a rebuild picks them up.
        "unprojected": max(0, embedded - projected),
        "unanalysed": unanalysed,
        "analysis_failed": failed,
        "no_embedding": no_embedding,
        "no_genre": no_genre,
        "loudness_outliers": loudness_outliers,
    }
