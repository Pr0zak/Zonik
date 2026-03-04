from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Float, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


class TrackAnalysis(Base):
    __tablename__ = "track_analysis"

    track_id: Mapped[str] = mapped_column(String, ForeignKey("tracks.id"), primary_key=True)
    bpm: Mapped[float | None] = mapped_column(Float)
    key: Mapped[str | None] = mapped_column(String)
    scale: Mapped[str | None] = mapped_column(String)
    energy: Mapped[float | None] = mapped_column(Float)
    danceability: Mapped[float | None] = mapped_column(Float)
    loudness: Mapped[float | None] = mapped_column(Float)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    track: Mapped["Track"] = relationship("Track", back_populates="analysis")
