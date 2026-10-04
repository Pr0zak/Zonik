from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Integer, Float, DateTime, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class TvVisualizerConfig(Base):
    """The TV visualizer's settings, shared by every TV and edited from the web UI.

    A single row (id 1). `config` is JSON whose keys mirror the app's settings; a key that is
    missing means "the app's default", so a setting added in a later app release needs no
    migration here. The server is the source of truth: TVs pull this and push their own
    changes back.
    """
    __tablename__ = "tv_visualizer_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    config: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String)  # "web" or a device name


class TvEffectStat(Base):
    """How a visualizer effect ran on one TV over one day, summed from the app's reports.

    Day buckets keep the table small (effects x devices x days) and still allow "the last
    week" or "the last month" views.
    """
    __tablename__ = "tv_effect_stats"
    __table_args__ = (UniqueConstraint("device_id", "effect", "day", name="uq_tv_effect_stats"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    device_name: Mapped[str | None] = mapped_column(String)
    effect: Mapped[str] = mapped_column(String, nullable=False, index=True)
    day: Mapped[str] = mapped_column(String, nullable=False, index=True)  # YYYY-MM-DD, UTC
    seconds_shown: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    frames: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    kicks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    times_shown: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_shown_at: Mapped[datetime | None] = mapped_column(DateTime)
