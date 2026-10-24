"""Per-device app tokens (phone, TV, watch): `zk_` + random, stored as its sha256.

Accepted as `Authorization: Bearer <token>` on /api and as the OpenSubsonic `apiKey` param.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.tokens import hash_token, new_token
from backend.models.auth import AuthSession, DeviceToken
from backend.models.user import User

DEVICE_PREFIX = "zk_"
PLATFORMS = ("android", "tv", "wear", "web", "other")
TOUCH_INTERVAL = timedelta(minutes=5)


def normalize_platform(platform: str | None) -> str:
    p = (platform or "").strip().lower()
    return p if p in PLATFORMS else "other"


async def create_device_token(db: AsyncSession, user: User, *, label: str | None, platform: str | None) -> tuple[str, DeviceToken]:
    """New device token for user; returns (token, row). Commits."""
    token = DEVICE_PREFIX + new_token()
    row = DeviceToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_hash=hash_token(token),
        label=(label or "").strip()[:80] or None,
        platform=normalize_platform(platform),
        created_at=datetime.utcnow(),
    )
    db.add(row)
    await db.commit()
    return token, row


async def lookup_device_token(db: AsyncSession, token: str) -> DeviceToken | None:
    """The unrevoked device token row, or None. last_seen_at moves at most every 5 min."""
    if not token:
        return None
    row = (await db.execute(
        select(DeviceToken).where(DeviceToken.token_hash == hash_token(token))
    )).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return None
    now = datetime.utcnow()
    if row.last_seen_at is None or now - row.last_seen_at > TOUCH_INTERVAL:
        row.last_seen_at = now
        await db.commit()
    return row


async def revoke_user_devices(db: AsyncSession, user_id: str) -> None:
    """Revoke every device token of a user. Caller commits."""
    await db.execute(
        update(DeviceToken)
        .where(DeviceToken.user_id == user_id, DeviceToken.revoked_at.is_(None))
        .values(revoked_at=datetime.utcnow())
    )


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


async def list_user_items(db: AsyncSession, user_id: str, *, current_session_id: str | None = None,
                          current_device_id: str | None = None) -> list[dict]:
    """A user's live web sessions and unrevoked device tokens, most recently seen first.
    Shared by /api/auth/devices (the caller's own) and /api/users/{id}/devices (admin view)."""
    now = datetime.utcnow()
    sessions = (await db.execute(
        select(AuthSession).where(AuthSession.user_id == user_id, AuthSession.expires_at > now)
    )).scalars().all()
    devices = (await db.execute(
        select(DeviceToken).where(DeviceToken.user_id == user_id, DeviceToken.revoked_at.is_(None))
    )).scalars().all()
    out = [
        {"id": s.id, "kind": "session", "label": s.label, "platform": "web", "ip": s.ip,
         "created_at": _iso(s.created_at), "last_seen_at": _iso(s.last_seen_at),
         "current": current_session_id is not None and s.id == current_session_id}
        for s in sessions
    ] + [
        {"id": d.id, "kind": "device", "label": d.label, "platform": d.platform, "ip": None,
         "created_at": _iso(d.created_at), "last_seen_at": _iso(d.last_seen_at),
         "current": current_device_id is not None and d.id == current_device_id}
        for d in devices
    ]
    out.sort(key=lambda r: r["last_seen_at"] or r["created_at"] or "", reverse=True)
    return out


async def revoke_user_item(db: AsyncSession, user_id: str, item_id: str) -> str | None:
    """Revoke one of a user's sessions (deleted) or device tokens (revoked_at set). Commits.
    Returns "session" / "device", or None when the user has no such item."""
    session_row = (await db.execute(
        select(AuthSession).where(AuthSession.id == item_id, AuthSession.user_id == user_id)
    )).scalar_one_or_none()
    if session_row is not None:
        await db.execute(delete(AuthSession).where(AuthSession.id == item_id))
        await db.commit()
        return "session"
    device = (await db.execute(
        select(DeviceToken).where(DeviceToken.id == item_id, DeviceToken.user_id == user_id)
    )).scalar_one_or_none()
    if device is None:
        return None
    if device.revoked_at is None:
        device.revoked_at = datetime.utcnow()
        await db.commit()
    return "device"
