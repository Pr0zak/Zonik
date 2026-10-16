"""Cache of CLAP embeddings computed from 30-second iTunes preview clips.

Keyed by the preview URL and the CLAP model id, so a candidate that comes back night after
night is downloaded and embedded once, and switching analysis.clap_model never compares old
embeddings against a centroid built with the new model. Rows older than the recommender's retention window are pruned by the refresh."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, LargeBinary, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class PreviewEmbedding(Base):
    __tablename__ = "preview_embeddings"

    preview_url: Mapped[str] = mapped_column(String, primary_key=True)
    # Hugging Face model id from embeddings.clap_model_name()
    model: Mapped[str] = mapped_column(String, primary_key=True)
    # 512 float32 values, L2-normalised (same layout as track_embeddings.embedding)
    embedding: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
