"""Vibe similarity search using embeddings."""
from __future__ import annotations

import logging

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models.embedding import TrackEmbedding
from backend.models.track import Track
from backend.services.embeddings import embedding_from_bytes, cosine_similarity

log = logging.getLogger(__name__)


async def find_similar_tracks(
    db: AsyncSession,
    seed_embedding: bytes,
    limit: int = 20,
    exclude_track_ids: set[str] | None = None,
) -> list[dict]:
    """Find tracks with similar vibes using cosine similarity.

    Returns list of {track_id, title, artist, similarity} sorted by similarity.
    """
    result = await db.execute(select(TrackEmbedding))
    all_embeddings = result.scalars().all()

    exclude = exclude_track_ids or set()
    scored = []

    for emb in all_embeddings:
        if emb.track_id in exclude:
            continue
        sim = cosine_similarity(seed_embedding, emb.embedding)
        scored.append((sim, emb.track_id))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:limit]

    # Fetch track details
    track_ids = [tid for _, tid in top]
    if not track_ids:
        return []

    tracks_result = await db.execute(
        select(Track).options(selectinload(Track.artist), selectinload(Track.album))
        .where(Track.id.in_(track_ids))
    )
    tracks_map = {t.id: t for t in tracks_result.scalars().all()}

    results = []
    for sim, tid in top:
        track = tracks_map.get(tid)
        if track:
            results.append({
                "track_id": tid,
                "title": track.title,
                "artist": track.artist.name if track.artist else None,
                "album": track.album.title if track.album else None,
                "similarity": round(sim, 4),
            })

    return results


async def echo_match(db: AsyncSession, track_id: str, limit: int = 20) -> list[dict]:
    """Find tracks with similar vibes to a seed track (Echo Match)."""
    result = await db.execute(
        select(TrackEmbedding).where(TrackEmbedding.track_id == track_id)
    )
    seed = result.scalar_one_or_none()
    if not seed:
        return []

    return await find_similar_tracks(db, seed.embedding, limit=limit, exclude_track_ids={track_id})


async def text_vibe_search(db: AsyncSession, query: str, limit: int = 20) -> list[dict]:
    """Search for tracks matching a text description (e.g., 'chill ambient beats')."""
    from backend.services.embeddings import generate_text_embedding

    text_emb = generate_text_embedding(query)
    if not text_emb:
        return []

    return await find_similar_tracks(db, text_emb, limit=limit)


async def steady_vibes_playlist(
    db: AsyncSession,
    seed_track_id: str,
    length: int = 20,
    similarity_threshold: float = 0.7,
) -> list[dict]:
    """Generate a playlist maintaining consistent energy/mood (Steady Vibes).

    Walks through the embedding space, picking tracks that are similar
    to the current position but haven't been used yet.
    """
    # Get seed embedding
    result = await db.execute(
        select(TrackEmbedding).where(TrackEmbedding.track_id == seed_track_id)
    )
    seed = result.scalar_one_or_none()
    if not seed:
        return []

    # Get all embeddings
    all_result = await db.execute(select(TrackEmbedding))
    all_embeddings = {e.track_id: e.embedding for e in all_result.scalars().all()}

    used = {seed_track_id}
    playlist_ids = [seed_track_id]
    current_emb = seed.embedding

    for _ in range(length - 1):
        best_id = None
        best_sim = -1.0

        for tid, emb in all_embeddings.items():
            if tid in used:
                continue
            sim = cosine_similarity(current_emb, emb)
            if sim >= similarity_threshold and sim > best_sim:
                best_sim = sim
                best_id = tid

        if best_id is None:
            # Lower threshold and try again
            for tid, emb in all_embeddings.items():
                if tid in used:
                    continue
                sim = cosine_similarity(current_emb, emb)
                if sim > best_sim:
                    best_sim = sim
                    best_id = tid

        if best_id is None:
            break

        used.add(best_id)
        playlist_ids.append(best_id)
        current_emb = all_embeddings[best_id]

    # Fetch track details
    tracks_result = await db.execute(
        select(Track).options(selectinload(Track.artist))
        .where(Track.id.in_(playlist_ids))
    )
    tracks_map = {t.id: t for t in tracks_result.scalars().all()}

    return [
        {
            "track_id": tid,
            "title": tracks_map[tid].title if tid in tracks_map else None,
            "artist": tracks_map[tid].artist.name if tid in tracks_map and tracks_map[tid].artist else None,
            "position": i,
        }
        for i, tid in enumerate(playlist_ids)
        if tid in tracks_map
    ]
