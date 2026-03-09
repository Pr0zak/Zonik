"""Track mood tags derived from CLAP embeddings and optional AI refinement."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import relationship

from backend.database import Base


class TrackMood(Base):
    __tablename__ = "track_moods"

    track_id = Column(String, ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True)
    moods = Column(String, default="")  # comma-separated mood tags
    primary_mood = Column(String, nullable=True)  # strongest mood
    confidence = Column(Float, default=0.0)  # 0-1 confidence of primary mood
    source = Column(String, default="clap")  # "clap" or "ai"
    created_at = Column(DateTime, default=datetime.utcnow)

    track = relationship("Track", backref="mood_data")
