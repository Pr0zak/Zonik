"""AI playlist generation — create playlists from natural language prompts."""
from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.config import get_settings
from backend.models.track import Track
from backend.models.artist import Artist
from backend.models.analysis import TrackAnalysis
from backend.models.playlist import Playlist, PlaylistTrack
from backend.services.ai.client import call_claude

log = logging.getLogger(__name__)


async def generate_playlist(
    db: AsyncSession,
    prompt: str,
    name: str | None = None,
    limit: int = 30,
) -> dict:
    """Generate a playlist from a natural language prompt.

    1. Claude interprets the prompt into track selection criteria
    2. We query the library for matching tracks
    3. Optionally Claude re-orders them for flow
    4. Save as a new playlist

    Returns {"id": ..., "name": ..., "track_count": ...} or {"error": ...}
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
        genre_conditions = [func.lower(Track.genre) == g.lower() for g in criteria["genres"]]
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
    tracks = track_result.scalars().all()

    if not tracks:
        # Fallback: just pick random tracks
        fallback = await db.execute(
            select(Track).order_by(func.random()).limit(limit)
        )
        tracks = fallback.scalars().all()

    if not tracks:
        return {"error": "No tracks found matching the criteria"}

    # Step 4: Create playlist
    playlist_name = name or criteria.get("name", f"AI: {prompt[:40]}")
    description = criteria.get("description", f"Generated from: {prompt}")

    playlist = Playlist(
        id=str(uuid.uuid4()),
        name=playlist_name,
        comment=description,
    )
    db.add(playlist)

    # Add tracks via PlaylistTrack model
    for i, track in enumerate(tracks):
        entry = PlaylistTrack(
            id=str(uuid.uuid4()),
            playlist_id=playlist.id,
            track_id=track.id,
            position=i,
        )
        db.add(entry)

    await db.commit()

    return {
        "id": playlist.id,
        "name": playlist_name,
        "track_count": len(tracks),
        "description": description,
    }
