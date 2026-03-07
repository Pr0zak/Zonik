from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Integer, DateTime, Text, LargeBinary
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class TasteProfile(Base):
    __tablename__ = "taste_profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # "default"
    profile_data: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    clap_centroid: Mapped[bytes | None] = mapped_column(LargeBinary)
    track_count: Mapped[int] = mapped_column(Integer, default=0)
    favorite_count: Mapped[int] = mapped_column(Integer, default=0)
    analyzed_count: Mapped[int] = mapped_column(Integer, default=0)
    computed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
