from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class SoulseekSnapshot(Base):
    __tablename__ = "soulseek_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    connected: Mapped[bool] = mapped_column(Boolean, default=False)
    peers: Mapped[int] = mapped_column(Integer, default=0)
    active_transfers: Mapped[int] = mapped_column(Integer, default=0)
    completed_transfers: Mapped[int] = mapped_column(Integer, default=0)
    failed_transfers: Mapped[int] = mapped_column(Integer, default=0)
    queued_transfers: Mapped[int] = mapped_column(Integer, default=0)
    bytes_transferred: Mapped[int] = mapped_column(Integer, default=0)
    speed: Mapped[int] = mapped_column(Integer, default=0)
    active_searches: Mapped[int] = mapped_column(Integer, default=0)
