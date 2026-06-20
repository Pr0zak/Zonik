"""AI playlist generation — create playlists from natural language prompts."""
from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.config import get_settings
import re

from backend.models.track import Track
from backend.models.artist import Artist
from backend.models.album import Album
from backend.models.analysis import TrackAnalysis
from backend.models.playlist import Playlist, PlaylistTrack
from backend.services.ai.client import call_claude

log = logging.getLogger(__name__)


async def generate_playlist(
    db: AsyncSession,
    prompt: str,
    name: str | None = None,
    limit: int = 30,
    save: bool = True,
) -> dict:
    """Generate a playlist from a natural language prompt.

    1. Claude interprets the prompt into track selection criteria
    2. We query the library for matching tracks
    3. Optionally Claude re-orders them for flow
    4. Save as a new playlist (only when ``save`` is True)

    When ``save`` is False the tracks are still selected and returned (ordered
    ``track_ids``) but no Playlist/PlaylistTrack rows are persisted — used by the
    voice "play only" path so spoken mixes don't clutter the library.

    Returns {"id", "name", "track_count", "description", "track_ids"} or
    {"error": ...}. ``id`` is None when ``save`` is False.
    """
    settings = get_settings()
    if not settings.assistant.ai_playlist_gen:
        return {"error": "AI playlist generation is disabled"}

    # Step 1: Get library context for Claude
    genre_result = await db.execute(
        select(Track.genre, func.count(Track.id))
        .where(Track.genre.isnot(None))
        .group_by(Track.genre)
        .order_by(func.count(Track.id).desc())
        .limit(20)
    )
    genres = [{"genre": g, "count": c} for g, c in genre_result.all()]

    artist_result = await db.execute(
        select(Artist.name, func.count(Track.id))
        .join(Track, Track.artist_id == Artist.id)
        .group_by(Artist.name)
        .order_by(func.count(Track.id).desc())
        .limit(30)
    )
    top_artists = [a for a, _ in artist_result.all()]

    total_tracks = (await db.execute(select(func.count(Track.id)))).scalar() or 0

    # Step 2: Ask Claude for selection criteria
    interpret_prompt = f"""You are a music playlist curator. Given a user's request and their library info, suggest how to select tracks.

User request: "{prompt}"

Library info:
- {total_tracks} total tracks
- Top genres: {json.dumps(genres[:15])}
- Top artists: {', '.join(top_artists[:20])}

Pick criteria broad enough to fill roughly {limit} tracks for this request.

Return JSON with selection criteria:
{{
  "name": "suggested playlist name (if user didn't provide one)",
  "genres": ["genre1", "genre2"] or null,
  "artists": ["artist1", "artist2"] or null,
  "min_bpm": number or null,
  "max_bpm": number or null,
  "mood_keywords": ["keyword1"] or null,
  "sort_by": "play_count/rating/random/created_at",
  "description": "1-sentence playlist description"
}}"""

    result = await call_claude(interpret_prompt, max_tokens=512, temperature=0.3)
    if "error" in result:
        return result

    criteria = result.get("parsed", {})
    if not criteria:
        return {"error": "Failed to interpret playlist prompt"}

    # Step 3: Query library
    query = select(Track).options(selectinload(Track.artist), selectinload(Track.album))
    conditions = []

    if criteria.get("genres"):
        # Substring match so multi-genre tags (e.g. "Pop;Christmas;Holiday") and
        # near-misses are caught — exact equality missed most of them.
        genre_conditions = [Track.genre.ilike(f"%{g}%") for g in criteria["genres"]]
        conditions.append(or_(*genre_conditions))

    if criteria.get("artists"):
        artist_conditions = [func.lower(Artist.name).contains(a.lower()) for a in criteria["artists"]]
        query = query.join(Artist, Track.artist_id == Artist.id, isouter=True)
        conditions.append(or_(*artist_conditions))

    if criteria.get("min_bpm") or criteria.get("max_bpm"):
        query = query.outerjoin(TrackAnalysis, Track.id == TrackAnalysis.track_id)
        if criteria.get("min_bpm"):
            conditions.append(TrackAnalysis.bpm >= criteria["min_bpm"])
        if criteria.get("max_bpm"):
            conditions.append(TrackAnalysis.bpm <= criteria["max_bpm"])

    if criteria.get("mood_keywords"):
        # Search genre/title for mood keywords
        mood_conds = []
        for kw in criteria["mood_keywords"]:
            mood_conds.append(Track.genre.ilike(f"%{kw}%"))
            mood_conds.append(Track.title.ilike(f"%{kw}%"))
        conditions.append(or_(*mood_conds))

    if conditions:
        query = query.where(and_(*conditions))

    # Sort
    sort_by = criteria.get("sort_by", "random")
    if sort_by == "random":
        query = query.order_by(func.random())
    elif sort_by == "play_count":
        query = query.order_by(Track.play_count.desc())
    elif sort_by == "rating":
        query = query.order_by(Track.rating.desc().nullslast())
    else:
        query = query.order_by(Track.created_at.desc())

    query = query.limit(min(limit, 200))

    track_result = await db.execute(query)
    tracks = list(track_result.scalars().all())

    target = min(limit, 200)
    if 0 < len(tracks) < target:
        # Broaden a thin match with an on-theme keyword search across artist,
        # ALBUM, title and genre — so niche/franchise requests still fill out
        # (e.g. "Demon Hunters" lives as the album "KPop Demon Hunters" whose
        # tracks are tagged HUNTR/X etc., which the artist filter alone missed).
        stop = {
            "play", "songs", "song", "music", "me", "a", "an", "the", "some", "from",
            "for", "of", "and", "or", "to", "with", "by", "mix", "playlist", "make",
            "give", "tracks", "track", "my", "please", "stuff", "want", "listen", "put",
        }
        words: set[str] = set()
        sources = [prompt, criteria.get("name") or ""]
        for key in ("genres", "artists", "mood_keywords"):
            sources.extend(str(x) for x in (criteria.get(key) or []))
        for src in sources:
            for w in re.findall(r"[A-Za-z0-9']+", src.lower()):
                if len(w) >= 3 and w not in stop:
                    words.add(w)
        if words:
            have = {t.id for t in tracks}
            kw_conds = []
            for w in words:
                like = f"%{w}%"
                kw_conds += [Track.title.ilike(like), Track.genre.ilike(like),
                             Artist.name.ilike(like), Album.title.ilike(like)]
            broad_q = (
                select(Track)
                .options(selectinload(Track.artist), selectinload(Track.album))
                .join(Artist, Track.artist_id == Artist.id, isouter=True)
                .outerjoin(Album, Track.album_id == Album.id)
                .where(or_(*kw_conds))
                .order_by(func.random())
                .limit(target)
            )
            for t in (await db.execute(broad_q)).scalars().all():
                if t.id not in have:
                    tracks.append(t)
                    have.add(t.id)
                    if len(tracks) >= target:
                        break

    if not tracks:
        # Last resort (zero matches at all): random tracks so we never return empty.
        fallback = await db.execute(
            select(Track).order_by(func.random()).limit(limit)
        )
        tracks = list(fallback.scalars().all())

    if not tracks:
        return {"error": "No tracks found matching the criteria"}

    # Step 4: assemble result. track_ids are always returned (ordered) so a voice
    # client can play immediately; the Playlist is only persisted when save=True.
    track_ids = [t.id for t in tracks]
    playlist_name = name or criteria.get("name", f"AI: {prompt[:40]}")
    description = criteria.get("description", f"Generated from: {prompt}")

    playlist_id = None
    if save:
        playlist = Playlist(
            id=str(uuid.uuid4()),
            name=playlist_name,
            comment=description,
        )
        db.add(playlist)
        for i, track in enumerate(tracks):
            db.add(PlaylistTrack(
                id=str(uuid.uuid4()),
                playlist_id=playlist.id,
                track_id=track.id,
                position=i,
            ))
        await db.commit()
        playlist_id = playlist.id

    return {
        "id": playlist_id,
        "name": playlist_name,
        "track_count": len(tracks),
        "description": description,
        "track_ids": track_ids,
    }
