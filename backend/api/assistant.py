"""Assistant API — voice-driven playlist creation.

Phase 1 of the AI voice feature: a spoken request (phone mic, later Android
Auto) is transcribed client-side and POSTed here as plain text. We reuse the
AI playlist pipeline to turn it into an ordered, playable list of track IDs.
Defaults to "play only" (no persisted Playlist) so spoken mixes don't clutter
the library.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.services.ai.playlist_gen import generate_playlist

log = logging.getLogger(__name__)

router = APIRouter()

MAX_SIZE = 200


class VoicePlaylistRequest(BaseModel):
    prompt: str
    size: int = 50
    save: bool = False  # ephemeral "play only" by default


@router.post("/voice-playlist")
async def voice_playlist(req: VoicePlaylistRequest, db: AsyncSession = Depends(get_db)):
    """Turn a spoken request into an ordered, playable list of track IDs.

    Returns {id, name, description, track_count, track_ids[]} or {error}.
    The client maps track_ids -> playback. `id` is null unless save=True.
    """
    prompt = (req.prompt or "").strip()
    if not prompt:
        return {"error": "Empty request — nothing to build a mix from"}

    size = max(1, min(req.size, MAX_SIZE))
    result = await generate_playlist(db, prompt, limit=size, save=req.save)

    if "error" in result:
        log.info("[voice-playlist] %r failed: %s", prompt[:60], result["error"])
        return result

    log.info(
        "[voice-playlist] %r -> %d tracks (%s)",
        prompt[:60], result.get("track_count", 0), result.get("name"),
    )
    return result
