"""Discovery API routes - Last.fm top tracks, similar artists/tracks, auth."""
from __future__ import annotations

import asyncio
import hashlib
import random
import re
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select, or_, and_, func as sqfunc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.config import get_settings
from backend.database import get_db
from backend.models.track import Track
from backend.models.artist import Artist
from backend.models.favorite import Favorite
from backend.models.recommendation import Recommendation
from backend.services import lastfm
from backend.services.soulseek import normalize_text

router = APIRouter()

# In-memory cache for Spotify new-releases. Keyed by country.
# { country: { "data": <response dict>, "expires_at": <epoch seconds> } }
_NEW_RELEASES_CACHE: dict[str, dict] = {}
_NEW_RELEASES_TTL_SECONDS = 6 * 60 * 60  # 6 hours


_PAREN_SUFFIX_RE = re.compile(r"\s*[\(\[][^\(\)\[\]]*[\)\]]\s*$")
_FEAT_RE = re.compile(r"\s+(feat\.?|featuring|ft\.?)\s+.+$", re.IGNORECASE)


def _norm_title(s: str) -> str:
    s = _PAREN_SUFFIX_RE.sub("", s).strip()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _norm_artist(s: str) -> str:
    primary = s.split(",", 1)[0]
    primary = _FEAT_RE.sub("", primary).strip()
    return re.sub(r"[^a-z0-9]", "", primary.lower())


async def _batch_library_match(
    db: AsyncSession,
    items: list[dict],
    name_key: str = "name",
    artist_key: str = "artist",
) -> None:
    """Annotate a list of dicts with in_library/track_id via a single batched query.

    Match is permissive: title and artist are normalized to alphanumerics with
    parenthetical suffixes ("(Remastered 2014)") and "feat./featuring" sections
    stripped, and the comma-joined primary artist is used. This handles the
    common cases where Spotify/Last.fm naming diverges from the local library.
    """
    if not items:
        return

    # Pull every (artist, title) pair once. Library is small (~5-10k tracks);
    # full scan is cheaper than building OR-of-100-conditions and avoids the
    # exact-match brittleness that previously caused dupes.
    lib_result = await db.execute(
        select(Track.id, Track.title, Artist.name)
        .join(Artist, Track.artist_id == Artist.id)
    )
    lib_map: dict[tuple[str, str], str] = {}
    for track_id, title, artist in lib_result.all():
        if not title or not artist:
            continue
        lib_map.setdefault((_norm_artist(artist), _norm_title(title)), track_id)

    for t in items:
        name = t.get(name_key) or ""
        artist = t.get(artist_key) or ""
        if not name or not artist:
            t["in_library"] = False
            t["track_id"] = None
            continue
        matched_id = lib_map.get((_norm_artist(artist), _norm_title(name)))
        t["in_library"] = matched_id is not None
        t["track_id"] = matched_id


async def _get_new_releases_raw(country: str) -> tuple[list[dict] | None, str | None, str | None]:
    """Cache-aware Spotify new-releases fetch. Returns (tracks, fetched_at, error).
    None tracks + error means "uncached AND fetch failed". Empty tracks + None error
    is "uncached AND Spotify creds missing"."""
    country = country.upper()
    now = time.time()
    cached = _NEW_RELEASES_CACHE.get(country)
    if cached and cached["expires_at"] > now:
        return [dict(t) for t in cached["tracks"]], cached["fetched_at"], None

    from backend.services.playlist_import import _spotify_get_token
    token = await _spotify_get_token()
    if not token:
        return [], None, "Spotify not configured"

    tracks: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            headers = {"Authorization": f"Bearer {token}"}
            resp = await client.get(
                "https://api.spotify.com/v1/browse/new-releases",
                headers=headers,
                params={"country": country, "limit": 20},
            )
            resp.raise_for_status()
            albums = resp.json().get("albums", {}).get("items", []) or []

            sem = asyncio.Semaphore(5)

            async def fetch_album_tracks(album: dict) -> list[dict]:
                album_id = album.get("id")
                if not album_id:
                    return []
                async with sem:
                    try:
                        ar = await client.get(
                            f"https://api.spotify.com/v1/albums/{album_id}/tracks",
                            headers=headers,
                            params={"limit": 10},
                        )
                        ar.raise_for_status()
                        items = ar.json().get("items", []) or []
                    except Exception:
                        return []
                primary_artist = ", ".join(
                    a.get("name", "") for a in album.get("artists", []) if a.get("name")
                )
                images = album.get("images") or []
                cover_url = images[0]["url"] if images else None
                release_date = album.get("release_date") or ""
                year = release_date[:4] if release_date else None
                album_name = album.get("name", "")
                album_id_out = album.get("id", "")
                spotify_url = (album.get("external_urls") or {}).get("spotify")

                out = []
                for t in items:
                    track_artists = ", ".join(
                        a.get("name", "") for a in t.get("artists", []) if a.get("name")
                    ) or primary_artist
                    out.append({
                        "track": t.get("name", ""),
                        "artist": track_artists,
                        "album": album_name,
                        "album_id": album_id_out,
                        "year": year,
                        "release_date": release_date,
                        "cover_url": cover_url,
                        "spotify_id": t.get("id", ""),
                        "spotify_url": (t.get("external_urls") or {}).get("spotify") or spotify_url,
                        "preview_url": t.get("preview_url"),
                        "duration_ms": t.get("duration_ms", 0),
                        "track_number": t.get("track_number"),
                    })
                return out

            results = await asyncio.gather(
                *[fetch_album_tracks(a) for a in albums], return_exceptions=True
            )
            for r in results:
                if isinstance(r, Exception):
                    continue
                tracks.extend(r)
    except httpx.HTTPError as e:
        return None, None, f"Spotify request failed: {e}"

    fetched_at = datetime.now(timezone.utc).isoformat()
    _NEW_RELEASES_CACHE[country] = {
        "tracks": [dict(t) for t in tracks],
        "fetched_at": fetched_at,
        "expires_at": now + _NEW_RELEASES_TTL_SECONDS,
    }
    return tracks, fetched_at, None


@router.get("/new-releases")
async def new_releases(
    country: str = Query("US", min_length=2, max_length=2),
    db: AsyncSession = Depends(get_db),
):
    """Return recent album drops from Spotify expanded into per-album top tracks.

    Cached in-memory for 6h per-country to avoid hammering Spotify.
    """
    country = country.upper()
    cached_hit = country in _NEW_RELEASES_CACHE and _NEW_RELEASES_CACHE[country]["expires_at"] > time.time()
    tracks, fetched_at, error = await _get_new_releases_raw(country)
    if error:
        return {
            "error": error,
            "tracks": [],
            "total": 0,
            "in_library": 0,
            "missing": 0,
        }
    await _batch_library_match(db, tracks, name_key="track")

    return {
        "tracks": tracks,
        "total": len(tracks),
        "in_library": sum(1 for t in tracks if t.get("in_library")),
        "missing": sum(1 for t in tracks if not t.get("in_library")),
        "fetched_at": fetched_at,
        "cached": cached_hit,
    }


_TAILORED_SOURCES = ("similar_track", "similar_artist", "tag")


@router.get("/weekly-radar")
async def weekly_radar(
    mode: str = Query("tailored", pattern="^(tailored|general)$"),
    db: AsyncSession = Depends(get_db),
):
    """Return missing-tracks-to-grab for the Weekly Radar tab.

    Tailored: taste-driven pending recommendations from the recommender pipeline.
    General: broader discovery — Spotify new-releases + Last.fm chart.getTopTracks
    filtered to tracks not yet in library.
    """
    fetched_at = datetime.now(timezone.utc).isoformat()

    if mode == "tailored":
        result = await db.execute(
            select(Recommendation)
            .where(
                Recommendation.status == "pending",
                Recommendation.source.in_(_TAILORED_SOURCES),
            )
            .order_by(Recommendation.score.desc(), Recommendation.created_at.desc())
            .limit(50)
        )
        recs = result.scalars().all()

        if not recs:
            return {
                "mode": "tailored",
                "tracks": [],
                "total": 0,
                "in_library": 0,
                "missing": 0,
                "last_refreshed": None,
                "fetched_at": fetched_at,
                "message": "No taste-driven recommendations yet. Run the recommendation refresh on the Schedule page or click Regenerate.",
            }

        tracks: list[dict] = [
            {
                "id": r.id,
                "track": r.track,
                "artist": r.artist,
                "album": None,
                "year": None,
                "cover_url": r.image_url,
                "score": r.score,
                "source": r.source,
                "preview_url": r.preview_url,
            }
            for r in recs
        ]
        await _batch_library_match(db, tracks, name_key="track")

        last_refreshed = max((r.created_at for r in recs if r.created_at), default=None)
        last_refreshed_iso = last_refreshed.isoformat() if last_refreshed else None

        return {
            "mode": "tailored",
            "tracks": tracks,
            "total": len(tracks),
            "in_library": sum(1 for t in tracks if t.get("in_library")),
            "missing": sum(1 for t in tracks if not t.get("in_library")),
            "last_refreshed": last_refreshed_iso,
            "fetched_at": fetched_at,
        }

    # general mode — Spotify new-releases (cached) + Last.fm chart
    pool: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def _add(track_name: str, artist_name: str, payload: dict) -> None:
        if not track_name or not artist_name:
            return
        key = (artist_name.lower(), track_name.lower())
        if key in seen:
            return
        seen.add(key)
        pool.append(payload)

    # Spotify new-releases — warm the cache on first General visit so the tab is
    # useful even before the New Releases tab has been opened.
    nr_tracks, _, _ = await _get_new_releases_raw("US")
    for raw in nr_tracks or []:
        t = raw.get("track") or ""
        a = raw.get("artist") or ""
        _add(t, a, {
            "track": t,
            "artist": a,
            "album": raw.get("album"),
            "year": raw.get("year"),
            "cover_url": raw.get("cover_url"),
            "source": "new_releases",
            "preview_url": raw.get("preview_url"),
        })

    # Last.fm global top tracks
    try:
        chart = await lastfm.get_top_tracks(limit=100, page=1)
    except Exception:
        chart = []
    for c in chart:
        t = c.get("name") or ""
        a = c.get("artist") or ""
        _add(t, a, {
            "track": t,
            "artist": a,
            "album": None,
            "year": None,
            "cover_url": None,
            "source": "trending",
        })

    # Annotate library presence so we can drop anything already in library.
    await _batch_library_match(db, pool, name_key="track")
    missing = [t for t in pool if not t.get("in_library")]
    random.shuffle(missing)
    missing = missing[:50]

    return {
        "mode": "general",
        "tracks": missing,
        "total": len(missing),
        "in_library": 0,
        "missing": len(missing),
        "last_refreshed": None,
        "fetched_at": fetched_at,
    }


@router.get("/top-tracks")
async def top_tracks(
    limit: int = Query(50, le=200),
    page: int = 1,
    db: AsyncSession = Depends(get_db),
):
    """Get Last.fm top tracks chart, annotated with library presence."""
    chart = await lastfm.get_top_tracks(limit=limit, page=page)
    await _batch_library_match(db, chart)

    return {
        "tracks": chart,
        "total": len(chart),
        "in_library": sum(1 for t in chart if t.get("in_library")),
        "missing": sum(1 for t in chart if not t.get("in_library")),
    }


@router.get("/similar-tracks")
async def similar_tracks(
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Get tracks similar to starred tracks via Last.fm."""
    # Get starred tracks
    result = await db.execute(
        select(Favorite)
        .options(selectinload(Favorite.track).selectinload(Track.artist))
        .where(Favorite.track_id.isnot(None))
        .limit(20)
    )
    favorites = result.scalars().all()

    similar = []
    seen: set[str] = set()

    for fav in favorites:
        if not fav.track or not fav.track.artist:
            continue
        artist_name = fav.track.artist.name
        track_name = fav.track.title

        tracks = await lastfm.get_similar_tracks(artist_name, track_name, limit=5)
        for t in tracks:
            key = normalize_text(f"{t['artist']} {t['name']}")
            if key in seen:
                continue
            seen.add(key)
            t["source_track"] = track_name
            t["source_artist"] = artist_name
            similar.append(t)

        if len(similar) >= limit:
            break

    similar = similar[:limit]
    await _batch_library_match(db, similar)

    return {
        "tracks": similar,
        "total": len(similar),
        "from_favorites": len(favorites),
    }


@router.get("/similar-artists")
async def similar_artists(
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Get artists similar to starred artists/tracks."""
    # Get unique artists from favorites
    result = await db.execute(
        select(Favorite)
        .options(selectinload(Favorite.track).selectinload(Track.artist))
        .where(Favorite.track_id.isnot(None))
    )
    favorites = result.scalars().all()

    fav_artists: set[str] = set()
    for fav in favorites:
        if fav.track and fav.track.artist:
            fav_artists.add(fav.track.artist.name)

    # Get existing artist names in library
    lib_result = await db.execute(select(Artist.name))
    library_artists = {r[0].lower() for r in lib_result.all()}

    similar = []
    seen: set[str] = set()
    artist_scores: dict[str, float] = {}

    for artist_name in list(fav_artists)[:15]:
        artists = await lastfm.get_similar_artists(artist_name, limit=10)
        for a in artists:
            key = a["name"].lower()
            if key in seen:
                artist_scores[key] = artist_scores.get(key, 0) + a["match"]
                continue
            seen.add(key)
            a["in_library"] = key in library_artists
            a["source_artist"] = artist_name
            artist_scores[key] = a["match"]
            similar.append(a)

    # Sort by cumulative match score
    similar.sort(key=lambda a: artist_scores.get(a["name"].lower(), 0), reverse=True)

    return {
        "artists": similar[:limit],
        "total": len(similar),
        "from_favorites": len(fav_artists),
    }


@router.get("/search")
async def discovery_search(
    q: str = Query("", min_length=1),
    limit: int = Query(30, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Search Last.fm for tracks and annotate with library presence."""
    # Try "Artist - Track" split first for artist top tracks
    parts = [p.strip() for p in q.split(" - ", 1)]
    if len(parts) == 2 and parts[0] and parts[1]:
        # Search for specific track + similar
        tracks = await lastfm.search_tracks(q, limit=limit)
    else:
        # General search — combine track search + artist top tracks
        tracks = await lastfm.search_tracks(q, limit=limit)
        # Also try as artist name for top tracks
        artist_tracks = await lastfm.get_artist_top_tracks(q, limit=min(limit, 20))
        # Merge, avoiding duplicates
        seen = {normalize_text(f"{t['artist']} {t['name']}") for t in tracks}
        for t in artist_tracks:
            key = normalize_text(f"{t['artist']} {t['name']}")
            if key not in seen:
                seen.add(key)
                tracks.append(t)

    tracks = tracks[:limit]
    await _batch_library_match(db, tracks)

    return {
        "tracks": tracks,
        "total": len(tracks),
        "in_library": sum(1 for t in tracks if t.get("in_library")),
        "missing": sum(1 for t in tracks if not t.get("in_library")),
    }


@router.get("/top-albums")
async def discover_albums(
    artist: str,
    limit: int = Query(10, le=50),
):
    """Get top albums for an artist from Last.fm."""
    albums = await lastfm.get_artist_top_albums(artist, limit=limit)
    return {"albums": albums}


@router.get("/track-info")
async def track_info(artist: str, track: str):
    """Get detailed track info from Last.fm."""
    info = await lastfm.get_track_info(artist, track)
    if not info:
        return {"error": "Track not found on Last.fm"}
    return info


@router.get("/similar-by-track")
async def similar_by_track(
    artist: str,
    track: str,
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Get tracks similar to a specific track via Last.fm, annotated with library status."""
    similar = await lastfm.get_similar_tracks(artist, track, limit=limit)
    await _batch_library_match(db, similar)

    return {
        "tracks": similar[:limit],
        "source_artist": artist,
        "source_track": track,
    }


@router.get("/remixes")
async def find_remixes(
    artist: str,
    track: str,
    limit: int = Query(30, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Find remixes, dubs, and edits of a track via Last.fm search."""
    from backend.services.remix_discovery import find_remixes as _find_remixes

    remixes = await _find_remixes(artist, track, limit=limit)
    await _batch_library_match(db, remixes)

    return {
        "remixes": remixes,
        "source_artist": artist,
        "source_track": track,
    }


@router.get("/remix-suggestions")
async def remix_suggestions(
    source: str = Query("popular", pattern="^(popular|favorites|random)$"),
    tracks_to_scan: int = Query(20, le=50),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Find remixes across multiple library tracks for bulk discovery."""
    import asyncio
    from backend.services.remix_discovery import find_remixes as _find_remixes

    # Pick source tracks
    if source == "favorites":
        result = await db.execute(
            select(Track).options(selectinload(Track.artist))
            .join(Favorite, Favorite.track_id == Track.id)
            .order_by(sqfunc.random())
            .limit(tracks_to_scan)
        )
    elif source == "popular":
        result = await db.execute(
            select(Track).options(selectinload(Track.artist))
            .where(Track.play_count > 0)
            .order_by(Track.play_count.desc())
            .limit(tracks_to_scan)
        )
    else:  # random
        result = await db.execute(
            select(Track).options(selectinload(Track.artist))
            .order_by(sqfunc.random())
            .limit(tracks_to_scan)
        )
    source_tracks = result.scalars().all()

    # Rate-limited remix search
    sem = asyncio.Semaphore(3)
    all_remixes = []
    seen: set[str] = set()

    async def scan_one(t):
        if not t.artist:
            return []
        async with sem:
            return await _find_remixes(t.artist.name, t.title, limit=5)

    tasks = [scan_one(t) for t in source_tracks]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for t, remix_list in zip(source_tracks, results):
        if isinstance(remix_list, Exception):
            continue
        for r in remix_list:
            key = normalize_text(f"{r['artist']} {r['name']}")
            if key in seen:
                continue
            seen.add(key)
            r["source_track"] = t.title
            r["source_artist"] = t.artist.name if t.artist else ""
            all_remixes.append(r)
            if len(all_remixes) >= limit:
                break
        if len(all_remixes) >= limit:
            break

    all_remixes = all_remixes[:limit]
    await _batch_library_match(db, all_remixes)

    return {
        "remixes": all_remixes,
        "source_tracks_scanned": len(source_tracks),
    }


@router.get("/artist-info")
async def artist_info(artist: str):
    """Get detailed artist info from Last.fm."""
    info = await lastfm.get_artist_info(artist)
    if not info:
        return {"error": "Artist not found on Last.fm"}
    return info


# --- Last.fm Authentication ---

@router.get("/lastfm/auth-url")
async def lastfm_auth_url(request: Request):
    """Get the Last.fm auth URL for the user to visit."""
    settings = get_settings()
    api_key = settings.lastfm.write_api_key
    if not api_key:
        return {"error": "Last.fm write API key not configured"}
    # Build callback URL so Last.fm redirects back automatically
    cb = f"{request.base_url}api/discovery/lastfm/callback"
    return {"url": f"https://www.last.fm/api/auth/?api_key={api_key}&cb={cb}"}


@router.get("/lastfm/callback")
async def lastfm_callback(token: str, request: Request):
    """Exchange a Last.fm auth token for a session key."""
    from fastapi.responses import RedirectResponse
    settings = get_settings()
    api_key = settings.lastfm.write_api_key
    secret = settings.lastfm.write_api_secret

    if not api_key or not secret:
        return {"error": "Last.fm write credentials not configured"}

    params = {
        "method": "auth.getSession",
        "api_key": api_key,
        "token": token,
    }
    sig_string = "".join(f"{k}{v}" for k, v in sorted(params.items())) + secret
    params["api_sig"] = hashlib.md5(sig_string.encode()).hexdigest()
    params["format"] = "json"

    import httpx
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get("https://ws.audioscrobbler.com/2.0/", params=params)
        data = resp.json()

    session = data.get("session", {})
    if session.get("key"):
        # Persist session key to config
        from backend.api.config_api import _read_raw_config, _write_config
        raw = _read_raw_config()
        if "lastfm" not in raw:
            raw["lastfm"] = {}
        raw["lastfm"]["session_key"] = session["key"]
        raw["lastfm"]["username"] = session.get("name", "")
        _write_config(raw)
        # If browser redirect (from Last.fm cb), redirect to settings page
        if request.headers.get("accept", "").startswith("text/html"):
            return RedirectResponse(url="/settings?lastfm_auth=ok")
        return {
            "session_key": session["key"],
            "username": session.get("name", ""),
        }
    # If browser redirect with error, redirect with error param
    if request.headers.get("accept", "").startswith("text/html"):
        return RedirectResponse(url="/settings?lastfm_auth=failed")
    return {"error": data.get("message", "Authentication failed")}


class ArtworkBatchRequest(BaseModel):
    items: list[dict]  # [{artist, track}]


@router.post("/artwork/batch")
async def get_artwork_batch(req: ArtworkBatchRequest):
    """Batch fetch artwork from iTunes Search API (up to 100 items, 10 concurrent)."""
    import asyncio
    import httpx
    import urllib.parse

    items = req.items[:100]
    results = {}
    sem = asyncio.Semaphore(10)

    async def fetch_one(client, item):
        artist = item.get("artist", "")
        track = item.get("track", "")
        key = f"{artist}::{track}".lower()
        async with sem:
            try:
                q = urllib.parse.quote(f"{artist} {track}")
                url = f"https://itunes.apple.com/search?term={q}&media=music&entity=song&limit=1"
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("results"):
                        r = data["results"][0]
                        results[key] = {
                            "image": (r.get("artworkUrl100") or "").replace("100x100", "60x60"),
                            "preview": r.get("previewUrl"),
                        }
                        return
            except Exception:
                pass
            results[key] = {"image": None, "preview": None}

    async with httpx.AsyncClient(timeout=10) as client:
        await asyncio.gather(*[fetch_one(client, item) for item in items])

    return {"results": results}


class PlaylistDiscoverRequest(BaseModel):
    limit: int = 10


@router.post("/playlists")
async def discover_playlists(req: PlaylistDiscoverRequest, db: AsyncSession = Depends(get_db)):
    """Discover playlists based on library taste profile.

    Searches Spotify and Deezer for playlists matching top genres/artists.
    """
    from backend.services.playlist_import import search_playlists

    # Get top genres and artists from library
    top_genres = (await db.execute(
        select(Track.genre, sqfunc.count()).where(Track.genre.isnot(None), Track.genre != "")
        .group_by(Track.genre).order_by(sqfunc.count().desc()).limit(5)
    )).all()

    top_artists = (await db.execute(
        select(Artist.name, sqfunc.count(Track.id))
        .join(Track, Track.artist_id == Artist.id)
        .group_by(Artist.name).order_by(sqfunc.count(Track.id).desc()).limit(5)
    )).all()

    # Build search queries from taste
    queries = []
    for genre, _ in top_genres[:3]:
        queries.append(genre)
    for artist, _ in top_artists[:2]:
        queries.append(artist)

    if not queries:
        return {"playlists": [], "queries": []}

    # Search across sources
    all_results = []
    seen = set()
    for q in queries:
        results = await search_playlists(q, limit=req.limit // len(queries) + 1)
        for r in results:
            key = f"{r['source']}:{r['id']}"
            if key not in seen:
                seen.add(key)
                r["matched_query"] = q
                all_results.append(r)

    return {"playlists": all_results[:req.limit], "queries": queries}


@router.post("/playlists/ai-rank")
async def ai_rank_playlists(playlists: list[dict], db: AsyncSession = Depends(get_db)):
    """AI-rank discovered playlists by taste compatibility."""
    from backend.services.ai.playlist_curator import rank_playlists
    from backend.services.recommender import build_taste_profile

    profile = await build_taste_profile(db)
    summary = f"Top genres: {', '.join(g['name'] for g in profile.get('genres', [])[:5])}. " \
              f"Top artists: {', '.join(a['name'] for a in profile.get('top_artists', [])[:5])}."

    ranked = await rank_playlists(playlists, summary)
    return {"playlists": ranked}
