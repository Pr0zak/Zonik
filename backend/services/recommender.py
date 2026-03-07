"""AI Music Assistant — taste profile builder, candidate sourcer, and scoring engine."""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta

import numpy as np
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.config import get_settings
from backend.models.track import Track
from backend.models.artist import Artist
from backend.models.favorite import Favorite
from backend.models.analysis import TrackAnalysis
from backend.models.embedding import TrackEmbedding
from backend.models.blacklist import DownloadBlacklist
from backend.models.recommendation import Recommendation
from backend.models.taste_profile import TasteProfile

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Taste Profile Builder
# ---------------------------------------------------------------------------

async def build_taste_profile(db: AsyncSession) -> dict:
    """Build a taste profile from the user's library data."""

    # Genre histogram (top 20)
    genre_result = await db.execute(
        select(Track.genre, func.count(Track.id).label("cnt"))
        .where(Track.genre.isnot(None), Track.genre != "")
        .group_by(Track.genre)
        .order_by(func.count(Track.id).desc())
        .limit(20)
    )
    genre_rows = genre_result.all()
    total_genre_tracks = sum(r[1] for r in genre_rows)
    genre_distribution = {
        g: round(c / total_genre_tracks, 3) if total_genre_tracks else 0
        for g, c in genre_rows
    }

    # Top artists by play_count (top 20)
    artist_result = await db.execute(
        select(Artist.name, func.sum(Track.play_count).label("plays"))
        .join(Track, Track.artist_id == Artist.id)
        .group_by(Artist.id)
        .order_by(func.sum(Track.play_count).desc())
        .limit(20)
    )
    top_artists = [{"name": name, "plays": int(plays or 0)} for name, plays in artist_result.all()]

    # Favorited artist names
    fav_result = await db.execute(
        select(Artist.name)
        .join(Favorite, Favorite.artist_id == Artist.id)
        .distinct()
    )
    favorite_artists = [r[0] for r in fav_result.all()]

    # Also get favorited tracks' artists
    fav_track_result = await db.execute(
        select(Artist.name)
        .join(Track, Track.artist_id == Artist.id)
        .join(Favorite, Favorite.track_id == Track.id)
        .distinct()
    )
    fav_track_artists = [r[0] for r in fav_track_result.all()]
    all_fav_artists = list(set(favorite_artists + fav_track_artists))

    # Audio analysis stats (from played tracks)
    analysis_result = await db.execute(
        select(
            func.avg(TrackAnalysis.bpm),
            func.avg(TrackAnalysis.energy),
            func.avg(TrackAnalysis.danceability),
            func.count(TrackAnalysis.track_id),
        )
        .join(Track, Track.id == TrackAnalysis.track_id)
        .where(Track.play_count > 0)
    )
    avg_bpm, avg_energy, avg_dance, analyzed_count = analysis_result.one()

    # BPM std dev
    bpm_std = None
    if avg_bpm:
        std_result = await db.execute(
            select(func.avg((TrackAnalysis.bpm - avg_bpm) * (TrackAnalysis.bpm - avg_bpm)))
            .join(Track, Track.id == TrackAnalysis.track_id)
            .where(Track.play_count > 0, TrackAnalysis.bpm.isnot(None))
        )
        variance = std_result.scalar()
        if variance and variance > 0:
            bpm_std = round(variance ** 0.5, 1)

    # CLAP centroid (average embedding of favorites + most-played)
    clap_centroid = None
    clap_count = 0
    # Get favorite track IDs
    fav_ids_result = await db.execute(
        select(Favorite.track_id).where(Favorite.track_id.isnot(None))
    )
    fav_track_ids = [r[0] for r in fav_ids_result.all()]

    # Get top played track IDs
    top_played_result = await db.execute(
        select(Track.id).where(Track.play_count > 0)
        .order_by(Track.play_count.desc()).limit(50)
    )
    top_played_ids = [r[0] for r in top_played_result.all()]

    centroid_ids = list(set(fav_track_ids + top_played_ids))
    if centroid_ids:
        emb_result = await db.execute(
            select(TrackEmbedding.embedding)
            .where(TrackEmbedding.track_id.in_(centroid_ids))
        )
        embeddings = []
        for (emb_bytes,) in emb_result.all():
            try:
                arr = np.frombuffer(emb_bytes, dtype=np.float32)
                if len(arr) == 512:
                    embeddings.append(arr)
            except Exception:
                pass
        if len(embeddings) >= 3:
            centroid = np.mean(embeddings, axis=0)
            clap_centroid = centroid.tobytes()
            clap_count = len(embeddings)

    # Blacklisted artists
    bl_result = await db.execute(
        select(DownloadBlacklist.artist).where(DownloadBlacklist.track.is_(None)).distinct()
    )
    blacklisted_artists = [r[0] for r in bl_result.all()]

    # Counts
    track_count = (await db.execute(select(func.count(Track.id)))).scalar() or 0
    fav_count = (await db.execute(select(func.count(Favorite.id)))).scalar() or 0

    profile_data = {
        "genre_distribution": genre_distribution,
        "top_artists": top_artists,
        "favorite_artists": all_fav_artists,
        "blacklisted_artists": blacklisted_artists,
        "audio": {
            "avg_bpm": round(avg_bpm, 1) if avg_bpm else None,
            "bpm_std": bpm_std,
            "avg_energy": round(avg_energy, 3) if avg_energy else None,
            "avg_danceability": round(avg_dance, 3) if avg_dance else None,
        },
    }

    # Save to DB
    existing = await db.get(TasteProfile, "default")
    if existing:
        existing.profile_data = json.dumps(profile_data)
        existing.clap_centroid = clap_centroid
        existing.track_count = track_count
        existing.favorite_count = fav_count
        existing.analyzed_count = int(analyzed_count or 0)
        existing.computed_at = datetime.utcnow()
    else:
        db.add(TasteProfile(
            id="default",
            profile_data=json.dumps(profile_data),
            clap_centroid=clap_centroid,
            track_count=track_count,
            favorite_count=fav_count,
            analyzed_count=int(analyzed_count or 0),
            computed_at=datetime.utcnow(),
        ))
    await db.commit()

    return profile_data


# ---------------------------------------------------------------------------
# 2. Candidate Sourcing
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Normalize text for dedup comparison."""
    import re
    return re.sub(r'[^a-z0-9]', '', text.lower())


async def _get_library_keys(db: AsyncSession) -> set[str]:
    """Get normalized artist::title keys for all library tracks."""
    result = await db.execute(
        select(Artist.name, Track.title)
        .join(Track, Track.artist_id == Artist.id)
    )
    return {f"{_normalize(a)}::{_normalize(t)}" for a, t in result.all()}


async def _get_blacklisted(db: AsyncSession) -> tuple[set[str], set[str]]:
    """Get blacklisted artists and artist::track pairs."""
    result = await db.execute(select(DownloadBlacklist))
    bl_artists = set()
    bl_tracks = set()
    for bl in result.scalars().all():
        if bl.track:
            bl_tracks.add(f"{_normalize(bl.artist)}::{_normalize(bl.track)}")
        else:
            bl_artists.add(_normalize(bl.artist))
    return bl_artists, bl_tracks


async def source_candidates(db: AsyncSession, profile: dict) -> list[dict]:
    """Source recommendation candidates from Last.fm."""
    from backend.services.lastfm import (
        get_similar_tracks, get_similar_artists,
        get_artist_top_tracks, get_top_tracks, get_track_info,
    )

    settings = get_settings()
    if not settings.lastfm.api_key:
        log.warning("No Last.fm API key — cannot source candidates")
        return []

    library_keys = await _get_library_keys(db)
    bl_artists, bl_tracks = await _get_blacklisted(db)

    # Recently rejected recommendations (last 7 days)
    week_ago = datetime.utcnow() - timedelta(days=7)
    rejected_result = await db.execute(
        select(Recommendation.artist, Recommendation.track)
        .where(Recommendation.feedback == "thumbs_down", Recommendation.created_at > week_ago)
    )
    rejected_keys = {
        f"{_normalize(a)}::{_normalize(t)}" for a, t in rejected_result.all()
    }

    candidates: dict[str, dict] = {}  # key -> candidate

    def add_candidate(artist: str, track: str, source: str, source_detail: str = "",
                      listeners: int = 0, match: float = 0.0):
        key = f"{_normalize(artist)}::{_normalize(track)}"
        if key in library_keys:
            return
        if _normalize(artist) in bl_artists:
            return
        if key in bl_tracks:
            return
        if key in rejected_keys:
            return
        if key in candidates:
            # Keep highest match score
            if match > (candidates[key].get("lastfm_match") or 0):
                candidates[key]["lastfm_match"] = match
            return
        candidates[key] = {
            "artist": artist,
            "track": track,
            "source": source,
            "source_detail": source_detail,
            "lastfm_listeners": listeners,
            "lastfm_match": match,
        }

    # Strategy 1: Similar tracks from favorites (top 20 favorites, 10 similar each)
    fav_result = await db.execute(
        select(Track.title, Artist.name)
        .join(Artist, Track.artist_id == Artist.id)
        .join(Favorite, Favorite.track_id == Track.id)
        .order_by(Track.play_count.desc())
        .limit(20)
    )
    fav_tracks = fav_result.all()
    for title, artist_name in fav_tracks:
        try:
            similar = await get_similar_tracks(artist_name, title, limit=10)
            for s in similar:
                add_candidate(
                    s["artist"], s["name"], "similar_track",
                    f"Similar to {artist_name} — {title}",
                    match=s.get("match", 0),
                )
        except Exception as e:
            log.debug(f"Similar tracks error for {artist_name} - {title}: {e}")

    # Strategy 2: Similar artists' top tracks
    fav_artists = profile.get("favorite_artists", [])[:10]
    for artist_name in fav_artists:
        try:
            similar = await get_similar_artists(artist_name, limit=5)
            for sa in similar[:3]:
                top = await get_artist_top_tracks(sa["name"], limit=5)
                for t in top:
                    add_candidate(
                        t["artist"], t["name"], "similar_artist",
                        f"Top track by {sa['name']} (similar to {artist_name})",
                        listeners=t.get("listeners", 0),
                        match=sa.get("match", 0),
                    )
        except Exception as e:
            log.debug(f"Similar artists error for {artist_name}: {e}")

    # Strategy 3: Tag-based discovery (top 5 genres)
    top_genres = list(profile.get("genre_distribution", {}).keys())[:5]
    for genre in top_genres:
        try:
            from backend.services.lastfm import lastfm_api
            data = await lastfm_api("tag.getTopTracks", {"tag": genre, "limit": "20"})
            if data and "tracks" in data:
                tracks = data["tracks"].get("track", [])
                for t in tracks[:20]:
                    add_candidate(
                        t.get("artist", {}).get("name", ""),
                        t.get("name", ""),
                        "tag",
                        f"Top {genre} track",
                        listeners=int(t.get("listeners", 0)),
                    )
        except Exception as e:
            log.debug(f"Tag discovery error for {genre}: {e}")

    # Strategy 4: Trending overlap (chart filtered by matching genres)
    try:
        chart = await get_top_tracks(limit=50)
        for t in chart:
            add_candidate(
                t["artist"], t["name"], "trending",
                "Last.fm trending",
                listeners=t.get("listeners", 0),
            )
    except Exception as e:
        log.debug(f"Chart error: {e}")

    log.info(f"Sourced {len(candidates)} candidates")
    return list(candidates.values())


# ---------------------------------------------------------------------------
# 3. Scoring Engine
# ---------------------------------------------------------------------------

def score_candidate(candidate: dict, profile: dict, clap_centroid: bytes | None = None) -> tuple[float, dict]:
    """Score a candidate track against the taste profile. Returns (score, breakdown)."""
    settings = get_settings()
    cfg = settings.assistant

    breakdown = {}

    # Artist affinity
    artist_norm = _normalize(candidate["artist"])
    fav_artists_norm = [_normalize(a) for a in profile.get("favorite_artists", [])]
    top_artists_norm = {_normalize(a["name"]): a["plays"] for a in profile.get("top_artists", [])}

    if artist_norm in fav_artists_norm:
        artist_affinity = 1.0
    elif artist_norm in top_artists_norm:
        max_plays = max(top_artists_norm.values()) if top_artists_norm else 1
        artist_affinity = 0.3 + 0.6 * (top_artists_norm[artist_norm] / max(max_plays, 1))
    else:
        artist_affinity = 0.0
    breakdown["artist_affinity"] = round(artist_affinity, 3)

    # Genre match (from source_detail or Last.fm tags — use source as proxy)
    genre_dist = profile.get("genre_distribution", {})
    genre_match = 0.0
    # Check if candidate source_detail mentions a genre we like
    source_detail = (candidate.get("source_detail") or "").lower()
    for genre, pct in genre_dist.items():
        if genre.lower() in source_detail:
            genre_match = min(1.0, pct * 3)  # Boost: top genres get close to 1.0
            break
    if candidate["source"] == "tag":
        # Tag-based candidates inherently match
        for genre in genre_dist:
            if genre.lower() in source_detail:
                genre_match = max(genre_match, min(1.0, genre_dist[genre] * 4))
                break
    breakdown["genre_match"] = round(genre_match, 3)

    # Last.fm similarity score
    lastfm_similar = candidate.get("lastfm_match") or 0.0
    breakdown["lastfm_similar"] = round(lastfm_similar, 3)

    # Audio profile match (heuristic — we don't have candidate audio yet)
    audio = profile.get("audio", {})
    audio_match = 0.5 if audio.get("avg_bpm") else 0.0  # Default middle if we have profile
    breakdown["audio_match"] = round(audio_match, 3)

    # CLAP similarity (only if we have centroid — post-download signal)
    clap_similarity = 0.0
    breakdown["clap_similarity"] = 0.0

    # Popularity
    listeners = candidate.get("lastfm_listeners") or 0
    popularity = min(1.0, listeners / 1_000_000)
    breakdown["popularity"] = round(popularity, 3)

    # Novelty bonus
    if artist_norm not in fav_artists_norm and artist_norm not in top_artists_norm:
        novelty = 1.0  # Completely new artist
    elif artist_affinity < 0.5:
        novelty = 0.5  # Known artist, new track
    else:
        novelty = 0.0  # Well-known
    breakdown["novelty"] = round(novelty, 3)

    # Weighted sum
    score = (
        cfg.w_artist_affinity * artist_affinity +
        cfg.w_genre_match * genre_match +
        cfg.w_lastfm_similar * lastfm_similar +
        cfg.w_audio_match * audio_match +
        cfg.w_clap_similarity * clap_similarity +
        cfg.w_popularity * popularity +
        cfg.w_novelty * novelty
    )

    return round(min(1.0, max(0.0, score)), 3), breakdown


def _generate_explanation(candidate: dict, breakdown: dict) -> str:
    """Generate a human-readable explanation for the recommendation."""
    parts = []
    source = candidate.get("source", "")
    detail = candidate.get("source_detail", "")

    if source == "similar_track" and detail:
        parts.append(detail)
    elif source == "similar_artist" and detail:
        parts.append(detail)
    elif source == "tag" and detail:
        parts.append(detail)
    elif source == "trending":
        parts.append("Currently trending on Last.fm")

    # Highlight strongest signal
    top_signal = max(breakdown, key=breakdown.get) if breakdown else None
    signal_labels = {
        "artist_affinity": "matches your favorite artists",
        "genre_match": "fits your preferred genres",
        "lastfm_similar": "highly similar on Last.fm",
        "novelty": "introduces a new artist",
        "popularity": "widely popular",
    }
    if top_signal and top_signal in signal_labels and breakdown.get(top_signal, 0) > 0.3:
        parts.append(signal_labels[top_signal])

    return ". ".join(parts) if parts else "Recommended based on your listening profile"


# ---------------------------------------------------------------------------
# 4. Full Refresh Pipeline
# ---------------------------------------------------------------------------

async def refresh_recommendations(
    db: AsyncSession,
    limit: int = 100,
    on_progress=None,
) -> dict:
    """Full recommendation refresh: build profile, source, score, store."""

    if on_progress:
        await on_progress(0, 4, "Building taste profile...")

    # Step 1: Build taste profile
    profile = await build_taste_profile(db)

    if on_progress:
        await on_progress(1, 4, "Sourcing candidates from Last.fm...")

    # Step 2: Source candidates
    candidates = await source_candidates(db, profile)

    if on_progress:
        await on_progress(2, 4, f"Scoring {len(candidates)} candidates...")

    # Step 3: Load CLAP centroid
    tp = await db.get(TasteProfile, "default")
    clap_centroid = tp.clap_centroid if tp else None

    # Step 4: Score and rank
    scored = []
    for c in candidates:
        score, breakdown = score_candidate(c, profile, clap_centroid)
        scored.append({**c, "score": score, "breakdown": breakdown})

    # Sort by score descending, take top N
    scored.sort(key=lambda x: x["score"], reverse=True)
    top = scored[:limit]

    if on_progress:
        await on_progress(3, 4, "Saving recommendations...")

    # Step 5: Expire old pending recommendations
    await db.execute(
        delete(Recommendation).where(
            Recommendation.status == "pending",
            Recommendation.created_at < datetime.utcnow() - timedelta(days=7),
        )
    )

    # Step 6: Clear existing pending (but keep accepted/downloaded/rejected for history)
    await db.execute(
        delete(Recommendation).where(Recommendation.status == "pending")
    )

    # Step 7: Insert new recommendations
    now = datetime.utcnow()
    expires = now + timedelta(days=7)
    for c in top:
        rec = Recommendation(
            id=str(uuid.uuid4()),
            artist=c["artist"],
            track=c["track"],
            source=c["source"],
            source_detail=c.get("source_detail"),
            score=c["score"],
            score_breakdown=json.dumps(c["breakdown"]),
            status="pending",
            explanation=_generate_explanation(c, c["breakdown"]),
            lastfm_listeners=c.get("lastfm_listeners"),
            lastfm_match=c.get("lastfm_match"),
            created_at=now,
            expires_at=expires,
        )
        db.add(rec)

    await db.commit()

    if on_progress:
        await on_progress(4, 4, "Done")

    return {
        "candidates_sourced": len(candidates),
        "recommendations_saved": len(top),
        "top_score": top[0]["score"] if top else 0,
    }
