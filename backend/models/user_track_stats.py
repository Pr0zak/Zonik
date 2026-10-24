from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class UserTrackStats(Base):
    """One user's relationship with one track: plays, skips and rating.

    The global columns on `tracks` (play_count, skip_count, last_played_at, rating) stay as
    "anyone, any time" totals for library maintenance; everything a person sees as theirs
    (Subsonic playCount/userRating, recently/most played, shuffle, taste) reads this table.
    """
    __tablename__ = "user_track_stats"

    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    track_id: Mapped[str] = mapped_column(String, ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True, index=True)
    play_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_played_at: Mapped[datetime | None] = mapped_column(DateTime)
    skip_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_skipped_at: Mapped[datetime | None] = mapped_column(DateTime)
    rating: Mapped[int | None] = mapped_column(Integer)
