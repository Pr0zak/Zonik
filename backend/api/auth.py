"""/api/auth — web login, first-run setup, the caller's own account and devices.

status, login, setup, device and logout are public (see backend/auth/policy.py); the rest
need real credentials — the grace-mode owner stand-in does not count as logged in.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import lockout
from backend.auth.devices import create_device_token
from backend.auth.passwords import check_password, hash_password, must_change_password, new_password_problem
from backend.auth.permissions import permissions_for
from backend.auth.resolve import client_ip, is_authenticated
from backend.auth.sessions import SESSION_COOKIE, create_session, delete_user_sessions, lookup_session, session_lifetime
from backend.config import get_settings
from backend.database import get_db
from backend.models.auth import AuthSession, DeviceToken
from backend.models.user import User

router = APIRouter()


class SetupRequest(BaseModel):
    username: str
    password: str
    display_name: str | None = None


class LoginRequest(BaseModel):
    username: str
    password: str


class DeviceLoginRequest(BaseModel):
    username: str
    password: str
    label: str | None = None
    platform: str | None = None


class MeUpdate(BaseModel):
    display_name: str | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


def me_payload(user: User, auth_method: str | None) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "is_admin": user.role == "admin",
        "permissions": permissions_for(user),
        "must_change_password": must_change_password(user.password_hash),
        "auth_method": auth_method,
    }


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, token,
        max_age=int(session_lifetime().total_seconds()),
        path="/", httponly=True, samesite="lax", secure=False,
    )


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax")


def _caller(request: Request) -> User:
    """The real (credentialed) caller, else 401."""
    if not is_authenticated(request):
        raise HTTPException(401, "Not authenticated")
    return request.state.user


def _lockout_message(minutes: int) -> str:
    return f"Too many attempts, try again in {minutes} minute{'s' if minutes != 1 else ''}"


async def _check_login(db: AsyncSession, request: Request, username: str, password: str) -> User:
    """Shared by /login and /device: lockout, credentials, disabled. Returns the user."""
    ip = client_ip(request)
    minutes = lockout.locked_minutes(ip, username)
    if minutes:
        raise HTTPException(429, _lockout_message(minutes))
    user = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if user is None or not check_password(password, user.password_hash):
        lockout.record_failure(ip, username)
        raise HTTPException(401, "Invalid username or password")
    if user.disabled:
        raise HTTPException(403, "Account disabled")
    lockout.clear(ip, username)
    user.last_login_at = datetime.utcnow()
    return user


@router.get("/status")
async def auth_status(db: AsyncSession = Depends(get_db)):
    from backend.api.config_api import _get_version
    count = (await db.execute(select(func.count(User.id)))).scalar() or 0
    return {"needs_setup": count == 0, "enforce": get_settings().auth.enforce, "version": _get_version()}


@router.post("/setup")
async def setup(body: SetupRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    """Create the first admin. Only while the users table is empty."""
    count = (await db.execute(select(func.count(User.id)))).scalar() or 0
    if count:
        raise HTTPException(409, "Setup already done")
    username = body.username.strip()
    if not username:
        raise HTTPException(400, "Username is required")
    problem = new_password_problem(body.password)
    if problem:
        raise HTTPException(400, problem)
    user = User(
        id=str(uuid.uuid4()),
        username=username,
        password_hash=hash_password(body.password),
        subsonic_api_key=secrets.token_hex(16),
        role="admin",
        display_name=(body.display_name or "").strip() or None,
        last_login_at=datetime.utcnow(),
    )
    db.add(user)
    await db.commit()
    token, _row = await create_session(db, user, user_agent=request.headers.get("user-agent"), ip=client_ip(request))
    _set_cookie(response, token)
    return me_payload(user, "session")


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    user = await _check_login(db, request, body.username, body.password)
    await db.commit()
    token, _row = await create_session(db, user, user_agent=request.headers.get("user-agent"), ip=client_ip(request))
    _set_cookie(response, token)
    return me_payload(user, "session")


@router.post("/device")
async def device_login(body: DeviceLoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Username + password -> a device token for an app (phone, TV, watch)."""
    user = await _check_login(db, request, body.username, body.password)
    await db.commit()
    token, _row = await create_device_token(db, user, label=body.label, platform=body.platform)
    return {"token": token, "user": me_payload(user, "device")}


@router.post("/logout")
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        row = await lookup_session(db, token)
        if row is not None:
            await db.delete(row)
            await db.commit()
    _clear_cookie(response)
    return {"ok": True}


@router.get("/me")
async def me(request: Request):
    user = _caller(request)
    return me_payload(user, request.state.auth_method)


@router.put("/me")
async def update_me(body: MeUpdate, request: Request, db: AsyncSession = Depends(get_db)):
    caller = _caller(request)
    user = await db.get(User, caller.id)
    user.display_name = (body.display_name or "").strip() or None
    await db.commit()
    return me_payload(user, request.state.auth_method)


@router.post("/password")
async def change_password(body: PasswordChange, request: Request, db: AsyncSession = Depends(get_db)):
    """Change the caller's password. Keeps this session, ends the others; device tokens stay."""
    caller = _caller(request)
    user = await db.get(User, caller.id)
    if not check_password(body.current_password, user.password_hash):
        raise HTTPException(403, "Current password is incorrect")
    problem = new_password_problem(body.new_password)
    if problem:
        raise HTTPException(400, problem)
    user.password_hash = hash_password(body.new_password)
    await delete_user_sessions(db, user.id, keep_id=request.state.session_id)
    await db.commit()
    return {"ok": True}


@router.get("/devices")
async def list_devices(request: Request, db: AsyncSession = Depends(get_db)):
    """The caller's web sessions and device tokens (revoked tokens left out)."""
    user = _caller(request)
    now = datetime.utcnow()
    sessions = (await db.execute(
        select(AuthSession).where(AuthSession.user_id == user.id, AuthSession.expires_at > now)
    )).scalars().all()
    devices = (await db.execute(
        select(DeviceToken).where(DeviceToken.user_id == user.id, DeviceToken.revoked_at.is_(None))
    )).scalars().all()

    def iso(dt):
        return dt.isoformat() if dt else None

    out = [
        {"id": s.id, "kind": "session", "label": s.label, "platform": "web", "ip": s.ip,
         "created_at": iso(s.created_at), "last_seen_at": iso(s.last_seen_at),
         "current": s.id == request.state.session_id}
        for s in sessions
    ] + [
        {"id": d.id, "kind": "device", "label": d.label, "platform": d.platform, "ip": None,
         "created_at": iso(d.created_at), "last_seen_at": iso(d.last_seen_at),
         "current": d.id == request.state.device_token_id}
        for d in devices
    ]
    out.sort(key=lambda r: r["last_seen_at"] or r["created_at"] or "", reverse=True)
    return out


@router.delete("/devices/{item_id}")
async def revoke_device(item_id: str, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    """Revoke one of the caller's sessions (deleted) or device tokens (revoked_at set)."""
    user = _caller(request)
    session_row = (await db.execute(
        select(AuthSession).where(AuthSession.id == item_id, AuthSession.user_id == user.id)
    )).scalar_one_or_none()
    if session_row is not None:
        await db.execute(delete(AuthSession).where(AuthSession.id == item_id))
        await db.commit()
        if item_id == request.state.session_id:
            _clear_cookie(response)
        return {"ok": True}
    device = (await db.execute(
        select(DeviceToken).where(DeviceToken.id == item_id, DeviceToken.user_id == user.id)
    )).scalar_one_or_none()
    if device is None:
        raise HTTPException(404, "Not found")
    if device.revoked_at is None:
        device.revoked_at = datetime.utcnow()
        await db.commit()
    return {"ok": True}
