"""Track mood tags derived from CLAP embeddings and optional AI refinement."""
from __future__ import annotations

from sqlalchemy import String, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base
from backend.models.mixins import CreatedAtMixin


class TrackMood(CreatedAtMixin, Base):
    __tablename__ = "track_moods"

    track_id: Mapped[str] = mapped_column(String, ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True)
    moods: Mapped[str] = mapped_column(String, default="")  # comma-separated mood tags
    primary_mood: Mapped[str | None] = mapped_column(String, nullable=True)  # strongest mood
    confidence: Mapped[float] = mapped_column(Float, default=0.0)  # 0-1 confidence of primary mood
    source: Mapped[str] = mapped_column(String, default="clap")  # "clap" or "ai"

    track = relationship("Track", backref="mood_data")
