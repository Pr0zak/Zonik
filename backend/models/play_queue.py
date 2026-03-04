from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class PlayQueue(Base):
    __tablename__ = "play_queue"

    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), primary_key=True)
    current_track_id: Mapped[str | None] = mapped_column(String, ForeignKey("tracks.id"))
    position_ms: Mapped[int] = mapped_column(Integer, default=0)
    track_ids: Mapped[str | None] = mapped_column(Text)  # JSON array
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
