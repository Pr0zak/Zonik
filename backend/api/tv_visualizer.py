"""TV visualizer API: shared settings and per-effect stats for the Google TV app.

The server holds the one copy of the visualizer's settings. The web UI edits it, and each TV
pulls it at startup and every few minutes and pushes back any change made on the TV itself.
TVs also report how each effect ran (time on screen, frame rate, kicks) for the web UI's stats.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import async_session, get_db
from backend.models.tv_visualizer import TvEffectStat, TvVisualizerConfig

log = logging.getLogger(__name__)

router = APIRouter()

# Set (and replaced) whenever the config is saved, to wake TVs waiting in a long poll. In memory
# is enough: the server runs as one uvicorn process.
_changed = asyncio.Event()

# Longest a long poll is held. Short enough that a restart is not held up for long by a TV
# that is waiting, long enough that an idle TV costs a request every half minute or so.
MAX_WAIT_SEC = 25


def _notify_changed() -> None:
    global _changed
    old, _changed = _changed, asyncio.Event()
    old.set()

# The app's own defaults, so a key missing from the stored config means the same thing on the
# server as on the TV. Keep in step with SettingsRepository's TV_AMBIENT_* defaults.
DEFAULTS: dict = {
    "enabled": True,
    "delay_sec": 10,
    "beat_reactive": True,
    "effects_off": [],
    "rotate_sec": 45,
    "info": "FADE",
    "transition": -1,
    "transition_ms": 1600,
    "colors": "ALBUM",
    "trails": False,
}

TRANSITIONS = [
    "Block dissolve", "Iris", "Clock sweep", "Ragged wipe", "Checkerboard",
    "Diamond", "Spiral", "Venetian blinds", "Split doors", "Radiating dissolve",
    "Melt", "Hexagons", "Shatter", "Star iris", "Wavy iris",
    "Pinwheel", "Rings", "Interlace", "Block cascade", "Burn",
]

# The choices the TV's settings screen cycles through, with its labels, for the web page.
OPTIONS: dict = {
    "delay_sec": [[0, "Only when asked"], [10, "10 s idle"], [30, "30 s idle"],
                  [60, "1 min idle"], [90, "90 s idle"], [300, "5 min idle"]],
    "rotate_sec": [[0, "Each track"], [30, "Every 30 s"], [45, "Every 45 s"],
                   [60, "Every minute"], [120, "Every 2 min"], [300, "Every 5 min"]],
    "info": [["FADE", "Centre, then fade"], ["ALWAYS", "Centre, always"],
             ["CORNER_FADE", "Corner, then fade"], ["CORNER_ALWAYS", "Corner, always"],
             ["NEVER", "Never"]],
    "transition": [[-1, "Mixed"]] + [[i, name] for i, name in enumerate(TRANSITIONS)],
    "transition_ms": [[600, "Fast"], [1600, "Normal"], [3000, "Slow"], [5000, "Very slow"]],
    "colors": [["ALBUM", "Album art"], ["RANDOM", "Random"], ["CYCLE", "Cycle"],
               ["MIXED", "Mixed"]],
}


def _clean(raw: dict) -> dict:
    """Keep only known keys with values of the right type; drop anything else.

    Lenient on purpose: an older or newer app may send a key this server does not know, and
    that must not fail the whole update.
    """
    out: dict = {}
    for key, default in DEFAULTS.items():
        if key not in raw:
            continue
        value = raw[key]
        if isinstance(default, bool):
            if isinstance(value, bool):
                out[key] = value
        elif isinstance(default, int):
            if isinstance(value, int) and not isinstance(value, bool):
                allowed = [o[0] for o in OPTIONS.get(key, [])]
                if not allowed or value in allowed:
                    out[key] = value
        elif isinstance(default, str):
            allowed = [o[0] for o in OPTIONS.get(key, [])]
            if isinstance(value, str) and (not allowed or value in allowed):
                out[key] = value
        elif isinstance(default, list):
            if isinstance(value, list) and all(isinstance(v, str) for v in value):
                out[key] = sorted(set(value))
    return out


def _iso(dt: datetime | None) -> str | None:
    return dt.replace(tzinfo=timezone.utc).isoformat() if dt else None


async def _load(db: AsyncSession) -> TvVisualizerConfig | None:
    return (await db.execute(select(TvVisualizerConfig).where(TvVisualizerConfig.id == 1))).scalar_one_or_none()


def _payload(row: TvVisualizerConfig | None) -> dict:
    stored = json.loads(row.config) if row else {}
    return {
        "config": {**DEFAULTS, **_clean(stored)},
        "defaults": DEFAULTS,
        "options": OPTIONS,
        "updated_at": _iso(row.updated_at) if row else None,
        "updated_by": row.updated_by if row else None,
    }


@router.get("/config")
async def get_config(wait: int = 0, since: str | None = None):
    """The current config. With `wait` and `since` (the `updated_at` the caller already has),
    a long poll: if nothing has changed, hold the request until a save or `wait` seconds
    (at most MAX_WAIT_SEC), so a TV applies a change from the web within a second instead of
    on its next poll.
    """
    async with async_session() as db:
        payload = _payload(await _load(db))
    if wait <= 0 or since is None or payload["updated_at"] != since:
        return payload
    event = _changed
    try:
        await asyncio.wait_for(event.wait(), timeout=min(wait, MAX_WAIT_SEC))
    except asyncio.TimeoutError:
        return payload
    async with async_session() as db:
        return _payload(await _load(db))


class ConfigUpdate(BaseModel):
    config: dict
    updated_by: str | None = None
    # "Replace" resets every key not given to its default; otherwise the keys given are
    # merged into what is stored.
    replace: bool = False


@router.put("/config")
async def put_config(body: ConfigUpdate, db: AsyncSession = Depends(get_db)):
    row = await _load(db)
    stored = {} if (row is None or body.replace) else _clean(json.loads(row.config))
    merged = {**stored, **_clean(body.config)}
    if row is None:
        row = TvVisualizerConfig(id=1)
        db.add(row)
    row.config = json.dumps(merged, sort_keys=True)
    row.updated_at = datetime.utcnow()
    row.updated_by = (body.updated_by or "web")[:80]
    await db.commit()
    _notify_changed()
    log.info("TV visualizer config updated by %s: %s", row.updated_by, merged)
    return _payload(row)


class EffectReport(BaseModel):
    effect: str = Field(max_length=40)
    seconds: float = Field(ge=0, le=86_400)
    frames: int = Field(ge=0)
    kicks: int = Field(ge=0)
    shows: int = Field(ge=0)


class StatsReport(BaseModel):
    device_id: str = Field(max_length=80)
    device_name: str | None = Field(default=None, max_length=120)
    effects: list[EffectReport] = Field(max_length=200)


@router.post("/stats")
async def post_stats(body: StatsReport, db: AsyncSession = Depends(get_db)):
    """Add a TV's per-effect totals since its last report into today's buckets."""
    now = datetime.utcnow()
    day = now.strftime("%Y-%m-%d")
    for rep in body.effects:
        if rep.seconds <= 0 and rep.shows == 0:
            continue
        row = (await db.execute(select(TvEffectStat).where(
            TvEffectStat.device_id == body.device_id,
            TvEffectStat.effect == rep.effect,
            TvEffectStat.day == day,
        ))).scalar_one_or_none()
        if row is None:
            row = TvEffectStat(device_id=body.device_id, effect=rep.effect, day=day,
                               seconds_shown=0.0, frames=0, kicks=0, times_shown=0)
            db.add(row)
        row.device_name = body.device_name
        row.seconds_shown += rep.seconds
        row.frames += rep.frames
        row.kicks += rep.kicks
        row.times_shown += rep.shows
        row.last_shown_at = now
    await db.commit()
    return {"ok": True}


@router.get("/stats")
async def get_stats(days: int = 30, db: AsyncSession = Depends(get_db)):
    """Per-effect totals over the last `days` days (0 = all time), across every TV."""
    if days < 0 or days > 3650:
        raise HTTPException(400, "days must be between 0 and 3650")
    q = select(
        TvEffectStat.effect,
        func.sum(TvEffectStat.seconds_shown),
        func.sum(TvEffectStat.frames),
        func.sum(TvEffectStat.kicks),
        func.sum(TvEffectStat.times_shown),
        func.max(TvEffectStat.last_shown_at),
    ).group_by(TvEffectStat.effect)
    devices_q = select(TvEffectStat.device_id, TvEffectStat.device_name,
                       func.max(TvEffectStat.last_shown_at)).group_by(TvEffectStat.device_id)
    if days:
        since = (datetime.utcnow() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        q = q.where(TvEffectStat.day >= since)
        devices_q = devices_q.where(TvEffectStat.day >= since)

    effects = {}
    total_seconds = 0.0
    for effect, seconds, frames, kicks, shows, last in (await db.execute(q)).all():
        seconds = seconds or 0.0
        total_seconds += seconds
        effects[effect] = {
            "seconds": round(seconds, 1),
            "shows": shows or 0,
            "fps": round(frames / seconds, 1) if seconds > 0 else None,
            "kicks_per_min": round(kicks * 60 / seconds, 1) if seconds > 0 else None,
            "last_shown_at": _iso(last),
        }
    devices = [{"id": d, "name": n, "last_seen_at": _iso(last)}
               for d, n, last in (await db.execute(devices_q)).all()]
    return {"days": days, "total_seconds": round(total_seconds, 1),
            "effects": effects, "devices": devices}
