"""Device pairing API — TV/new devices connect without typing credentials."""
from __future__ import annotations

import random
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

# In-memory store: code -> {status, config, expires_at}
_pairs: dict[str, dict] = {}
EXPIRY_SECONDS = 300  # 5 minutes


def _cleanup():
    """Remove expired codes."""
    now = time.time()
    expired = [k for k, v in _pairs.items() if v["expires_at"] < now]
    for k in expired:
        del _pairs[k]


@router.post("")
async def create_pair():
    """Generate a 6-digit pairing code."""
    _cleanup()
    code = f"{random.randint(100000, 999999)}"
    # Avoid collisions
    while code in _pairs:
        code = f"{random.randint(100000, 999999)}"
    expires_at = time.time() + EXPIRY_SECONDS
    _pairs[code] = {"status": "pending", "config": None, "expires_at": expires_at}
    from datetime import datetime, timezone
    return {
        "code": code,
        "expires": datetime.fromtimestamp(expires_at, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


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
