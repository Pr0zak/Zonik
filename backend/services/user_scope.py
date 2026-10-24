"""Per-user scoping helpers for the analytics side of multi-user P2 (taste, recommendations,
Live, dashboard, Music Map listening layers, AI context).

Thin additions on top of backend.services.user_data (the shared contract): resolving a
"whose data" id when a caller passes None, and the owner-only bits (the Last.fm account in
zonik.toml and pre-multi-user leftovers belong to the owner).
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import HTTPConnection

from backend.models.user import User
from backend.services.user_data import caller, owner_id


async def resolve_user_id(db: AsyncSession, user_id: str | None) -> str | None:
    """user_id, or the owner when None (scheduler/single-user callers)."""
    return user_id or await owner_id(db)


async def is_owner(db: AsyncSession, user_id: str | None) -> bool:
    if not user_id:
        return False
    return user_id == await owner_id(db)


def caller_is_admin(conn: HTTPConnection) -> bool:
    """True for an admin caller. No resolved user at all (a server without accounts, or
    the auth columns not migrated yet) behaves like the single-user server it is."""
    user = caller(conn)
    return user is None or getattr(user, "role", None) == "admin"


async def usernames(db: AsyncSession) -> dict[str, str]:
    """{user id: username} for every account."""
    from sqlalchemy import select
    return {uid: name for uid, name in (await db.execute(select(User.id, User.username))).all()}
