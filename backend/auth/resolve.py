"""Who is calling, and the gates that use it.

Resolution order (every /api request, /api/ws and /rest): session cookie `zonik_session`
-> `Authorization: Bearer <device token>` -> `apiKey=<device token or legacy subsonic_api_key>`
-> Subsonic `u` + `t`/`s` (or `p`). Disabled users count as no credentials.

Grace mode ([auth] enforce = false, the default) keeps every request that worked before the
auth work working: a request with no or bad credentials runs as the legacy owner (the first
admin by created_at) with auth_method "anonymous", and is logged. Enforce mode answers it 401
(Subsonic error 40 on /rest). Either way an authenticated role=user caller gets 403 on
admin-only routes.
"""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import HTTPConnection

from backend.auth.devices import DEVICE_PREFIX, lookup_device_token
from backend.auth.passwords import check_password
from backend.auth.permissions import has_perm
from backend.auth.policy import PUBLIC, perm_for
from backend.auth.sessions import SESSION_COOKIE, lookup_session
from backend.config import get_settings
from backend.database import async_session
from backend.models.user import User

log = logging.getLogger(__name__)

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Real credentials; "anonymous" (grace owner) and "internal" (worker on loopback) are not.
AUTHENTICATED_METHODS = frozenset({"session", "device", "subsonic"})

# The arq worker calls these on 127.0.0.1 without credentials (download delegation and the
# backend-ready probe). They stay reachable from loopback when enforce is on.
_INTERNAL_PATHS = frozenset({"/api/download/internal-run", "/api/download/status"})
_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})

# Subsonic endpoints a client calls before it has credentials.
_SUBSONIC_OPEN = frozenset({"ping", "getLicense", "getOpenSubsonicExtensions"})

_password_ok_cache: dict[str, bool] = {}

_GRACE_LOG_INTERVAL = 600.0
_grace_logged: dict[str, float] = {}
_db_error_logged = 0.0


@dataclass
class Caller:
    user: User
    method: str  # session | device | subsonic
    session_id: str | None = None
    device_token_id: str | None = None


class SubsonicAuthRequired(Exception):
    """Raised by the /rest gate in enforce mode; main.py renders Subsonic error 40."""


def client_ip(conn: HTTPConnection) -> str | None:
    fwd = conn.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return conn.client.host if conn.client else None


def _usable(user: User | None) -> User | None:
    return user if user is not None and not user.disabled else None


async def _user_by_id(db: AsyncSession, user_id: str) -> User | None:
    return _usable((await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none())


async def lookup_api_key(db: AsyncSession, key: str) -> tuple[User | None, str | None]:
    """(user, device_token_id) for an apiKey: a device token, else a legacy subsonic_api_key."""
    if not key:
        return None, None
    if key.startswith(DEVICE_PREFIX):
        row = await lookup_device_token(db, key)
        if row is not None:
            return await _user_by_id(db, row.user_id), row.id
    user = (await db.execute(select(User).where(User.subsonic_api_key == key))).scalar_one_or_none()
    return _usable(user), None


def _verify_subsonic(user: User, token: str | None, salt: str | None, password: str | None) -> bool:
    if token and salt:
        # token = md5(secret + salt); the secret is the user's subsonic_api_key, not the password.
        if not user.subsonic_api_key:
            return False
        expected = hashlib.md5((user.subsonic_api_key + salt).encode()).hexdigest()
        return token.lower() == expected.lower()
    if password:
        plain = password
        if plain.startswith("enc:"):
            try:
                plain = bytes.fromhex(plain[4:]).decode("utf-8")
            except ValueError:
                return False
        # Clients using p= send it on every call; bcrypt each time would cost ~0.2 s a request.
        key = hashlib.sha256(f"{user.password_hash}\0{plain}".encode()).hexdigest()
        ok = _password_ok_cache.get(key)
        if ok is None:
            ok = check_password(plain, user.password_hash)
            if len(_password_ok_cache) > 500:
                _password_ok_cache.clear()
            _password_ok_cache[key] = ok
        return ok
    return False


async def _params(conn: HTTPConnection, include_form: bool) -> dict:
    params = dict(conn.query_params)
    if include_form and isinstance(conn, Request) and conn.method == "POST":
        ctype = conn.headers.get("content-type", "")
        if "form" in ctype:
            try:
                form = await conn.form()
                for k, v in form.items():
                    if isinstance(v, str):
                        params.setdefault(k, v)
            except Exception:
                pass
    return params


async def resolve_caller(conn: HTTPConnection, *, include_form: bool = False) -> Caller | None:
    """The authenticated caller, or None when there are no usable credentials."""
    async with async_session() as db:
        cookie = conn.cookies.get(SESSION_COOKIE)
        if cookie:
            row = await lookup_session(db, cookie)
            if row is not None:
                user = await _user_by_id(db, row.user_id)
                if user is not None:
                    return Caller(user, "session", session_id=row.id)

        auth = conn.headers.get("authorization") or ""
        if auth[:7].lower() == "bearer ":
            row = await lookup_device_token(db, auth[7:].strip())
            if row is not None:
                user = await _user_by_id(db, row.user_id)
                if user is not None:
                    return Caller(user, "device", device_token_id=row.id)

        params = await _params(conn, include_form)
        api_key = params.get("apiKey")
        if api_key:
            user, device_id = await lookup_api_key(db, api_key)
            if user is not None:
                return Caller(user, "device" if device_id else "subsonic", device_token_id=device_id)

        username = params.get("u")
        if username and (params.get("t") and params.get("s") or params.get("p")):
            user = _usable((await db.execute(select(User).where(User.username == username))).scalar_one_or_none())
            if user is not None and _verify_subsonic(user, params.get("t"), params.get("s"), params.get("p")):
                return Caller(user, "subsonic")
    return None


async def get_owner() -> User | None:
    """The legacy owner grace-mode requests run as: the first enabled admin by created_at."""
    async with async_session() as db:
        return (await db.execute(
            select(User)
            .where(User.role == "admin", User.disabled.is_(False))
            .order_by(User.created_at)
            .limit(1)
        )).scalar_one_or_none()


def _is_internal(conn: HTTPConnection) -> bool:
    return (
        conn.scope.get("path") in _INTERNAL_PATHS
        and (conn.client.host if conn.client else None) in _LOOPBACK
        and not conn.headers.get("x-forwarded-for")
    )


def _log_grace(conn: HTTPConnection, method: str) -> None:
    route = conn.scope.get("route")
    key = getattr(route, "path", None) or conn.scope.get("path", "")
    now = time.monotonic()
    if now - _grace_logged.get(key, -_GRACE_LOG_INTERVAL - 1) < _GRACE_LOG_INTERVAL:
        return
    if len(_grace_logged) > 2000:
        _grace_logged.clear()
    _grace_logged[key] = now
    log.warning(f"auth grace: unauthenticated {method} {conn.scope.get('path', '')} from {client_ip(conn)}")


def _log_db_error(e: Exception) -> None:
    global _db_error_logged
    now = time.monotonic()
    if now - _db_error_logged > _GRACE_LOG_INTERVAL:
        _db_error_logged = now
        log.error(f"auth: could not resolve the caller ({e!r}) — has `alembic upgrade head` run? "
                  f"Grace mode lets the request through anonymously.")


def _set_state(conn: HTTPConnection, user: User | None, method: str | None, caller: Caller | None = None) -> None:
    conn.state.user = user
    conn.state.auth_method = method
    conn.state.session_id = caller.session_id if caller else None
    conn.state.device_token_id = caller.device_token_id if caller else None


def check_origin(request: Request) -> None:
    """CSRF guard for cookie-authenticated writes: an Origin header, when present, must
    name this host. SameSite=Lax on the cookie covers requests without one."""
    origin = request.headers.get("origin")
    if not origin:
        return
    origin_host = urlsplit(origin).netloc.lower()
    hosts = {h.strip().lower() for h in (request.headers.get("host"), request.headers.get("x-forwarded-host")) if h}
    if not origin_host or origin_host not in hosts:
        raise HTTPException(403, "Cross-origin request blocked")


async def _resolve_or_grace(conn: HTTPConnection, method: str, *, include_form: bool = False,
                            grace_owner: bool = True) -> bool:
    """Resolve the caller into conn.state. False when there are no usable credentials and
    enforce is on (the caller decides how to refuse). grace_owner=False leaves user None
    for grace-mode anonymous requests and skips the grace log (/rest)."""
    enforce = get_settings().auth.enforce
    try:
        caller = await resolve_caller(conn, include_form=include_form)
        if caller is not None:
            _set_state(conn, caller.user, caller.method, caller)
            return True
        if _is_internal(conn):
            _set_state(conn, await get_owner(), "internal")
            return True
        if enforce:
            _set_state(conn, None, None)
            return False
        owner = await get_owner() if grace_owner else None
    except Exception as e:
        # Typically the auth columns before `alembic upgrade head` has run.
        if enforce:
            raise
        _log_db_error(e)
        _set_state(conn, None, "anonymous")
        return True
    _set_state(conn, owner, "anonymous")
    if grace_owner:
        _log_grace(conn, method)
    return True


async def api_gate(request: Request) -> None:
    """Dependency on every /api router: authenticate, CSRF-check, apply the path policy."""
    method = request.method
    perm = perm_for(method, request.scope.get("path", ""))
    if perm == PUBLIC:
        return
    if not await _resolve_or_grace(request, method):
        raise HTTPException(401, "Not authenticated")
    if request.state.auth_method == "session" and method not in SAFE_METHODS:
        check_origin(request)
    user = request.state.user
    if user is not None and not has_perm(user, perm):
        raise HTTPException(403, "Admins only")


async def subsonic_gate(request: Request) -> None:
    """Dependency on the /rest router. Grace mode: unauthenticated requests pass exactly as
    before. Enforce mode: Subsonic error 40, except the pre-login endpoints."""
    # Per-endpoint behaviour on /rest is unchanged in P1: no owner stand-in for anonymous calls.
    if await _resolve_or_grace(request, request.method, include_form=True, grace_owner=False):
        return
    endpoint = request.scope.get("path", "").rstrip("/").rsplit("/", 1)[-1].removesuffix(".view")
    if endpoint in _SUBSONIC_OPEN:
        return
    raise SubsonicAuthRequired()


async def websocket_allowed(websocket) -> bool:
    """Resolve the caller of /api/ws into websocket.state; False = refuse (enforce mode)."""
    return await _resolve_or_grace(websocket, "WS")


def is_authenticated(conn: HTTPConnection) -> bool:
    return getattr(conn.state, "auth_method", None) in AUTHENTICATED_METHODS and getattr(conn.state, "user", None) is not None


def reset_grace_log() -> None:
    """Tests only."""
    _grace_logged.clear()
