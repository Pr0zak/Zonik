"""AI Music Assistant — taste profile builder, candidate sourcer, and scoring engine."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta
from urllib.parse import quote_plus

import httpx
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


async def _fetch_itunes_metadata(artist: str, track: str) -> dict:
    """Fetch cover art and preview URL from iTunes Search API."""
    try:
        query = quote_plus(f"{artist} {track}")
        url = f"https://itunes.apple.com/search?term={query}&media=music&entity=song&limit=1"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return {}
            data = resp.json()
            results = data.get("results", [])
            if not results:
                return {}
            r = results[0]
            # Upgrade to 300x300 artwork
            art_url = r.get("artworkUrl100", "")
            if art_url:
                art_url = art_url.replace("100x100", "300x300")
            return {
                "image_url": art_url or None,
                "preview_url": r.get("previewUrl") or None,
            }
    except Exception as e:
        log.debug(f"iTunes metadata error for {artist} - {track}: {e}")
        return {}


async def _batch_fetch_itunes(candidates: list[dict], max_concurrent: int = 5) -> None:
    """Batch-fetch iTunes metadata for candidates (in-place update)."""
    sem = asyncio.Semaphore(max_concurrent)

    async def fetch_one(c):
        async with sem:
            meta = await _fetch_itunes_metadata(c["artist"], c["track"])
            if meta:
                c["image_url"] = meta.get("image_url")
                c["preview_url"] = meta.get("preview_url")
            # Rate limit: ~200ms between requests
            await asyncio.sleep(0.2)

    tasks = [fetch_one(c) for c in candidates]
    await asyncio.gather(*tasks, return_exceptions=True)
    fetched = sum(1 for c in candidates if c.get("image_url"))
    log.info(f"iTunes metadata: {fetched}/{len(candidates)} with cover art")


async def _fetch_candidate_tags(candidates: list[dict]) -> None:
    """Fetch Last.fm tags for candidates that don't have them yet (in-place update)."""
    from backend.services.lastfm import get_track_info

    for c in candidates:
        if c.get("tags"):
            continue
        try:
            info = await get_track_info(c["artist"], c["track"])
            if info and info.get("tags"):
                c["tags"] = info["tags"][:5]  # Top 5 tags
        except Exception as e:
            log.debug(f"Tag fetch error for {c['artist']} - {c['track']}: {e}")


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

    # Genre match — use Last.fm tags when available, fall back to source_detail
    genre_dist = profile.get("genre_distribution", {})
    genre_dist_lower = {g.lower(): pct for g, pct in genre_dist.items()}
    genre_match = 0.0
    candidate_tags = [t.lower() for t in candidate.get("tags", [])]
    if candidate_tags:
        # Real tag comparison: weighted overlap with user's genre distribution
        overlap = sum(genre_dist_lower.get(tag, 0) for tag in candidate_tags)
        genre_match = min(1.0, overlap * 2.5)  # Normalize: 40% distribution match → 1.0
    else:
        # Fallback: pattern match against source_detail
        source_detail = (candidate.get("source_detail") or "").lower()
        for genre, pct in genre_dist.items():
            if genre.lower() in source_detail:
                genre_match = min(1.0, pct * 3)
                break
    if candidate["source"] == "tag" and genre_match < 0.3:
        # Tag-based candidates inherently match their genre
        source_detail = (candidate.get("source_detail") or "").lower()
        for genre_key, pct in genre_dist_lower.items():
            if genre_key in source_detail:
                genre_match = max(genre_match, min(1.0, pct * 4))
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

async def _get_feedback_multipliers(db: AsyncSession) -> dict[str, float]:
    """Build feedback multipliers from historical thumbs up/down.

    Returns {normalized_artist: multiplier} where:
    - Artists with thumbs_up history get 1.2x
    - Artists with thumbs_down history get 0.5x
    """
    multipliers: dict[str, float] = {}

    # Liked recommendations boost the artist
    liked = await db.execute(
        select(Recommendation.artist)
        .where(Recommendation.feedback == "thumbs_up")
    )
    for (artist,) in liked.all():
        multipliers[_normalize(artist)] = 1.2

    # Disliked recommendations suppress the artist
    disliked = await db.execute(
        select(Recommendation.artist)
        .where(Recommendation.feedback == "thumbs_down")
    )
    for (artist,) in disliked.all():
        multipliers[_normalize(artist)] = 0.5

    return multipliers


async def validate_downloaded_recommendations(db: AsyncSession) -> int:
    """Validate downloaded recommendations against CLAP taste centroid.

    Compares each downloaded rec's track embedding to the centroid.
    Flags mismatches (cosine similarity < 0.3) by updating source_detail.
    Returns count of validated tracks.
    """
    # Load taste profile centroid
    tp = await db.get(TasteProfile, "default")
    if not tp or not tp.clap_centroid:
        return 0

    centroid = np.frombuffer(tp.clap_centroid, dtype=np.float32)
    if len(centroid) != 512:
        return 0

    # Find downloaded recommendations that haven't been validated yet
    downloaded = (await db.execute(
        select(Recommendation)
        .where(
            Recommendation.status == "downloaded",
            Recommendation.feedback.is_(None),
        )
    )).scalars().all()

    if not downloaded:
        return 0

    validated = 0
    for rec in downloaded:
        # Find the track in library by artist+title match
        track_result = await db.execute(
            select(Track.id)
            .join(Artist, Track.artist_id == Artist.id)
            .where(
                func.lower(Track.title) == func.lower(rec.track),
                func.lower(Artist.name) == func.lower(rec.artist),
            )
            .limit(1)
        )
        track_id = track_result.scalar_one_or_none()
        if not track_id:
            continue

        # Get embedding
        emb = await db.get(TrackEmbedding, track_id)
        if not emb:
            continue

        try:
            track_emb = np.frombuffer(emb.embedding, dtype=np.float32)
            if len(track_emb) != 512:
                continue

            # Cosine similarity
            dot = np.dot(centroid, track_emb)
            norm = np.linalg.norm(centroid) * np.linalg.norm(track_emb)
            similarity = float(dot / norm) if norm > 0 else 0

            # Update score breakdown with CLAP validation
            breakdown = json.loads(rec.score_breakdown) if rec.score_breakdown else {}
            breakdown["clap_similarity"] = round(similarity, 3)
            rec.score_breakdown = json.dumps(breakdown)

            if similarity < 0.3:
                rec.source_detail = (rec.source_detail or "") + f" [CLAP mismatch: {similarity:.0%}]"
                log.info(f"CLAP mismatch for {rec.artist} - {rec.track}: {similarity:.3f}")

            validated += 1
        except Exception as e:
            log.debug(f"CLAP validation error for {rec.artist} - {rec.track}: {e}")

    if validated:
        await db.commit()
        log.info(f"CLAP-validated {validated} downloaded recommendations")

    return validated


async def refresh_recommendations(
    db: AsyncSession,
    limit: int = 100,
    use_claude: bool = False,
    on_progress=None,
) -> dict:
    """Full recommendation refresh: build profile, source, score, store."""
    total_steps = 6 if use_claude else 5

    if on_progress:
        await on_progress(0, total_steps, "Building taste profile...")

    # Step 1: Build taste profile
    profile = await build_taste_profile(db)

    # Validate any previously downloaded recommendations via CLAP
    clap_validated = await validate_downloaded_recommendations(db)

    if on_progress:
        await on_progress(1, total_steps, "Sourcing candidates from Last.fm...")

    # Step 2: Source candidates
    candidates = await source_candidates(db, profile)

    if on_progress:
        await on_progress(2, total_steps, f"Fetching tags for {len(candidates)} candidates...")

    # Step 2b: Fetch Last.fm tags for top candidates (improves genre scoring)
    # Only fetch for first 200 to stay within rate limits
    await _fetch_candidate_tags(candidates[:200])

    if on_progress:
        await on_progress(3, total_steps, f"Scoring {len(candidates)} candidates...")

    # Step 3: Load CLAP centroid + feedback multipliers
    tp = await db.get(TasteProfile, "default")
    clap_centroid = tp.clap_centroid if tp else None
    feedback_mults = await _get_feedback_multipliers(db)

    # Step 4: Score and rank
    scored = []
    for c in candidates:
        score, breakdown = score_candidate(c, profile, clap_centroid)
        # Apply feedback multiplier
        artist_key = _normalize(c["artist"])
        mult = feedback_mults.get(artist_key, 1.0)
        if mult != 1.0:
            score = round(min(1.0, max(0.0, score * mult)), 3)
            breakdown["feedback_multiplier"] = mult
        scored.append({**c, "score": score, "breakdown": breakdown})

    # Sort by score descending, take top N
    scored.sort(key=lambda x: x["score"], reverse=True)
    top = scored[:limit]

    # Step 4b: Claude re-ranking (optional)
    claude_usage = None
    if use_claude:
        if on_progress:
            await on_progress(4, total_steps, "Getting AI suggestions from Claude...")
        try:
            from backend.services.claude_ai import rerank_with_claude
            claude_result = await rerank_with_claude(profile, top[:50])

            if "error" not in claude_result:
                claude_usage = claude_result.get("usage")
                # Merge Claude re-ranked scores and explanations
                ranked = claude_result.get("ranked", [])
                claude_map = {
                    f"{_normalize(r['artist'])}::{_normalize(r['track'])}": r
                    for r in ranked
                }
                for c in top:
                    key = f"{_normalize(c['artist'])}::{_normalize(c['track'])}"
                    if key in claude_map:
                        cr = claude_map[key]
                        c["score"] = cr.get("score", c["score"])
                        c["breakdown"]["claude_score"] = cr.get("score", 0)
                        if cr.get("explanation"):
                            c["source_detail"] = cr["explanation"]

                # Add Claude's additional suggestions
                additional = claude_result.get("additional", [])
                for a in additional:
                    if not a.get("artist") or not a.get("track"):
                        continue
                    top.append({
                        "artist": a["artist"],
                        "track": a["track"],
                        "source": "claude",
                        "source_detail": a.get("explanation", "AI suggestion"),
                        "score": a.get("score", 0.7),
                        "breakdown": {"claude_score": a.get("score", 0.7)},
                        "lastfm_listeners": None,
                        "lastfm_match": None,
                    })

                # Re-sort after Claude adjustments
                top.sort(key=lambda x: x["score"], reverse=True)
                top = top[:limit]
                log.info(f"Claude re-ranked {len(ranked)} candidates, added {len(additional)} suggestions")
            else:
                log.warning(f"Claude re-ranking failed: {claude_result['error']}")
        except Exception as e:
            log.error(f"Claude integration error: {e}")

    # Fetch iTunes metadata (cover art + preview URL) for top candidates
    step = 5 if use_claude else 4
    if on_progress:
        await on_progress(step, total_steps, f"Fetching artwork for {len(top)} recommendations...")
    await _batch_fetch_itunes(top)

    if on_progress:
        await on_progress(step, total_steps, "Saving recommendations...")

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
            image_url=c.get("image_url"),
            preview_url=c.get("preview_url"),
            created_at=now,
            expires_at=expires,
        )
        db.add(rec)

    await db.commit()

    if on_progress:
        await on_progress(total_steps, total_steps, "Done")

    result = {
        "candidates_sourced": len(candidates),
        "recommendations_saved": len(top),
        "top_score": top[0]["score"] if top else 0,
        "clap_validated": clap_validated,
    }
    if claude_usage:
        result["claude_usage"] = claude_usage
    return result
