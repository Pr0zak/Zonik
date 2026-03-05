"""Metadata enrichment pipeline: MusicBrainz + Last.fm + cover art."""
from __future__ import annotations

import asyncio
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.track import Track
from backend.models.artist import Artist
from backend.models.album import Album
from backend.services import lastfm
from backend.services.artwork import fetch_and_cache_cover

log = logging.getLogger(__name__)

MB_BASE = "https://musicbrainz.org/ws/2"
MB_HEADERS = {"User-Agent": "Zonik/0.1.0 (music backend)", "Accept": "application/json"}

# Per-track timeout for the entire enrichment pipeline
ENRICH_TRACK_TIMEOUT = 45
# Timeout for cover art fetch specifically (can be slow)
COVER_ART_TIMEOUT = 20


async def enrich_track(db: AsyncSession, track: Track) -> dict:
    """Run the full enrichment pipeline on a track.

    1. MusicBrainz + Last.fm lookups (concurrent)
    2. Cover art (multi-source, with timeout)
    3. Update DB records
    """
    changes = {}
    artist_name = track.artist.name if track.artist else None
    album_title = track.album.title if track.album else None
    track_label = f"{artist_name} - {track.title}" if artist_name else track.title

    # 1. Run MusicBrainz + Last.fm lookups concurrently
    mb_task = _lookup_musicbrainz(track, artist_name)
    lfm_task = _lookup_lastfm(track, artist_name)

    mb_changes, lfm_changes = await asyncio.gather(
        mb_task, lfm_task, return_exceptions=True
    )

    if isinstance(mb_changes, dict):
        changes.update(mb_changes)
    elif isinstance(mb_changes, Exception):
        log.warning(f"[enrich] MusicBrainz failed for {track_label}: {mb_changes}")

    if isinstance(lfm_changes, dict):
        changes.update(lfm_changes)
    elif isinstance(lfm_changes, Exception):
        log.warning(f"[enrich] Last.fm failed for {track_label}: {lfm_changes}")

    # 2. Cover art (with dedicated timeout)
    if not track.cover_art_path:
        try:
            cover_path = await asyncio.wait_for(
                fetch_and_cache_cover(
                    artist=artist_name or "Unknown",
                    album=album_title,
                    track=track.title,
                ),
                timeout=COVER_ART_TIMEOUT,
            )
            if cover_path:
                track.cover_art_path = cover_path
                changes["cover_art"] = cover_path
                if track.album and not track.album.cover_art_path:
                    track.album.cover_art_path = cover_path
        except asyncio.TimeoutError:
            log.warning(f"[enrich] Cover art fetch timed out for {track_label}")
        except Exception as e:
            log.warning(f"[enrich] Cover art failed for {track_label}: {e}")

    if changes:
        await db.commit()

    return changes


async def _lookup_musicbrainz(track: Track, artist_name: str | None) -> dict:
    """MusicBrainz lookup — returns changes dict."""
    changes = {}
    if track.musicbrainz_id:
        mb_data = await _musicbrainz_recording(track.musicbrainz_id)
        if mb_data:
            if not track.title or track.title == track.file_path.split("/")[-1]:
                track.title = mb_data.get("title", track.title)
                changes["title"] = track.title
    elif artist_name and track.title:
        mb_data = await _musicbrainz_search(artist_name, track.title)
        if mb_data:
            track.musicbrainz_id = mb_data.get("id")
            changes["musicbrainz_id"] = track.musicbrainz_id
    return changes


async def _lookup_lastfm(track: Track, artist_name: str | None) -> dict:
    """Last.fm lookup — returns changes dict."""
    changes = {}
    if not (artist_name and track.title):
        return changes

    lfm_info = await lastfm.get_track_info(artist_name, track.title)
    if lfm_info:
        tags = lfm_info.get("tags", [])
        if tags and not track.genre:
            track.genre = tags[0]
            changes["genre"] = track.genre

        if track.artist and not track.artist.biography:
            artist_info = await lastfm.get_artist_info(artist_name)
            if artist_info:
                track.artist.biography = artist_info.get("bio", "")
                if artist_info.get("image"):
                    track.artist.image_url = artist_info["image"]
                if artist_info.get("mbid") and not track.artist.musicbrainz_id:
                    track.artist.musicbrainz_id = artist_info["mbid"]

    return changes


async def enrich_batch(db: AsyncSession, track_ids: list[str]) -> dict:
    """Enrich a batch of tracks. Returns summary stats."""
    stats = {"processed": 0, "enriched": 0, "errors": 0}

    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(Track).options(selectinload(Track.artist), selectinload(Track.album))
        .where(Track.id.in_(track_ids))
    )
    tracks = result.scalars().all()

    for track in tracks:
        stats["processed"] += 1
        try:
            changes = await enrich_track(db, track)
            if changes:
                stats["enriched"] += 1
        except Exception as e:
            log.error(f"Enrichment failed for {track.title}: {e}")
            stats["errors"] += 1

    return stats


async def _musicbrainz_recording(mbid: str) -> dict | None:
    """Look up a recording by MusicBrainz ID."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{MB_BASE}/recording/{mbid}",
                params={"fmt": "json", "inc": "artists+releases+tags"},
                headers=MB_HEADERS,
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        log.debug(f"MusicBrainz lookup failed: {e}")
    return None


async def _musicbrainz_search(artist: str, title: str) -> dict | None:
    """Search MusicBrainz for a recording."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{MB_BASE}/recording",
                params={
                    "query": f'artist:"{artist}" AND recording:"{title}"',
                    "limit": 1, "fmt": "json",
                },
                headers=MB_HEADERS,
            )
            if resp.status_code == 200:
                data = resp.json()
                recordings = data.get("recordings", [])
                if recordings:
                    return recordings[0]
    except Exception as e:
        log.debug(f"MusicBrainz search failed: {e}")
    return None
