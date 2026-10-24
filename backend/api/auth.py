"""/api/auth — web login, first-run setup, the caller's own account and devices.

status, login, setup, device, logout, invite/{code} and join are public (see
backend/auth/policy.py); the rest
need real credentials — the grace-mode owner stand-in does not count as logged in.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import invites, lockout
from backend.auth.devices import create_device_token, list_user_items, revoke_user_item
from backend.auth.passwords import check_password, hash_password, must_change_password, new_password_problem
from backend.auth.permissions import permissions_for
from backend.auth.resolve import client_ip, is_authenticated
from backend.auth.sessions import SESSION_COOKIE, create_session, delete_user_sessions, lookup_session, session_lifetime
from backend.config import get_settings
from backend.database import get_db
from backend.models.invite import Invite
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


class DeviceTokenRequest(BaseModel):
    label: str | None = None
    platform: str | None = None


class JoinRequest(BaseModel):
    code: str
    username: str
    password: str
    display_name: str | None = None


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
async def auth_status(request: Request, db: AsyncSession = Depends(get_db)):
    from backend.api.config_api import _get_version
    from backend.services.discovery import advertise_url, server_name
    count = (await db.execute(select(func.count(User.id)))).scalar() or 0
    return {"needs_setup": count == 0, "enforce": get_settings().auth.enforce, "version": _get_version(),
            "server_name": server_name(), "url": advertise_url() or invites.base_url(request)}


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


def _check_invite_lockout(ip: str | None) -> None:
    minutes = lockout.locked_minutes(ip, invites.LOCKOUT_NAME)
    if minutes:
        raise HTTPException(429, _lockout_message(minutes))


async def _valid_invite_or_404(db: AsyncSession, ip: str | None, code: str) -> Invite:
    """The usable invite for code; a miss counts towards the per-IP lockout and 404s."""
    invite = await invites.find_valid(db, (code or "").strip())
    if invite is None:
        lockout.record_failure(ip, invites.LOCKOUT_NAME)
        raise HTTPException(404, invites.INVALID_MESSAGE)
    return invite


@router.get("/invite/{code}")
async def invite_info(code: str, request: Request, db: AsyncSession = Depends(get_db)):
    """What the /join page shows before the form. Same 404 for unknown/used/expired/revoked."""
    ip = client_ip(request)
    _check_invite_lockout(ip)
    invite = await _valid_invite_or_404(db, ip, code)
    inviter = await db.get(User, invite.created_by)
    invited_by = (inviter.display_name or inviter.username) if inviter else None
    return {"valid": True, "role": invite.role, "expires_at": invite.expires_at.isoformat(),
            "invited_by": invited_by}


@router.post("/join")
async def join(body: JoinRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    """Redeem an invite: create the account with the invite's role and log it in like /login."""
    ip = client_ip(request)
    _check_invite_lockout(ip)
    invite = await _valid_invite_or_404(db, ip, body.code)
    username = (body.username or "").strip()
    problem = invites.username_problem(username)
    if problem:
        raise HTTPException(400, problem)
    problem = new_password_problem(body.password)
    if problem:
        raise HTTPException(400, problem)
    if await invites.username_taken(db, username):
        raise HTTPException(409, "Username already taken")
    user = User(
        id=str(uuid.uuid4()),
        username=username,
        password_hash=hash_password(body.password),
        subsonic_api_key=secrets.token_hex(16),
        role=invite.role,
        display_name=(body.display_name or "").strip() or None,
        last_login_at=datetime.utcnow(),
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:  # lost a race on the username's unique index
        await db.rollback()
        raise HTTPException(409, "Username already taken")
    if not await invites.consume(db, invite.id, user.id):  # someone else redeemed it first
        await db.rollback()
        raise HTTPException(404, invites.INVALID_MESSAGE)
    await db.commit()
    lockout.clear(ip, invites.LOCKOUT_NAME)
    token, _row = await create_session(db, user, user_agent=request.headers.get("user-agent"), ip=ip)
    _set_cookie(response, token)
    return me_payload(user, "session")


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
    return await list_user_items(db, user.id, current_session_id=request.state.session_id,
                                 current_device_id=request.state.device_token_id)


@router.post("/devices")
async def issue_device_token(body: DeviceTokenRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """A new device token for the signed-in caller, no password needed. The phone app uses
    it to move its own legacy API-key login onto a token, and to hand the paired watch a
    token of its own instead of the phone's credentials."""
    user = _caller(request)
    token, row = await create_device_token(db, user, label=body.label, platform=body.platform)
    return {
        "token": token,
        "device": {"id": row.id, "label": row.label, "platform": row.platform},
        "user": me_payload(user, request.state.auth_method),
    }


@router.delete("/devices/{item_id}")
async def revoke_device(item_id: str, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    """Revoke one of the caller's sessions (deleted) or device tokens (revoked_at set)."""
    user = _caller(request)
    kind = await revoke_user_item(db, user.id, item_id)
    if kind is None:
        raise HTTPException(404, "Not found")
    if kind == "session" and item_id == request.state.session_id:
        _clear_cookie(response)
    return {"ok": True}
