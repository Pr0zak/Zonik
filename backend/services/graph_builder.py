"""Graph builder for Music Map visualization."""
from __future__ import annotations

import hashlib
import logging
from functools import lru_cache

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.track import Track
from backend.models.artist import Artist
from backend.models.favorite import Favorite

log = logging.getLogger(__name__)


def _color_from_name(name: str) -> str:
    """Generate a consistent HSL-based hex color from a genre name."""
    h = int(hashlib.md5(name.encode()).hexdigest()[:8], 16) % 360
    # Convert HSL(h, 70%, 55%) to hex (simplified)
    import colorsys
    r, g, b = colorsys.hls_to_rgb(h / 360, 0.55, 0.7)
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"


async def build_graph(
    db: AsyncSession,
    max_artists: int = 200,
    min_genre_tracks: int = 3,
    include_tracks: bool = False,
    max_tracks_per_artist: int = 50,
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

    # 2. Top artists by track count
    artist_result = await db.execute(
        select(Artist.id, Artist.name, func.count(Track.id).label("cnt"))
        .join(Track, Track.artist_id == Artist.id)
        .group_by(Artist.id)
        .order_by(func.count(Track.id).desc())
        .limit(max_artists)
    )
    artists = artist_result.all()
    artist_ids = [a[0] for a in artists]

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

    # 5. Build artist nodes + artist_genre edges
    for artist_id, artist_name, track_count in artists:
        primary = artist_primary_genre.get(artist_id)
        genre_color = _color_from_name(primary) if primary else "#888888"
        nodes.append({
            "id": f"artist:{artist_id}",
            "type": "artist",
            "label": artist_name,
            "size": track_count,
            "genre": primary,
            "is_favorite": artist_id in fav_artist_ids,
            "color": genre_color,
        })
        if primary and primary in genre_set:
            edges.append({
                "source": f"artist:{artist_id}",
                "target": f"genre:{primary}",
                "type": "artist_genre",
                "weight": track_count,
            })

    # 6. Genre co-occurrence edges
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

    # 7. Track nodes (optional, expensive)
    total_tracks = 0
    if include_tracks and artist_ids:
        from backend.models.analysis import TrackAnalysis
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

    # Meta
    total_track_count = (await db.execute(select(func.count(Track.id)))).scalar() or 0
    meta = {
        "total_tracks": total_track_count,
        "total_artists": len(artists),
        "total_genres": len(genres),
    }

    return {"nodes": nodes, "edges": edges, "meta": meta}
