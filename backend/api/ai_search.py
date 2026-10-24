"""AI-powered search API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.services.ai.nl_search import detect_nl_query, interpret_query, search_with_filters
from backend.services.user_data import caller_id

router = APIRouter()


class AISearchRequest(BaseModel):
    query: str
    limit: int = 50


@router.post("/ai")
async def ai_search(req: AISearchRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Natural language search — interpret query and find matching tracks."""
    # Interpret the query
    filters = await interpret_query(req.query)
    if "error" in filters:
        return {"error": filters["error"], "tracks": [], "total": 0}

    # Search with interpreted filters
    tracks = await search_with_filters(db, filters, limit=req.limit, user_id=await caller_id(request, db))

    return {
        "tracks": tracks,
        "total": len(tracks),
        "filters": {k: v for k, v in filters.items() if v is not None and k != "error"},
        "ai_interpreted": True,
    }


@router.post("/detect-nl")
async def check_nl_query(req: AISearchRequest):
    """Check if a query looks like natural language."""
    return {"is_natural_language": detect_nl_query(req.query)}
