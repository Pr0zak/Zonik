from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Integer, Float, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class AIUsage(Base):
    """One row per Claude API call — raw token counts plus a cost estimate.

    Token counts are the durable record; cost_usd is computed at insert time from
    backend.services.ai.pricing, so it can always be recomputed if rates change.
    """
    __tablename__ = "ai_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True, nullable=False)
    feature: Mapped[str] = mapped_column(String, nullable=False, index=True)  # recommendations, nl_search, playlist_gen, ...
    model: Mapped[str] = mapped_column(String, nullable=False, index=True)  # raw model id as sent to the API
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error: Mapped[str | None] = mapped_column(String)  # short error label when success=False
