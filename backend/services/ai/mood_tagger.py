"""Mood tagging using CLAP text embeddings and optional Claude refinement."""
from __future__ import annotations

import logging
import numpy as np
from datetime import datetime

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import async_session
from backend.models.mood import TrackMood
from backend.models.embedding import TrackEmbedding

_log = logging.getLogger(__name__)

# 15 mood vocabulary — short, music-relevant labels
MOOD_VOCAB = [
    "energetic", "calm", "melancholic", "happy", "dark",
    "romantic", "aggressive", "dreamy", "uplifting", "mysterious",
    "nostalgic", "playful", "intense", "peaceful", "ethereal",
]

# CLAP text embeddings for each mood (computed lazily)
_mood_embeddings: dict[str, np.ndarray] | None = None


def _get_mood_embeddings() -> dict[str, np.ndarray]:
    """Compute CLAP text embeddings for mood vocabulary (cached)."""
    global _mood_embeddings
    if _mood_embeddings is not None:
        return _mood_embeddings

    try:
        from backend.services.embeddings import get_model
        model, processor = get_model()
        import torch

        embeddings = {}
        for mood in MOOD_VOCAB:
            text = f"{mood} music"
            inputs = processor(text=[text], return_tensors="pt", padding=True)
            with torch.no_grad():
                text_embed = model.get_text_features(**inputs)
            vec = text_embed[0].cpu().numpy().astype(np.float32)
            vec = vec / (np.linalg.norm(vec) + 1e-8)
            embeddings[mood] = vec

        _mood_embeddings = embeddings
        _log.info(f"Computed CLAP text embeddings for {len(embeddings)} moods")
        return embeddings
    except Exception as e:
        _log.error(f"Failed to compute mood embeddings: {e}")
        return {}


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))


async def tag_tracks_with_moods(track_ids: list[str], top_k: int = 3) -> dict:
    """Tag tracks with mood labels using CLAP similarity.

    Returns: {track_id: {moods: [...], primary: str, confidence: float}}
    """
    mood_embeds = _get_mood_embeddings()
    if not mood_embeds:
        return {"error": "CLAP model not available for mood tagging"}

    results = {}
    tagged = 0

    async with async_session() as session:
        # Fetch embeddings for requested tracks
        stmt = select(TrackEmbedding).where(TrackEmbedding.track_id.in_(track_ids))
        rows = (await session.execute(stmt)).scalars().all()

        for emb in rows:
            try:
                from backend.services.embeddings import embedding_from_bytes
                track_vec = embedding_from_bytes(emb.embedding)

                # Score each mood
                scores = {}
                for mood, mood_vec in mood_embeds.items():
                    scores[mood] = _cosine_similarity(track_vec, mood_vec)

                # Top-k moods
                sorted_moods = sorted(scores.items(), key=lambda x: x[1], reverse=True)
                top_moods = sorted_moods[:top_k]

                primary = top_moods[0][0]
                confidence = top_moods[0][1]
                mood_list = [m for m, _ in top_moods]

                # Upsert mood record
                existing = await session.get(TrackMood, emb.track_id)
                if existing:
                    existing.moods = ",".join(mood_list)
                    existing.primary_mood = primary
                    existing.confidence = round(confidence, 4)
                    existing.source = "clap"
                    existing.created_at = datetime.utcnow()
                else:
                    session.add(TrackMood(
                        track_id=emb.track_id,
                        moods=",".join(mood_list),
                        primary_mood=primary,
                        confidence=round(confidence, 4),
                        source="clap",
                    ))

                results[emb.track_id] = {
                    "moods": mood_list,
                    "primary": primary,
                    "confidence": round(confidence, 4),
                }
                tagged += 1
            except Exception as e:
                _log.warning(f"Mood tagging failed for {emb.track_id}: {e}")

        if tagged:
            await session.commit()

    return {
        "tagged": tagged,
        "skipped": len(track_ids) - tagged,
        "results": results,
    }


async def get_track_moods(track_ids: list[str] | None = None) -> list[dict]:
    """Get mood tags for tracks. If no IDs given, return all."""
    async with async_session() as session:
        stmt = select(TrackMood)
        if track_ids:
            stmt = stmt.where(TrackMood.track_id.in_(track_ids))
        rows = (await session.execute(stmt)).scalars().all()
        return [
            {
                "track_id": r.track_id,
                "moods": r.moods.split(",") if r.moods else [],
                "primary_mood": r.primary_mood,
                "confidence": r.confidence,
                "source": r.source,
            }
            for r in rows
        ]
