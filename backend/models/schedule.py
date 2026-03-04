from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Boolean, Integer, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class ScheduleTask(Base):
    __tablename__ = "schedule_tasks"

    task_name: Mapped[str] = mapped_column(String, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    interval_hours: Mapped[int] = mapped_column(Integer, default=24)
    run_at: Mapped[str | None] = mapped_column(String)  # HH:MM
    day_of_week: Mapped[int | None] = mapped_column(Integer)  # 0=Mon, 6=Sun
    config: Mapped[str | None] = mapped_column(Text)  # JSON
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime)
