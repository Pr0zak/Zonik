"""OpenSubsonic API router with auth middleware."""
from __future__ import annotations

from fastapi import APIRouter, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.subsonic.auth import authenticate_subsonic, _client_ip
from backend.subsonic.activity import record_activity
from backend.subsonic import system, browsing, lists, search, playlists_api, media, annotation, bookmarks, users


async def _track_subsonic_activity(request: Request) -> None:
    """Bump Live activity counters for every /rest/* call.

    Runs regardless of whether the handler authenticates — gives the Live
    view a true picture of which clients are hitting the API.
    """
    params = request.query_params
    username = params.get("u")
    if not username:
        return
    record_activity(
        username,
        params.get("c"),
        request.headers.get("user-agent"),
        _client_ip(request),
    )


router = APIRouter(dependencies=[Depends(_track_subsonic_activity)])

# Include all sub-routers
router.include_router(system.router)
router.include_router(browsing.router)
router.include_router(lists.router)
router.include_router(search.router)
router.include_router(playlists_api.router)
router.include_router(media.router)
router.include_router(annotation.router)
router.include_router(bookmarks.router)
router.include_router(users.router)
