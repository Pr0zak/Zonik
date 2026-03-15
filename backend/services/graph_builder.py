"""Graph builder for Music Map visualization."""
from __future__ import annotations

import hashlib
import logging
from functools import lru_cache

import numpy as np
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.track import Track
from backend.models.artist import Artist
from backend.models.favorite import Favorite
from backend.models.analysis import TrackAnalysis
from backend.models.mood import TrackMood
from backend.models.embedding import TrackEmbedding

log = logging.getLogger(__name__)


def _color_from_name(name: str) -> str:
    """Generate a consistent HSL-based hex color from a genre name."""
    h = int(hashlib.md5(name.encode()).hexdigest()[:8], 16) % 360
    # Convert HSL(h, 70%, 55%) to hex (simplified)
    import colorsys
    r, g, b = colorsys.hls_to_rgb(h / 360, 0.55, 0.7)
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"


FORMAT_QUALITY = {"flac": 100, "wav": 90, "opus": 70, "ogg": 60, "m4a": 55, "mp3": 50, "aac": 45, "wma": 30}


async def _aggregate_analysis(db: AsyncSession, artist_ids: list[str]) -> dict:
    """Join TrackAnalysis with Track, group by artist_id, compute averages.

    Returns dict {artist_id: {avg_energy, avg_danceability, avg_bpm}}.
    """
    if not artist_ids:
        return {}
    result = await db.execute(
        select(
            Track.artist_id,
            func.avg(TrackAnalysis.energy).label("avg_energy"),
            func.avg(TrackAnalysis.danceability).label("avg_danceability"),
            func.avg(TrackAnalysis.bpm).label("avg_bpm"),
        )
        .join(TrackAnalysis, TrackAnalysis.track_id == Track.id)
        .where(Track.artist_id.in_(artist_ids))
        .group_by(Track.artist_id)
    )
    out = {}
    for aid, avg_energy, avg_dance, avg_bpm in result.all():
        out[aid] = {
            "avg_energy": round(avg_energy, 3) if avg_energy is not None else None,
            "avg_danceability": round(avg_dance, 3) if avg_dance is not None else None,
            "avg_bpm": round(avg_bpm, 1) if avg_bpm is not None else None,
        }
    return out


async def _aggregate_moods(db: AsyncSession, artist_ids: list[str]) -> dict:
    """Join TrackMood with Track, group by (artist_id, primary_mood).

    Returns dict {artist_id: primary_mood_string} (most common mood per artist).
    """
    if not artist_ids:
        return {}
    result = await db.execute(
        select(
            Track.artist_id,
            TrackMood.primary_mood,
            func.count(TrackMood.track_id).label("cnt"),
        )
        .join(TrackMood, TrackMood.track_id == Track.id)
        .where(
            Track.artist_id.in_(artist_ids),
            TrackMood.primary_mood.isnot(None),
            TrackMood.primary_mood != "",
        )
        .group_by(Track.artist_id, TrackMood.primary_mood)
        .order_by(func.count(TrackMood.track_id).desc())
    )
    out: dict[str, str] = {}
    for aid, mood, cnt in result.all():
        # First row per artist_id wins (ordered by count desc)
        if aid not in out:
            out[aid] = mood
    return out


async def _aggregate_decades(db: AsyncSession, artist_ids: list[str]) -> dict:
    """Query Track.year grouped by artist_id, compute most common decade.

    Returns dict {artist_id: primary_decade_int}.
    """
    if not artist_ids:
        return {}
    # Use (year / 10) * 10 for decade bucketing
    result = await db.execute(
        select(
            Track.artist_id,
            (Track.year / 10 * 10).label("decade"),
            func.count(Track.id).label("cnt"),
        )
        .where(
            Track.artist_id.in_(artist_ids),
            Track.year.isnot(None),
            Track.year > 0,
        )
        .group_by(Track.artist_id, Track.year / 10 * 10)
        .order_by(func.count(Track.id).desc())
    )
    out: dict[str, int] = {}
    for aid, decade, cnt in result.all():
        if aid not in out:
            out[aid] = int(decade)
    return out


async def _compute_vibe_layout(
    db: AsyncSession, artist_ids: list[str], similarity_threshold: float = 0.7
) -> tuple[dict, list]:
    """Compute 2D layout from CLAP embeddings via dimensionality reduction.

    Returns (positions_dict {artist_id: [x, y]}, similarity_edges list).
    """
    if not artist_ids:
        return {}, []

    # Fetch all embeddings joined with tracks
    result = await db.execute(
        select(Track.artist_id, TrackEmbedding.embedding)
        .join(TrackEmbedding, TrackEmbedding.track_id == Track.id)
        .where(Track.artist_id.in_(artist_ids))
    )
    rows = result.all()
    if not rows:
        return {}, []

    # Compute mean embedding per artist
    artist_embeddings: dict[str, list[np.ndarray]] = {}
    for aid, emb_bytes in rows:
        if emb_bytes is None:
            continue
        try:
            emb = np.frombuffer(emb_bytes, dtype=np.float32).copy()
            if len(emb) != 512:
                continue
            artist_embeddings.setdefault(aid, []).append(emb)
        except Exception:
            continue

    if not artist_embeddings:
        return {}, []

    # Build mean vectors
    ordered_ids = list(artist_embeddings.keys())
    mean_vectors = np.array([
        np.mean(artist_embeddings[aid], axis=0) for aid in ordered_ids
    ])
    n = len(ordered_ids)

    # Dimensionality reduction to 2D
    coords_2d = None
    if n >= 2:
        try:
            from sklearn.manifold import TSNE
            perplexity = min(30, max(1, n // 3))
            if perplexity >= n:
                perplexity = max(1, n - 1)
            tsne = TSNE(n_components=2, perplexity=perplexity, random_state=42, n_iter=500)
            coords_2d = tsne.fit_transform(mean_vectors)
        except Exception:
            log.warning("TSNE failed, falling back to PCA")
            try:
                from sklearn.decomposition import PCA
                pca = PCA(n_components=2)
                coords_2d = pca.fit_transform(mean_vectors)
            except Exception:
                log.warning("PCA also failed for vibe layout")
    elif n == 1:
        coords_2d = np.array([[0.0, 0.0]])

    positions: dict[str, list[float]] = {}
    if coords_2d is not None:
        # Normalize to [-500, 500]
        mins = coords_2d.min(axis=0)
        maxs = coords_2d.max(axis=0)
        ranges = maxs - mins
        # Avoid division by zero
        ranges[ranges == 0] = 1.0
        normalized = (coords_2d - mins) / ranges * 1000 - 500  # maps to [-500, 500]
        for i, aid in enumerate(ordered_ids):
            positions[aid] = [round(float(normalized[i, 0]), 1), round(float(normalized[i, 1]), 1)]

    # Compute pairwise cosine similarity for edges
    similarity_edges = []
    if n >= 2:
        # Normalize vectors for cosine similarity
        norms = np.linalg.norm(mean_vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        normed = mean_vectors / norms
        sim_matrix = normed @ normed.T

        for i in range(n):
            for j in range(i + 1, n):
                sim = float(sim_matrix[i, j])
                if sim > similarity_threshold:
                    similarity_edges.append({
                        "source": f"artist:{ordered_ids[i]}",
                        "target": f"artist:{ordered_ids[j]}",
                        "type": "vibe_similarity",
                        "weight": round(sim, 3),
                    })

    return positions, similarity_edges


async def build_graph(
    db: AsyncSession,
    max_artists: int = 200,
    min_genre_tracks: int = 3,
    include_tracks: bool = False,
    max_tracks_per_artist: int = 50,
    layout: str = "force",
    similarity_threshold: float = 0.7,
) -> dict:
    """Build the graph data for the Music Map."""
    nodes = []
    edges = []

    # 1. Genre nodes
    genre_result = await db.execute(
        select(Track.genre, func.count(Track.id).label("cnt"))
        .where(Track.genre.isnot(None), Track.genre != "")
        .group_by(Track.genre)
        .having(func.count(Track.id) >= min_genre_tracks)
        .order_by(func.count(Track.id).desc())
    )
    genres = genre_result.all()
    genre_set = {g[0] for g in genres}

    for genre_name, count in genres:
        nodes.append({
            "id": f"genre:{genre_name}",
            "type": "genre",
            "label": genre_name,
            "size": count,
            "color": _color_from_name(genre_name),
        })

    # 2. Top artists by track count + aggregate play_count and quality
    artist_result = await db.execute(
        select(
            Artist.id, Artist.name, Artist.image_url,
            func.count(Track.id).label("cnt"),
            func.coalesce(func.sum(Track.play_count), 0).label("total_plays"),
            func.avg(Track.bitrate).label("avg_bitrate"),
        )
        .join(Track, Track.artist_id == Artist.id)
        .group_by(Artist.id)
        .order_by(func.count(Track.id).desc())
        .limit(max_artists)
    )
    artists = artist_result.all()
    artist_ids = [a[0] for a in artists]

    # 2b. Primary format per artist (most common format)
    artist_primary_format: dict[str, str] = {}
    if artist_ids:
        fmt_result = await db.execute(
            select(Track.artist_id, Track.format, func.count(Track.id).label("cnt"))
            .where(Track.artist_id.in_(artist_ids), Track.format.isnot(None))
            .group_by(Track.artist_id, Track.format)
            .order_by(func.count(Track.id).desc())
        )
        for aid, fmt, cnt in fmt_result.all():
            if aid not in artist_primary_format:
                artist_primary_format[aid] = fmt

    # 3. Get favorite artist IDs
    fav_result = await db.execute(
        select(Favorite.artist_id).where(Favorite.artist_id.isnot(None))
    )
    fav_artist_ids = {r[0] for r in fav_result.all()}

    # 4. Primary genre per artist
    if artist_ids:
        primary_genre_result = await db.execute(
            select(Track.artist_id, Track.genre, func.count(Track.id).label("cnt"))
            .where(Track.artist_id.in_(artist_ids), Track.genre.isnot(None), Track.genre != "")
            .group_by(Track.artist_id, Track.genre)
            .order_by(func.count(Track.id).desc())
        )
        # Build {artist_id: primary_genre}
        artist_primary_genre: dict[str, str] = {}
        for artist_id, genre, cnt in primary_genre_result.all():
            if artist_id not in artist_primary_genre:
                artist_primary_genre[artist_id] = genre
    else:
        artist_primary_genre = {}

    # 5. Aggregation helpers (sequential — AsyncSession can't do concurrent)
    analysis_data = await _aggregate_analysis(db, artist_ids)
    mood_data = await _aggregate_moods(db, artist_ids)
    decade_data = await _aggregate_decades(db, artist_ids)

    # 6. Build artist nodes + artist_genre edges
    # Build lookup for image_url from artist query
    artist_image_map = {a[0]: a[2] for a in artists}

    for artist_id, artist_name, image_url, track_count, total_plays, avg_bitrate in artists:
        primary = artist_primary_genre.get(artist_id)
        genre_color = _color_from_name(primary) if primary else "#888888"
        primary_fmt = artist_primary_format.get(artist_id, "unknown")
        avg_quality = FORMAT_QUALITY.get(primary_fmt, 0) + int((avg_bitrate or 0) // 10)

        node = {
            "id": f"artist:{artist_id}",
            "type": "artist",
            "label": artist_name,
            "size": track_count,
            "genre": primary,
            "is_favorite": artist_id in fav_artist_ids,
            "color": genre_color,
            "play_count": total_plays,
            "avg_bitrate": int(avg_bitrate) if avg_bitrate else None,
            "primary_format": primary_fmt,
            "avg_quality": avg_quality,
            "image_url": image_url,
        }

        # Merge analysis aggregates
        if artist_id in analysis_data:
            node.update(analysis_data[artist_id])
        else:
            node["avg_energy"] = None
            node["avg_danceability"] = None
            node["avg_bpm"] = None

        # Merge mood
        node["primary_mood"] = mood_data.get(artist_id)

        # Merge decade
        node["primary_decade"] = decade_data.get(artist_id)

        nodes.append(node)
        if primary and primary in genre_set:
            edges.append({
                "source": f"artist:{artist_id}",
                "target": f"genre:{primary}",
                "type": "artist_genre",
                "weight": track_count,
            })

    # 7. Genre co-occurrence edges
    if artist_ids:
        cooccur_result = await db.execute(text("""
            SELECT a.genre, b.genre, COUNT(DISTINCT a.artist_id)
            FROM (SELECT DISTINCT artist_id, genre FROM tracks WHERE genre IS NOT NULL AND genre != '' AND artist_id IS NOT NULL) a
            JOIN (SELECT DISTINCT artist_id, genre FROM tracks WHERE genre IS NOT NULL AND genre != '' AND artist_id IS NOT NULL) b
              ON a.artist_id = b.artist_id AND a.genre < b.genre
            GROUP BY a.genre, b.genre
            HAVING COUNT(DISTINCT a.artist_id) > 0
        """))
        for genre_a, genre_b, shared_artists in cooccur_result.all():
            if genre_a in genre_set and genre_b in genre_set:
                edges.append({
                    "source": f"genre:{genre_a}",
                    "target": f"genre:{genre_b}",
                    "type": "genre_cooccurrence",
                    "weight": shared_artists,
                })

    # 8. Track nodes (optional, expensive)
    total_tracks = 0
    if include_tracks and artist_ids:
        track_result = await db.execute(
            select(Track)
            .where(Track.artist_id.in_(artist_ids))
            .order_by(Track.play_count.desc())
            .limit(max_artists * max_tracks_per_artist)
        )
        track_rows = track_result.scalars().all()
        # Group by artist and cap
        artist_track_counts: dict[str, int] = {}
        for t in track_rows:
            aid = t.artist_id
            if not aid:
                continue
            artist_track_counts[aid] = artist_track_counts.get(aid, 0) + 1
            if artist_track_counts[aid] > max_tracks_per_artist:
                continue
            nodes.append({
                "id": f"track:{t.id}",
                "type": "track",
                "label": t.title,
                "size": max(1, t.play_count or 0),
                "artist_id": aid,
            })
            edges.append({
                "source": f"track:{t.id}",
                "target": f"artist:{aid}",
                "type": "track_artist",
                "weight": 1.0,
            })
            total_tracks += 1

    # 9. Vibe layout (optional)
    result_dict: dict = {"nodes": nodes, "edges": edges}
    if layout == "vibe" and artist_ids:
        vibe_positions, similarity_edges = await _compute_vibe_layout(
            db, artist_ids, similarity_threshold
        )
        result_dict["vibe_positions"] = vibe_positions
        edges.extend(similarity_edges)

    # Meta
    total_track_count = (await db.execute(select(func.count(Track.id)))).scalar() or 0
    meta = {
        "total_tracks": total_track_count,
        "total_artists": len(artists),
        "total_genres": len(genres),
    }
    result_dict["meta"] = meta

    return result_dict
