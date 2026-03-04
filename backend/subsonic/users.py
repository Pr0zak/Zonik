"""Subsonic user endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Request, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.user import User
from backend.subsonic.responses import subsonic_response

router = APIRouter()


def _get_format(request: Request) -> str:
    return request.query_params.get("f", "json")


@router.get("/getUser")
@router.get("/getUser.view")
async def get_user(request: Request, db: AsyncSession = Depends(get_db)):
    username = request.query_params.get("username") or request.query_params.get("u", "admin")

    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()

    if not user:
        # Return a default response for unknown users
        return subsonic_response({
            "user": {
                "username": username,
                "scrobblingEnabled": "true",
                "adminRole": "false",
                "settingsRole": "true",
                "downloadRole": "true",
                "uploadRole": "false",
                "playlistRole": "true",
                "coverArtRole": "true",
                "commentRole": "true",
                "podcastRole": "false",
                "streamRole": "true",
                "jukeboxRole": "false",
                "shareRole": "false",
                "videoConversionRole": "false",
                "folder": [1],
            }
        }, _get_format(request))

    return subsonic_response({
        "user": {
            "username": user.username,
            "scrobblingEnabled": "true",
            "adminRole": str(user.is_admin).lower(),
            "settingsRole": "true",
            "downloadRole": "true",
            "uploadRole": "false",
            "playlistRole": "true",
            "coverArtRole": "true",
            "commentRole": "true",
            "podcastRole": "false",
            "streamRole": "true",
            "jukeboxRole": "false",
            "shareRole": "false",
            "videoConversionRole": "false",
            "folder": [1],
        }
    }, _get_format(request))
