"""Device pairing API — TV/new devices connect without typing credentials.

Legacy flow (TV app <= v1.52, unchanged): POST /api/pair -> {code, expires}; the TV polls
GET /api/pair/{code} for {status: pending|expired|ready, url, username, api_key}.

Pairing v2 (P4): a logged-in user opens /pair?code=…, sees GET /api/pair/{code}/info and
approves with POST /api/pair/{code}/approve, which mints a device token for that user. The TV's
"ready" poll then also carries device_token and display_name (additive).
"""
from __future__ import annotations

import io
import secrets
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import lockout
from backend.auth.devices import create_device_token, normalize_platform
from backend.auth.invites import base_url
from backend.auth.resolve import client_ip, is_authenticated
from backend.database import get_db
from backend.models.user import User

router = APIRouter()

# In-memory store: code -> {status, config, expires_at, label, platform, created_at, ip[, approving]}
_pairs: dict[str, dict] = {}
EXPIRY_SECONDS = 300  # 5 minutes
INVALID_MESSAGE = "Code expired or invalid"
# Failed /info lookups share the login lockout, per IP, under a name no username can have.
LOCKOUT_NAME = "#pair"


def _cleanup():
    """Remove expired codes."""
    now = time.time()
    expired = [k for k, v in _pairs.items() if v["expires_at"] < now]
    for k in expired:
        del _pairs[k]


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_code() -> str:
    return f"{secrets.randbelow(900000) + 100000}"


def _clean(value, limit: int) -> str | None:
    return (value.strip()[:limit] or None) if isinstance(value, str) else None


def _public_url(request: Request) -> str:
    from backend.services.discovery import advertise_url
    return advertise_url() or base_url(request)


@router.post("")
async def create_pair(request: Request):
    """Generate a 6-digit pairing code. Optional JSON body {label?, platform?}; a missing or
    unparseable body is fine (the legacy TV app sends none)."""
    body: dict = {}
    try:
        if await request.body():
            parsed = await request.json()
            if isinstance(parsed, dict):
                body = parsed
    except Exception:
        body = {}
    _cleanup()
    code = _new_code()
    # Avoid collisions
    while code in _pairs:
        code = _new_code()
    now = time.time()
    expires_at = now + EXPIRY_SECONDS
    _pairs[code] = {
        "status": "pending", "config": None, "expires_at": expires_at,
        "label": _clean(body.get("label"), 80), "platform": _clean(body.get("platform"), 20),
        "created_at": now, "ip": client_ip(request),
    }
    return {"code": code, "expires": _iso(expires_at)}


@router.get("/{code}")
async def get_pair(code: str):
    """Poll pairing status. Called by the TV/device."""
    _cleanup()
    pair = _pairs.get(code)
    if not pair:
        return {"status": "expired"}
    if pair["config"]:
        # Consume on read — one-time retrieval
        config = pair["config"]
        del _pairs[code]
        return {"status": "ready", **config}
    return {"status": "pending"}


@router.get("/{code}/info")
async def pair_info(code: str, request: Request):
    """What the approver sees. Unknown/expired -> {status: "expired"} (200); misses count
    towards a per-IP lockout."""
    ip = client_ip(request)
    minutes = lockout.locked_minutes(ip, LOCKOUT_NAME)
    if minutes:
        raise HTTPException(429, f"Too many attempts, try again in {minutes} minute{'s' if minutes != 1 else ''}")
    _cleanup()
    pair = _pairs.get(code)
    if not pair:
        lockout.record_failure(ip, LOCKOUT_NAME)
        return {"status": "expired"}
    if pair["config"] or pair.get("approving"):  # already approved: no longer usable
        return {"status": "expired"}
    return {
        "status": "pending",
        "label": pair["label"], "platform": pair["platform"],
        "created_at": _iso(pair["created_at"]), "expires": _iso(pair["expires_at"]),
    }


class PairApprove(BaseModel):
    label: str | None = None


@router.post("/{code}/approve")
async def approve_pair(code: str, request: Request, body: PairApprove | None = None,
                       db: AsyncSession = Depends(get_db)):
    """Pair the waiting device as the caller: mint a device token and hand the TV its config."""
    if not is_authenticated(request):
        raise HTTPException(401, "Not authenticated")
    _cleanup()
    pair = _pairs.get(code)
    if not pair:
        raise HTTPException(404, INVALID_MESSAGE)
    if pair["config"] or pair.get("approving"):
        raise HTTPException(409, "Code already used")
    # Claim the code before any await so a concurrent approve gets 409, not a second token.
    pair["approving"] = True
    try:
        user = await db.get(User, request.state.user.id)
        if user is None:
            raise HTTPException(401, "Not authenticated")
        if not user.subsonic_api_key:
            user.subsonic_api_key = secrets.token_hex(16)
            await db.commit()
        label = _clean(body.label if body else None, 80) or pair["label"] or "TV"
        platform = normalize_platform(pair["platform"] or "tv")
        token, row = await create_device_token(db, user, label=label, platform=platform)
    except BaseException:
        pair["approving"] = False
        raise
    pair["config"] = {
        "url": _public_url(request),
        "username": user.username,
        "api_key": user.subsonic_api_key,
        "device_token": token,
        "display_name": user.display_name or user.username,
    }
    pair["status"] = "ready"
    return {"status": "ok", "device": {"id": row.id, "label": row.label, "platform": row.platform}}


@router.get("/{code}/qr.svg")
async def pair_qr(code: str, request: Request):
    """SVG QR of <advertise url>/pair?code=<code> for the TV screen; 404 for unknown/expired."""
    import segno
    _cleanup()
    if code not in _pairs:
        raise HTTPException(404, INVALID_MESSAGE)
    buf = io.BytesIO()
    segno.make(f"{_public_url(request)}/pair?code={code}", error="m").save(buf, kind="svg", scale=6, border=2)
    return Response(buf.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


class PairSubmit(BaseModel):
    url: str
    username: str
    api_key: str


@router.post("/{code}/submit")
async def submit_pair(code: str, body: PairSubmit):
    """Submit server config for a pairing code. Called from the web UI."""
    _cleanup()
    pair = _pairs.get(code)
    if not pair:
        raise HTTPException(404, "Code expired or invalid")
    pair["config"] = {"url": body.url, "username": body.username, "api_key": body.api_key}
    pair["status"] = "ready"
    return {"status": "ok"}
