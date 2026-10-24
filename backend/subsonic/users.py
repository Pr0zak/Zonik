"""Subsonic user endpoints: getUser (real users only) and getUsers (admins only)."""
from __future__ import annotations

from fastapi import APIRouter, Request, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.user import User
from backend.services.user_data import caller_user, is_admin
from backend.subsonic.responses import subsonic_response, error_response

router = APIRouter()


def _get_format(request: Request) -> str:
    return request.query_params.get("f", "json")


def _user_entry(user: User) -> dict:
    admin = str(user.role == "admin").lower()
    return {
        "username": user.username,
        "scrobblingEnabled": "true",
        "adminRole": admin,
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


@router.get("/getUser")
@router.get("/getUser.view")
async def get_user(request: Request, db: AsyncSession = Depends(get_db)):
    """A user's roles. Without `username` it is the caller (the owner for anonymous
    grace-mode calls). Asking about someone else needs admin, as in the Subsonic spec."""
    me = await caller_user(request, db)
    username = request.query_params.get("username") or (me.username if me else request.query_params.get("u"))
    if not username:
        return error_response(70, "User not found", _get_format(request))
    if me is not None and username != me.username and not is_admin(me):
        return error_response(50, "User is not authorized for the given operation", _get_format(request))

    user = me if me is not None and me.username == username else (
        await db.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()
    if not user:
        return error_response(70, "User not found", _get_format(request))
    return subsonic_response({"user": _user_entry(user)}, _get_format(request))


@router.get("/getUsers")
@router.get("/getUsers.view")
async def get_users(request: Request, db: AsyncSession = Depends(get_db)):
    me = await caller_user(request, db)
    if me is not None and not is_admin(me):
        return error_response(50, "User is not authorized for the given operation", _get_format(request))
    users = (await db.execute(select(User).order_by(User.created_at))).scalars().all()
    return subsonic_response({"users": {"user": [_user_entry(u) for u in users]}}, _get_format(request))
