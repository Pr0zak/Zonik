from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class TrackLyrics(Base):
    """A track's lyrics, found once and kept (see backend/services/lyrics.py).

    `status` is `found` or `none`; a `none` row is looked for again after a while, since
    LRCLIB grows. `lines` is a JSON list of [ms, text], ms -1 for untimed lyrics. `source` is
    `tags` (embedded in the file), `lrc` (a .lrc file beside it) or `lrclib`.
    """
    __tablename__ = "track_lyrics"

    track_id: Mapped[str] = mapped_column(String, ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str | None] = mapped_column(String)
    synced: Mapped[bool] = mapped_column(Boolean, default=False)
    lines: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
