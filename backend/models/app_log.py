from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class AppLog(Base):
    __tablename__ = "app_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    device: Mapped[str] = mapped_column(String, nullable=False)
    app_version: Mapped[str] = mapped_column(String, nullable=False)
    timestamp: Mapped[str] = mapped_column(String, nullable=False)  # ISO from client
    logs: Mapped[str] = mapped_column(Text, nullable=False)
    username: Mapped[str | None] = mapped_column(String)  # Subsonic user who uploaded
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
