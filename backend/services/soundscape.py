"""Sound Atlas — project per-track CLAP embeddings into a stable 2D map.

Distance on the map ≈ how alike two tracks SOUND. The projection (PCA→t-SNE) is
computed once and cached in `track_projection`; the map endpoint serves it with
per-point metadata for coloring/tooltips. A text query is "located" on the map by
averaging the positions of its nearest-sounding tracks (t-SNE has no transform()).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.embedding import TrackEmbedding

log = logging.getLogger(__name__)

MODEL = "clap-htsat-base/tsne-v1"

# Guards against overlapping recomputes (t-SNE is CPU-heavy, ~1-2 min for ~3k pts).
_computing = False


def is_computing() -> bool:
    return _computing


async def _ensure_table(db: AsyncSession) -> None:
    await db.execute(text(
        "CREATE TABLE IF NOT EXISTS track_projection ("
        "track_id TEXT PRIMARY KEY, x REAL NOT NULL, y REAL NOT NULL, "
        "model_version TEXT, computed_at TEXT)"
    ))


def _project_sync(mat: np.ndarray) -> np.ndarray:
    """PCA→t-SNE to 2D, normalized to [0,1] per axis. Runs in a worker thread."""
    from sklearn.manifold import TSNE
    n = mat.shape[0]
    # L2-normalize rows (CLAP lives in cosine space), then PCA-reduce to denoise + speed up.
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    mat = mat / np.where(norms == 0, 1.0, norms)
    if mat.shape[1] > 50 and n > 50:
        from sklearn.decomposition import PCA
        mat = PCA(n_components=50, random_state=42).fit_transform(mat)
    perplexity = float(min(40, max(5, n // 100)))
    try:
        xy = TSNE(n_components=2, perplexity=perplexity, init="pca", random_state=42).fit_transform(mat)
    except Exception as e:
        log.warning("[soundscape] t-SNE failed (%s) — falling back to PCA", e)
        from sklearn.decomposition import PCA
        xy = PCA(n_components=2, random_state=42).fit_transform(mat)
    xy = np.asarray(xy, dtype=np.float64)
    mn, mx = xy.min(axis=0), xy.max(axis=0)
    rng = np.where(mx - mn == 0, 1.0, mx - mn)
    return (xy - mn) / rng


async def compute_soundscape(db: AsyncSession) -> dict:
    """(Re)compute the 2D projection for all embedded tracks and cache it."""
    global _computing
    if _computing:
        return {"status": "already_running"}
    _computing = True
    try:
        rows = (await db.execute(select(TrackEmbedding.track_id, TrackEmbedding.embedding))).all()
        if len(rows) < 10:
            return {"points": 0, "error": "Not enough embedded tracks to map"}
        ids = [r[0] for r in rows]
        mat = np.stack([np.frombuffer(r[1], dtype=np.float32).astype(np.float32) for r in rows])
        log.info("[soundscape] projecting %d embeddings…", len(ids))
        xy = await asyncio.to_thread(_project_sync, mat)

        await _ensure_table(db)
        await db.execute(text("DELETE FROM track_projection"))
        now = datetime.now(timezone.utc).isoformat()
        params = [
            {"tid": ids[i], "x": float(xy[i, 0]), "y": float(xy[i, 1]), "mv": MODEL, "ca": now}
            for i in range(len(ids))
        ]
        # chunk inserts to keep statements small
        for i in range(0, len(params), 500):
            await db.execute(
                text("INSERT OR REPLACE INTO track_projection (track_id,x,y,model_version,computed_at) "
                     "VALUES (:tid,:x,:y,:mv,:ca)"),
                params[i:i + 500],
            )
        await db.commit()
        log.info("[soundscape] projected %d tracks", len(ids))
        return {"points": len(ids), "computed_at": now}
    finally:
        _computing = False


async def get_soundscape(db: AsyncSession) -> dict:
    """Serve the cached projection + per-point metadata as parallel arrays."""
    await _ensure_table(db)
    total = (await db.execute(text("SELECT COUNT(*) FROM tracks"))).scalar() or 0
    rows = (await db.execute(text(
        "SELECT p.track_id, p.x, p.y, p.computed_at, t.title, ar.name, t.genre, "
        "       t.play_count, t.last_played_at, t.album_id, a.energy "
        "FROM track_projection p "
        "JOIN tracks t ON t.id = p.track_id "
        "LEFT JOIN artists ar ON ar.id = t.artist_id "
        "LEFT JOIN track_analysis a ON a.track_id = p.track_id"
    ))).all()

    now = datetime.now(timezone.utc)
    ids, xs, ys, title, artist, genre, plays, recency, energy, album = ([] for _ in range(10))
    for r in rows:
        ids.append(r[0]); xs.append(r[1]); ys.append(r[2])
        title.append(r[4]); artist.append(r[5]); genre.append(r[6])
        plays.append(r[7] or 0)
        # days since last play; null = never played
        if r[8]:
            try:
                lp = datetime.fromisoformat(str(r[8]))
                if lp.tzinfo is None:
                    lp = lp.replace(tzinfo=timezone.utc)
                recency.append(round((now - lp).total_seconds() / 86400, 1))
            except Exception:
                recency.append(None)
        else:
            recency.append(None)
        album.append(r[9])
        energy.append(round(r[10], 3) if r[10] is not None else None)

    return {
        "model_version": MODEL,
        "computed_at": rows[0][3] if rows else None,
        "computing": _computing,
        "count": len(ids),
        "total_tracks": total,
        "ids": ids, "x": xs, "y": ys,
        "title": title, "artist": artist, "genre": genre,
        "play_count": plays, "recency_days": recency, "energy": energy, "album_id": album,
    }


async def locate_text(db: AsyncSession, query: str, k: int = 12) -> dict:
    """Place a text query ('rainy lo-fi jazz') on the map by averaging the
    positions of its nearest-sounding tracks, and return those tracks."""
    from backend.services.embeddings import generate_text_embedding
    from backend.services.similarity import find_similar_tracks

    q = (query or "").strip()
    if not q:
        return {"error": "Empty query"}
    emb = generate_text_embedding(q)
    if not emb:
        return {"error": "Could not embed query (CLAP text model unavailable)"}

    sims = await find_similar_tracks(db, emb, limit=k)
    if not sims:
        return {"error": "No matches"}
    ids = [s["track_id"] for s in sims]
    await _ensure_table(db)
    placeholders = ",".join(f":id{i}" for i in range(len(ids)))
    pos = (await db.execute(
        text(f"SELECT track_id, x, y FROM track_projection WHERE track_id IN ({placeholders})"),
        {f"id{i}": ids[i] for i in range(len(ids))},
    )).all()
    if not pos:
        return {"error": "Matches aren't on the map yet — recompute the atlas."}
    px = sum(p[1] for p in pos) / len(pos)
    py = sum(p[2] for p in pos) / len(pos)
    return {"x": px, "y": py, "query": q, "tracks": sims, "track_ids": [p[0] for p in pos]}
