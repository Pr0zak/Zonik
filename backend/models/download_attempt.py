from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Integer, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class DownloadAttempt(Base):
    """Memory of failed automatic downloads, so the schedulers stop retrying the
    same unfindable track every night. One row per normalised artist::title."""
    __tablename__ = "download_attempts"

    key: Mapped[str] = mapped_column(String, primary_key=True)  # norm_artist::norm_title
    artist: Mapped[str] = mapped_column(String, nullable=False)
    track: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str | None] = mapped_column(String)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_job_id: Mapped[str | None] = mapped_column(String)
