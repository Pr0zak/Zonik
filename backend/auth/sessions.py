"""Web login sessions: an HttpOnly cookie holding a random token, stored as its sha256."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.tokens import hash_token, new_token
from backend.config import get_settings
from backend.models.auth import AuthSession
from backend.models.user import User

SESSION_COOKIE = "zonik_session"
# Sliding expiry: a session used again after this long gets last_seen/expires_at pushed out.
TOUCH_INTERVAL = timedelta(minutes=5)


def session_lifetime() -> timedelta:
    return timedelta(days=max(1, get_settings().auth.session_days))


def short_label(user_agent: str | None) -> str | None:
    """"Firefox on Linux" style label from a User-Agent, else its first 60 chars."""
    if not user_agent:
        return None
    ua = user_agent
    browser = next((name for pat, name in (
        (r"Edg/", "Edge"), (r"OPR/", "Opera"), (r"Firefox/", "Firefox"),
        (r"Chrome/", "Chrome"), (r"Safari/", "Safari"), (r"okhttp", "Zonik app"),
    ) if re.search(pat, ua)), None)
    system = next((name for pat, name in (
        (r"Android", "Android"), (r"iPhone|iPad", "iOS"), (r"Windows", "Windows"),
        (r"Mac OS X|Macintosh", "macOS"), (r"CrOS", "ChromeOS"), (r"Linux", "Linux"),
    ) if re.search(pat, ua)), None)
    if browser and system:
        return f"{browser} on {system}"
    return browser or system or ua[:60]


async def create_session(db: AsyncSession, user: User, *, user_agent: str | None, ip: str | None) -> tuple[str, AuthSession]:
    """New session for user; returns (cookie token, row). Commits."""
    token = new_token()
    now = datetime.utcnow()
    row = AuthSession(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_hash=hash_token(token),
        label=short_label(user_agent),
        ip=ip,
        created_at=now,
        last_seen_at=now,
        expires_at=now + session_lifetime(),
    )
    db.add(row)
    await db.commit()
    return token, row


async def lookup_session(db: AsyncSession, token: str) -> AuthSession | None:
    """The live session for a cookie token (sliding its expiry), or None."""
    if not token:
        return None
    row = (await db.execute(
        select(AuthSession).where(AuthSession.token_hash == hash_token(token))
    )).scalar_one_or_none()
    if row is None:
        return None
    now = datetime.utcnow()
    if row.expires_at and row.expires_at <= now:
        await db.delete(row)
        await db.commit()
        return None
    if row.last_seen_at is None or now - row.last_seen_at > TOUCH_INTERVAL:
        row.last_seen_at = now
        row.expires_at = now + session_lifetime()
        await db.commit()
    return row


async def delete_user_sessions(db: AsyncSession, user_id: str, *, keep_id: str | None = None) -> None:
    """Drop every session of a user (except keep_id). Caller commits."""
    stmt = delete(AuthSession).where(AuthSession.user_id == user_id)
    if keep_id:
        stmt = stmt.where(AuthSession.id != keep_id)
    await db.execute(stmt)
