"""Shared model mixins."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """Adds created_at and updated_at columns."""
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CreatedAtMixin:
    """Adds only created_at column (for models without updated_at)."""
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
