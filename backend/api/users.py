"""User management API routes (admin only — see backend/auth/policy.py): accounts, invite
links (P3) and an admin view of each user's sessions/devices."""
from __future__ import annotations

import io
import secrets
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import invites
from backend.auth.devices import list_user_items, revoke_user_devices, revoke_user_item
from backend.auth.passwords import check_password, hash_password, new_password_problem
from backend.auth.sessions import delete_user_sessions
from backend.database import get_db
from backend.models.auth import DeviceToken
from backend.models.invite import Invite
from backend.models.user import ROLES, User

router = APIRouter()


class UserCreate(BaseModel):
    username: str
    password: str
    is_admin: bool = False
    role: str | None = None
    display_name: str | None = None


class UserUpdate(BaseModel):
    display_name: str | None = None
    role: str | None = None
    disabled: bool | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class PasswordReset(BaseModel):
    new_password: str


class InviteCreate(BaseModel):
    role: str = "user"
    note: str | None = None
    expires_days: int = 7


async def _get_user(db: AsyncSession, user_id: str) -> User:
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    return user


def _caller_id(request: Request) -> str | None:
    caller = getattr(request.state, "user", None)
    return caller.id if caller is not None else None


async def _other_enabled_admins(db: AsyncSession, user_id: str) -> int:
    return (await db.execute(
        select(func.count(User.id)).where(User.role == "admin", User.disabled.is_(False), User.id != user_id)
    )).scalar() or 0


async def _guard_admin_loss(db: AsyncSession, request: Request, user: User, action: str) -> None:
    """Refuse to demote/disable/delete yourself or the last enabled admin."""
    if user.id == _caller_id(request):
        raise HTTPException(400, f"You can't {action} your own account")
    if user.role == "admin" and not user.disabled and await _other_enabled_admins(db, user.id) == 0:
        raise HTTPException(400, f"Can't {action} the last enabled admin")


def _user_row(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name,
        "role": u.role,
        "is_admin": u.role == "admin",
        "disabled": bool(u.disabled),
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        "has_api_key": bool(u.subsonic_api_key),
        "subsonic_api_key": u.subsonic_api_key or "",
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


async def _usernames(db: AsyncSession, ids: set[str]) -> dict[str, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = await db.execute(select(User.id, User.username).where(User.id.in_(ids)))
    return {uid: name for uid, name in rows.all()}


def _invite_row(inv: Invite, request: Request, names: dict[str, str], now: datetime) -> dict:
    def who(uid: str | None):
        return {"id": uid, "username": names.get(uid)} if uid else None

    return {
        "id": inv.id,
        "code": inv.code,
        "url": invites.invite_url(request, inv.code),
        "role": inv.role,
        "note": inv.note,
        "status": inv.status(now),
        "created_at": _iso(inv.created_at),
        "expires_at": _iso(inv.expires_at),
        "used_at": _iso(inv.used_at),
        "used_by": who(inv.used_by),
        "created_by": who(inv.created_by),
    }


async def _get_invite(db: AsyncSession, invite_id: str) -> Invite:
    invite = await db.get(Invite, invite_id)
    if invite is None:
        raise HTTPException(404, "Invite not found")
    return invite


# --- invites (declared before the /{user_id} routes) ------------------------------------

@router.post("/invites")
async def create_invite(req: InviteCreate, request: Request, db: AsyncSession = Depends(get_db)):
    if req.role not in ROLES:
        raise HTTPException(400, f"Role must be one of: {', '.join(ROLES)}")
    if not invites.MIN_EXPIRES_DAYS <= req.expires_days <= invites.MAX_EXPIRES_DAYS:
        raise HTTPException(400, f"expires_days must be {invites.MIN_EXPIRES_DAYS}-{invites.MAX_EXPIRES_DAYS}")
    created_by = _caller_id(request)
    if created_by is None:
        raise HTTPException(401, "Not authenticated")
    now = datetime.utcnow()
    invite = Invite(
        id=str(uuid.uuid4()),
        code=invites.new_code(),
        role=req.role,
        note=(req.note or "").strip()[:200] or None,
        created_by=created_by,
        created_at=now,
        expires_at=now + timedelta(days=req.expires_days),
    )
    db.add(invite)
    await db.commit()
    return _invite_row(invite, request, await _usernames(db, {created_by}), now)


@router.get("/invites")
async def list_invites(request: Request, include_used: bool = False, db: AsyncSession = Depends(get_db)):
    """Newest first. Without include_used only active invites are listed."""
    rows = (await db.execute(select(Invite).order_by(Invite.created_at.desc()))).scalars().all()
    now = datetime.utcnow()
    if not include_used:
        rows = [r for r in rows if r.status(now) == "active"]
    names = await _usernames(db, {r.created_by for r in rows} | {r.used_by for r in rows if r.used_by})
    return [_invite_row(r, request, names, now) for r in rows]


@router.delete("/invites/{invite_id}")
async def revoke_invite(invite_id: str, db: AsyncSession = Depends(get_db)):
    invite = await _get_invite(db, invite_id)
    if invite.used_at is not None:
        raise HTTPException(400, "Invite already used")
    if invite.revoked_at is None:
        invite.revoked_at = datetime.utcnow()
        await db.commit()
    return {"ok": True}


@router.get("/invites/{invite_id}/qr.svg")
async def invite_qr(invite_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    import segno
    invite = await _get_invite(db, invite_id)
    buf = io.BytesIO()
    segno.make(invites.invite_url(request, invite.code), error="m").save(buf, kind="svg", scale=6, border=2)
    return Response(buf.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


@router.get("")
async def list_users(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).order_by(User.username))
    return [_user_row(u) for u in result.scalars().all()]


@router.post("")
async def create_user(req: UserCreate, db: AsyncSession = Depends(get_db)):
    username = req.username.strip()
    if not username:
        raise HTTPException(400, "Username is required")
    role = req.role or ("admin" if req.is_admin else "user")
    if role not in ROLES:
        raise HTTPException(400, f"Role must be one of: {', '.join(ROLES)}")
    if not req.password:
        raise HTTPException(400, "Password is required")
    existing = await db.execute(select(User).where(User.username == username))
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Username already exists")
    user = User(
        id=str(uuid.uuid4()),
        username=username,
        password_hash=hash_password(req.password),
        role=role,
        display_name=(req.display_name or "").strip() or None,
    )
    db.add(user)
    await db.commit()
    return {"id": user.id, "username": user.username}


@router.put("/{user_id}")
async def update_user(user_id: str, req: UserUpdate, request: Request, db: AsyncSession = Depends(get_db)):
    user = await _get_user(db, user_id)
    if req.role is not None and req.role not in ROLES:
        raise HTTPException(400, f"Role must be one of: {', '.join(ROLES)}")
    if req.role is not None and req.role != "admin" and user.role == "admin":
        await _guard_admin_loss(db, request, user, "demote")
    if req.disabled and not user.disabled:
        await _guard_admin_loss(db, request, user, "disable")

    if "display_name" in req.model_fields_set:
        user.display_name = (req.display_name or "").strip() or None
    if req.role is not None:
        user.role = req.role
    if req.disabled is not None and req.disabled != user.disabled:
        user.disabled = req.disabled
        if req.disabled:
            # Disabling ends every way in: web sessions and app device tokens.
            await delete_user_sessions(db, user.id)
            await revoke_user_devices(db, user.id)
    await db.commit()
    return _user_row(user)


@router.post("/{user_id}/reset-password")
async def reset_password(user_id: str, req: PasswordReset, db: AsyncSession = Depends(get_db)):
    """Admin sets a new password (no current one needed); the user's web sessions end."""
    user = await _get_user(db, user_id)
    problem = new_password_problem(req.new_password)
    if problem:
        raise HTTPException(400, problem)
    user.password_hash = hash_password(req.new_password)
    await delete_user_sessions(db, user.id)
    await db.commit()
    return {"ok": True}


@router.put("/{user_id}/password")
async def change_password(user_id: str, req: PasswordChange, db: AsyncSession = Depends(get_db)):
    user = await _get_user(db, user_id)
    if not check_password(req.current_password, user.password_hash):
        raise HTTPException(403, "Current password is incorrect")
    user.password_hash = hash_password(req.new_password)
    await db.commit()
    return {"ok": True}


@router.post("/{user_id}/api-key")
async def generate_api_key(user_id: str, db: AsyncSession = Depends(get_db)):
    """Generate a new Subsonic API key for token-based auth (e.g. Zonik-mobile)."""
    user = await _get_user(db, user_id)
    user.subsonic_api_key = secrets.token_hex(16)
    await db.commit()
    return {"ok": True, "api_key": user.subsonic_api_key}


@router.delete("/{user_id}/api-key")
async def revoke_api_key(user_id: str, db: AsyncSession = Depends(get_db)):
    """Revoke a user's Subsonic API key."""
    user = await _get_user(db, user_id)
    user.subsonic_api_key = None
    await db.commit()
    return {"ok": True}


@router.get("/{user_id}/devices")
async def list_user_devices(user_id: str, db: AsyncSession = Depends(get_db)):
    """Admin view of a user's sessions and device tokens (same shape as /api/auth/devices)."""
    user = await _get_user(db, user_id)
    return await list_user_items(db, user.id)


@router.delete("/{user_id}/devices/{item_id}")
async def revoke_user_device(user_id: str, item_id: str, db: AsyncSession = Depends(get_db)):
    user = await _get_user(db, user_id)
    if await revoke_user_item(db, user.id, item_id) is None:
        raise HTTPException(404, "Not found")
    return {"ok": True}


@router.delete("/{user_id}")
async def delete_user(user_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user = await _get_user(db, user_id)
    await _guard_admin_loss(db, request, user, "delete")
    await delete_user_sessions(db, user.id)
    await db.execute(delete(DeviceToken).where(DeviceToken.user_id == user.id))
    await db.delete(user)
    await db.commit()
    return {"ok": True}
