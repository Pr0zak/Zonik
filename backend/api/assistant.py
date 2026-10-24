"""Assistant API — voice-driven playlist creation.

Phase 1 of the AI voice feature: a spoken request (phone mic, later Android
Auto) is transcribed client-side and POSTed here as plain text. We reuse the
AI playlist pipeline to turn it into an ordered, playable list of track IDs.
Defaults to "play only" (no persisted Playlist) so spoken mixes don't clutter
the library.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.services.ai.playlist_gen import generate_playlist
from backend.services.user_data import caller_id

log = logging.getLogger(__name__)

router = APIRouter()

MAX_SIZE = 200


class VoicePlaylistRequest(BaseModel):
    prompt: str
    size: int = 50
    save: bool = False  # ephemeral "play only" by default
    suggest_missing: bool = True  # also name fitting songs the library lacks


@router.post("/voice-playlist")
async def voice_playlist(req: VoicePlaylistRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Turn a spoken request into an ordered, playable list of track IDs.

    Returns {id, name, description, track_count, track_ids[], missing[]} or
    {error, missing?}. The client maps track_ids -> playback. `id` is null
    unless save=True. `missing` lists catalog songs that fit the request but
    aren't in the library (each with a `reason`), for the client to offer.
    """
    prompt = (req.prompt or "").strip()
    if not prompt:
        return {"error": "Empty request — nothing to build a mix from"}

    size = max(1, min(req.size, MAX_SIZE))
    # The mix comes from the library; in parallel, ask which specific songs fit
    # the request so the ones not owned can be offered ("Get the 4 missing").
    from backend.services.ai import track_resolver
    wants_missing = req.suggest_missing and track_resolver.enabled()
    # The caller's listening steers the mix; a saved mix is the caller's playlist.
    playlist_task = generate_playlist(db, prompt, limit=size, save=req.save,
                                      user_id=await caller_id(request, db))
    if wants_missing:
        result, suggestions = await asyncio.gather(playlist_task, track_resolver.resolve(prompt, limit=8))
    else:
        result, suggestions = await playlist_task, []

    missing: list[dict] = []
    if suggestions:
        from backend.api.catalog import _annotate
        await _annotate(db, suggestions)
        missing = [t for t in suggestions if not t["in_library"]]

    if "error" in result and missing:
        # Nothing in the library fits, but songs that do exist: offer those.
        log.info("[voice-playlist] %r: no library mix, %d songs to get", prompt[:60], len(missing))
        return {**result, "missing": missing}

    if "error" in result:
        log.info("[voice-playlist] %r failed: %s", prompt[:60], result["error"])
        return result

    log.info(
        "[voice-playlist] %r -> %d tracks (%s), %d missing",
        prompt[:60], result.get("track_count", 0), result.get("name"), len(missing),
    )
    return {**result, "missing": missing}
