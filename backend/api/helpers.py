"""Shared API helpers."""
from __future__ import annotations

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession


async def paginate(db: AsyncSession, query, offset: int = 0, limit: int = 25):
    """Execute a paginated query and return {"items": [...], "total": int}.

    The query should already have filters and ordering applied.
    This helper adds the count, offset, and limit.
    """
    total = (await db.execute(
        select(func.count()).select_from(query.subquery())
    )).scalar() or 0
    result = await db.execute(query.offset(offset).limit(limit))
    items = result.scalars().all()
    return {"items": items, "total": total}
