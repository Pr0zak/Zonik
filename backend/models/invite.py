"""Single-use invite links: an admin creates one, a new user opens /join/<code> and picks a
username + password. No alembic revision: a new table that init_db's create_all makes."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    code: Mapped[str] = mapped_column(String, unique=True, nullable=False)  # secrets.token_urlsafe(9)
    role: Mapped[str] = mapped_column(String, nullable=False, default="user")  # user|admin
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    used_by: Mapped[str | None] = mapped_column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def status(self, now: datetime | None = None) -> str:
        """active | used | expired | revoked (used wins over revoked; revoke refuses used ones)."""
        if self.used_at is not None:
            return "used"
        if self.revoked_at is not None:
            return "revoked"
        if self.expires_at <= (now or datetime.utcnow()):
            return "expired"
        return "active"
