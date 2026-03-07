from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Integer, DateTime, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


class TrackUpgrade(Base):
    __tablename__ = "track_upgrades"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    track_id: Mapped[str] = mapped_column(String, ForeignKey("tracks.id"), index=True)
    original_format: Mapped[str] = mapped_column(String, nullable=False)
    original_bitrate: Mapped[int | None] = mapped_column(Integer)
    original_file_size: Mapped[int | None] = mapped_column(Integer)
    target_format: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="pending", index=True)  # pending/queued/downloading/completed/failed/skipped
    upgraded_format: Mapped[str | None] = mapped_column(String)
    upgraded_bitrate: Mapped[int | None] = mapped_column(Integer)
    upgraded_file_size: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String, nullable=False)  # low_bitrate, lossy_to_lossless, opus_to_flac, all_lossy
    error_message: Mapped[str | None] = mapped_column(Text)
    job_id: Mapped[str | None] = mapped_column(String)  # link to download Job (plain string, not FK)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    track = relationship("Track")
