"""OpenSubsonic API router with auth middleware."""
from __future__ import annotations

from fastapi import APIRouter, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.subsonic.auth import authenticate_subsonic
from backend.subsonic import system, browsing, lists, search, playlists_api, media, annotation, bookmarks, users

router = APIRouter()

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
