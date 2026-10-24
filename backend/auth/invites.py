"""Invite links (P3): lookup, the join URL, username rules and the code-guess lockout.

An invite is single use. It's consumed by POST /api/auth/join with a conditional UPDATE so two
people racing on one link can't both get an account (see consume()).
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime

from fastapi import Request
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.invite import Invite
from backend.models.user import User

INVALID_MESSAGE = "This invite link is invalid or has expired"
# Failed code lookups share the login lockout, keyed per IP under a name no username can have.
LOCKOUT_NAME = "#invite"
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
MIN_EXPIRES_DAYS = 1
MAX_EXPIRES_DAYS = 30


def new_code() -> str:
    return secrets.token_urlsafe(9)


def username_problem(username: str) -> str | None:
    if not USERNAME_RE.match(username or ""):
        return "Username must be 3-32 characters: letters, digits, '_', '.' or '-'"
    return None


async def username_taken(db: AsyncSession, username: str) -> bool:
    row = (await db.execute(
        select(User.id).where(func.lower(User.username) == username.lower()).limit(1)
    )).first()
    return row is not None


async def find_valid(db: AsyncSession, code: str) -> Invite | None:
    """The invite for code when it's still usable (not used, revoked or expired), else None."""
    if not code:
        return None
    invite = (await db.execute(select(Invite).where(Invite.code == code))).scalar_one_or_none()
    if invite is None or invite.status() != "active":
        return None
    return invite


async def consume(db: AsyncSession, invite_id: str, user_id: str) -> bool:
    """Mark the invite used by user_id, only if it is still usable. True when this call won.
    Doesn't commit: the caller commits it together with the new user, or rolls both back."""
    now = datetime.utcnow()
    result = await db.execute(
        update(Invite)
        .where(Invite.id == invite_id, Invite.used_at.is_(None), Invite.revoked_at.is_(None),
               Invite.expires_at > now)
        .values(used_at=now, used_by=user_id)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def _first(value: str | None) -> str | None:
    value = (value or "").split(",")[0].strip()
    return value or None


def base_url(request: Request) -> str:
    """The URL the caller reached us on, honouring X-Forwarded-Proto/Host from the proxy."""
    proto = _first(request.headers.get("x-forwarded-proto"))
    host = _first(request.headers.get("x-forwarded-host"))
    if host:
        return f"{proto or request.url.scheme}://{host}".rstrip("/")
    base = str(request.base_url).rstrip("/")
    if proto and "://" in base:
        base = f"{proto}://{base.split('://', 1)[1]}"
    return base


def invite_url(request: Request, code: str) -> str:
    return f"{base_url(request)}/join/{code}"
