from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Float, DateTime, ForeignKey, Integer, Text
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


class TrackBeatGrid(Base):
    """A track's beat grid for the TV visualizer (see backend/services/beat_grid.py).

    Computed the first time a TV asks for it and cached, failures included, so a track that
    has no steady beat is not decoded again on every play. `version` is the computation's
    version: a row from an older one is recomputed on its next request.
    """
    __tablename__ = "track_beat_grids"

    track_id: Mapped[str] = mapped_column(String, ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(String, nullable=False)  # ready / none / failed
    bpm: Mapped[float | None] = mapped_column(Float)
    downbeat_s: Mapped[float | None] = mapped_column(Float)
    beats_per_bar: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float | None] = mapped_column(Float)
    bar_energy: Mapped[str | None] = mapped_column(Text)  # JSON list of 0..1, one per bar
    drops: Mapped[str | None] = mapped_column(Text)  # JSON list of bar indices
    error: Mapped[str | None] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
