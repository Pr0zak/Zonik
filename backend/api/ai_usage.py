"""Claude API usage & cost dashboard endpoints.

Every call routed through `call_claude` writes one row to `ai_usage` (see
backend/services/ai/client.py). That covers all ten AI features; the Settings
page's connectivity probe (`POST /api/config/test/claude`) talks to Anthropic
directly and is deliberately not counted. This router turns those rows into a single
aggregate payload for the frontend's AI usage page — summary totals, a gap-filled
timeseries, per-feature and per-model breakdowns, and the most recent calls.

Costs are *estimates* derived from stored token counts via
backend/services/ai/pricing.py, not billed amounts: raw tokens are persisted so a
price change only requires re-running the maths, never a backfill.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.ai_usage import AIUsage
from backend.services.ai import pricing

router = APIRouter()

_RECENT_LIMIT = 25
_COST_DP = 6  # never 2 — a single Haiku call costs a fraction of a cent


def _iso(value) -> str | None:
    """SQLite min()/max() over a DATETIME may hand back a str; normalise to ISO."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _cost(value) -> float:
    return round(float(value or 0.0), _COST_DP)


def _errors_expr():
    return func.sum(case((AIUsage.success.is_(False), 1), else_=0))


def _empty_summary() -> dict:
    return {
        "requests": 0,
        "errors": 0,
        "error_rate": 0.0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "avg_latency_ms": 0.0,
        "first_call": None,
        "last_call": None,
    }


async def _summary(db: AsyncSession, cutoff: datetime | None) -> dict:
    """Window totals (cutoff=None → all time). Aggregated SQL-side."""
    stmt = select(
        func.count(AIUsage.id),
        _errors_expr(),
        func.sum(AIUsage.input_tokens),
        func.sum(AIUsage.output_tokens),
        func.sum(AIUsage.cache_read_tokens),
        func.sum(AIUsage.cache_write_tokens),
        func.sum(AIUsage.cost_usd),
        func.avg(AIUsage.latency_ms),
        func.min(AIUsage.created_at),
        func.max(AIUsage.created_at),
    )
    if cutoff is not None:
        stmt = stmt.where(AIUsage.created_at >= cutoff)

    row = (await db.execute(stmt)).one_or_none()
    if row is None:
        return _empty_summary()

    requests = int(row[0] or 0)
    if requests == 0:
        return _empty_summary()

    errors = int(row[1] or 0)
    input_tokens = int(row[2] or 0)
    output_tokens = int(row[3] or 0)
    cache_read = int(row[4] or 0)
    cache_write = int(row[5] or 0)

    return {
        "requests": requests,
        "errors": errors,
        "error_rate": round(errors / requests, 4),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "total_tokens": input_tokens + output_tokens + cache_read + cache_write,
        "cost_usd": _cost(row[6]),
        "avg_latency_ms": round(float(row[7] or 0.0), 1),
        "first_call": _iso(row[8]),
        "last_call": _iso(row[9]),
    }


def _bucket_keys(start: datetime, end: datetime, bucket: str) -> list[str]:
    """Every bucket key in [start, end], ascending — the gap-fill skeleton."""
    keys: list[str] = []
    if bucket == "hour":
        cur = start.replace(minute=0, second=0, microsecond=0)
        step = timedelta(hours=1)
        fmt = "%Y-%m-%dT%H:00"
    else:
        cur = start.replace(hour=0, minute=0, second=0, microsecond=0)
        step = timedelta(days=1)
        fmt = "%Y-%m-%d"
    while cur <= end:
        keys.append(cur.strftime(fmt))
        cur += step
    return keys


@router.get("/dashboard")
async def ai_usage_dashboard(
    days: int = Query(30, description="Window size in days (clamped 1..365)"),
    bucket: str = Query("day", description="'day' or 'hour' ('hour' only honoured when days <= 2)"),
    db: AsyncSession = Depends(get_db),
):
    """One round-trip payload for the AI usage & cost dashboard."""
    days = max(1, min(365, int(days)))
    bucket = bucket if bucket in ("day", "hour") else "day"
    if bucket == "hour" and days > 2:
        bucket = "day"

    now = datetime.utcnow()  # created_at is naive UTC — keep the same basis
    if bucket == "hour":
        hours = days * 24
        start = (now - timedelta(hours=hours - 1)).replace(minute=0, second=0, microsecond=0)
        period_col = func.strftime("%Y-%m-%dT%H:00", AIUsage.created_at)
    else:
        start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
        period_col = func.strftime("%Y-%m-%d", AIUsage.created_at)

    summary = await _summary(db, start)
    all_time = await _summary(db, None)

    # --- Timeseries (grouped SQL-side, gap-filled in Python) ---
    ts_rows = (await db.execute(
        select(
            period_col.label("period"),
            func.count(AIUsage.id),
            _errors_expr(),
            func.sum(AIUsage.input_tokens),
            func.sum(AIUsage.output_tokens),
            func.sum(AIUsage.cache_read_tokens),
            func.sum(AIUsage.cache_write_tokens),
            func.sum(AIUsage.cost_usd),
        )
        .where(AIUsage.created_at >= start)
        .group_by(period_col)
        .order_by(period_col)
    )).all()

    by_period = {
        r[0]: {
            "period": r[0],
            "requests": int(r[1] or 0),
            "errors": int(r[2] or 0),
            "input_tokens": int(r[3] or 0),
            "output_tokens": int(r[4] or 0),
            "cache_read_tokens": int(r[5] or 0),
            "cache_write_tokens": int(r[6] or 0),
            "cost_usd": _cost(r[7]),
        }
        for r in ts_rows
        if r[0] is not None
    }

    timeseries = [
        by_period.get(key, {
            "period": key,
            "requests": 0,
            "errors": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "cost_usd": 0.0,
        })
        for key in _bucket_keys(start, now, bucket)
    ]

    # --- Per-feature breakdown ---
    feature_rows = (await db.execute(
        select(
            AIUsage.feature,
            func.count(AIUsage.id),
            _errors_expr(),
            func.sum(AIUsage.input_tokens),
            func.sum(AIUsage.output_tokens),
            func.sum(AIUsage.cost_usd),
            func.avg(AIUsage.latency_ms),
        )
        .where(AIUsage.created_at >= start)
        .group_by(AIUsage.feature)
        .order_by(func.sum(AIUsage.cost_usd).desc())
    )).all()

    by_feature = [
        {
            "feature": r[0] or "unknown",
            "requests": int(r[1] or 0),
            "errors": int(r[2] or 0),
            "input_tokens": int(r[3] or 0),
            "output_tokens": int(r[4] or 0),
            "cost_usd": _cost(r[5]),
            "avg_latency_ms": round(float(r[6] or 0.0), 1),
        }
        for r in feature_rows
    ]

    # --- Per-model breakdown ---
    model_rows = (await db.execute(
        select(
            AIUsage.model,
            func.count(AIUsage.id),
            func.sum(AIUsage.input_tokens),
            func.sum(AIUsage.output_tokens),
            func.sum(AIUsage.cost_usd),
        )
        .where(AIUsage.created_at >= start)
        .group_by(AIUsage.model)
        .order_by(func.sum(AIUsage.cost_usd).desc())
    )).all()

    by_model = []
    for r in model_rows:
        model = r[0] or "unknown"
        try:
            known = bool(pricing.is_known_model(model))
        except Exception:
            known = False
        by_model.append({
            "model": model,
            "requests": int(r[1] or 0),
            "input_tokens": int(r[2] or 0),
            "output_tokens": int(r[3] or 0),
            "cost_usd": _cost(r[4]),
            "known_pricing": known,
        })

    # --- Recent calls ---
    recent_rows = (await db.execute(
        select(
            AIUsage.created_at,
            AIUsage.feature,
            AIUsage.model,
            AIUsage.input_tokens,
            AIUsage.output_tokens,
            AIUsage.cost_usd,
            AIUsage.latency_ms,
            AIUsage.success,
            AIUsage.error,
        )
        # Window-scoped like every other aggregate here — the table sits inside
        # the card the 7d/30d/90d buttons drive, so it must move with them.
        .where(AIUsage.created_at >= start)
        .order_by(AIUsage.created_at.desc(), AIUsage.id.desc())
        .limit(_RECENT_LIMIT)
    )).all()

    recent = [
        {
            "created_at": _iso(r[0]),
            "feature": r[1] or "unknown",
            "model": r[2] or "unknown",
            "input_tokens": int(r[3] or 0),
            "output_tokens": int(r[4] or 0),
            "cost_usd": _cost(r[5]),
            "latency_ms": int(r[6] or 0),
            "success": bool(r[7]),
            "error": r[8],
        }
        for r in recent_rows
    ]

    # --- Models seen in the window that pricing.py can't price ---
    distinct_models = (await db.execute(
        select(AIUsage.model).where(AIUsage.created_at >= start).distinct()
    )).scalars().all()

    unknown_models = []
    for m in distinct_models:
        if not m:
            continue
        try:
            if not pricing.is_known_model(m):
                unknown_models.append(m)
        except Exception:
            unknown_models.append(m)
    unknown_models.sort()

    return {
        "days": days,
        "bucket": bucket,
        "summary": summary,
        "all_time": all_time,
        "timeseries": timeseries,
        "by_feature": by_feature,
        "by_model": by_model,
        "recent": recent,
        "pricing": {
            "as_of": pricing.PRICING_AS_OF,
            "unknown_models": unknown_models,
            # Always true: cost is derived from token counts, not billed amounts.
            "estimated": True,
        },
    }
