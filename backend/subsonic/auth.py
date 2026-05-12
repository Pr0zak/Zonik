"""Subsonic authentication - supports token and password auth."""
from __future__ import annotations

import hashlib

import bcrypt
from fastapi import Request, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import async_session
from backend.models.user import User
from backend.subsonic.activity import record_activity


def _client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


async def authenticate_subsonic(request: Request) -> User:
    """Authenticate a Subsonic API request. Returns the User or raises."""
    # Get params from query string or form data
    params = dict(request.query_params)
    if request.method == "POST":
        try:
            form = await request.form()
            params.update(form)
        except Exception:
            pass

    api_key = params.get("apiKey")
    username = params.get("u")
    password = params.get("p")
    token = params.get("t")
    salt = params.get("s")
    client_name = params.get("c")

    # API key auth (OpenSubsonic apiKey param — no username needed)
    if api_key:
        async with async_session() as db:
            result = await db.execute(
                select(User).where(User.subsonic_api_key == api_key)
            )
            user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(401, "Invalid API key")
        record_activity(
            user.username,
            client_name,
            request.headers.get("user-agent"),
            _client_ip(request),
        )
        return user

    if not username:
        raise HTTPException(400, "Missing username")

    async with async_session() as db:
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(401, "Unknown user")

    if token and salt:
        # Token auth: token = md5(password + salt)
        # Verify against stored subsonic_api_key (plaintext key for token auth)
        if not user.subsonic_api_key:
            raise HTTPException(401, "No API key configured for this user. Set one in Settings > Users.")
        expected = hashlib.md5((user.subsonic_api_key + salt).encode()).hexdigest()
        if token.lower() != expected.lower():
            raise HTTPException(401, "Invalid token")
    elif password:
        # Password auth: either hex-encoded or plain
        plain_password = password
        if plain_password.startswith("enc:"):
            # Hex-encoded password
            plain_password = bytes.fromhex(plain_password[4:]).decode("utf-8")

        if not bcrypt.checkpw(plain_password.encode(), user.password_hash.encode()):
            raise HTTPException(401, "Invalid password")
    else:
        raise HTTPException(400, "Missing authentication")

    record_activity(
        user.username,
        client_name,
        request.headers.get("user-agent"),
        _client_ip(request),
    )
    return user


def _is_bcrypt(hash_str: str) -> bool:
    return hash_str.startswith("$2")
