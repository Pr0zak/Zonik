from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Float, Integer, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    artist: Mapped[str] = mapped_column(String, nullable=False)
    track: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String)  # similar_track, similar_artist, tag, trending
    source_detail: Mapped[str | None] = mapped_column(Text)  # JSON context
    score: Mapped[float] = mapped_column(Float, default=0.0)
    score_breakdown: Mapped[str | None] = mapped_column(Text)  # JSON per-signal scores
    status: Mapped[str] = mapped_column(String, default="pending")  # pending, accepted, rejected, downloaded, expired
    feedback: Mapped[str | None] = mapped_column(String)  # thumbs_up, thumbs_down
    explanation: Mapped[str | None] = mapped_column(Text)
    lastfm_listeners: Mapped[int | None] = mapped_column(Integer)
    lastfm_match: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
