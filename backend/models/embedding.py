from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, LargeBinary, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class TrackEmbedding(Base):
    __tablename__ = "track_embeddings"

    track_id: Mapped[str] = mapped_column(String, ForeignKey("tracks.id"), primary_key=True)
    embedding: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    model_version: Mapped[str] = mapped_column(String, default="clap-htsat-base")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
