from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class DownloadBlacklist(Base):
    __tablename__ = "download_blacklist"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    artist: Mapped[str] = mapped_column(String, nullable=False)
    track: Mapped[str | None] = mapped_column(String)  # None = entire artist blocked
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
