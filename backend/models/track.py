from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


class Track(Base):
    __tablename__ = "tracks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    artist_id: Mapped[str | None] = mapped_column(String, ForeignKey("artists.id"), index=True)
    album_id: Mapped[str | None] = mapped_column(String, ForeignKey("albums.id"), index=True)
    track_number: Mapped[int | None] = mapped_column(Integer)
    disc_number: Mapped[int] = mapped_column(Integer, default=1)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    file_path: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    file_size: Mapped[int | None] = mapped_column(Integer)
    format: Mapped[str | None] = mapped_column(String)
    bitrate: Mapped[int | None] = mapped_column(Integer)
    sample_rate: Mapped[int | None] = mapped_column(Integer)
    bit_depth: Mapped[int | None] = mapped_column(Integer)
    mime_type: Mapped[str | None] = mapped_column(String)
    genre: Mapped[str | None] = mapped_column(String)
    year: Mapped[int | None] = mapped_column(Integer)
    musicbrainz_id: Mapped[str | None] = mapped_column(String)
    acoustid: Mapped[str | None] = mapped_column(String)
    cover_art_path: Mapped[str | None] = mapped_column(String)
    replay_gain_track: Mapped[float | None] = mapped_column(Float)
    replay_gain_album: Mapped[float | None] = mapped_column(Float)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    play_count: Mapped[int] = mapped_column(Integer, default=0)
    last_played_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    artist: Mapped["Artist | None"] = relationship("Artist", back_populates="tracks")
    album: Mapped["Album | None"] = relationship("Album", back_populates="tracks")
    analysis: Mapped["TrackAnalysis | None"] = relationship("TrackAnalysis", back_populates="track", uselist=False)

    @property
    def suffix(self) -> str:
        return self.file_path.rsplit(".", 1)[-1].lower() if "." in self.file_path else ""
