from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


class Album(Base):
    __tablename__ = "albums"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    artist_id: Mapped[str | None] = mapped_column(String, ForeignKey("artists.id"))
    year: Mapped[int | None] = mapped_column(Integer)
    genre: Mapped[str | None] = mapped_column(String)
    musicbrainz_id: Mapped[str | None] = mapped_column(String)
    cover_art_path: Mapped[str | None] = mapped_column(String)
    track_count: Mapped[int | None] = mapped_column(Integer)
    is_compilation: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    artist: Mapped["Artist | None"] = relationship("Artist", back_populates="albums")
    tracks: Mapped[list["Track"]] = relationship("Track", back_populates="album")
