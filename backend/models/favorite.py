from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


class Favorite(Base):
    __tablename__ = "favorites"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"))
    track_id: Mapped[str | None] = mapped_column(String, ForeignKey("tracks.id"), index=True)
    album_id: Mapped[str | None] = mapped_column(String, ForeignKey("albums.id"), index=True)
    artist_id: Mapped[str | None] = mapped_column(String, ForeignKey("artists.id"), index=True)
    starred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    track: Mapped["Track | None"] = relationship("Track")
    album: Mapped["Album | None"] = relationship("Album")
    artist: Mapped["Artist | None"] = relationship("Artist")

    __table_args__ = (
        UniqueConstraint("user_id", "track_id", name="uq_fav_user_track"),
        UniqueConstraint("user_id", "album_id", name="uq_fav_user_album"),
        UniqueConstraint("user_id", "artist_id", name="uq_fav_user_artist"),
    )
