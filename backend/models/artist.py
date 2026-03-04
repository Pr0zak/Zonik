from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


class Artist(Base):
    __tablename__ = "artists"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    sort_name: Mapped[str | None] = mapped_column(String)
    musicbrainz_id: Mapped[str | None] = mapped_column(String)
    image_url: Mapped[str | None] = mapped_column(String)
    biography: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    albums: Mapped[list["Album"]] = relationship("Album", back_populates="artist")
    tracks: Mapped[list["Track"]] = relationship("Track", back_populates="artist")

    @property
    def display_name(self) -> str:
        return self.sort_name or self.name
