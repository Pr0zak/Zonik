from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Boolean, DateTime, event, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base
from backend.models.mixins import CreatedAtMixin

ROLES = ("admin", "user")


class User(CreatedAtMixin, Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    subsonic_api_key: Mapped[str | None] = mapped_column(String, nullable=True, default=None, index=True)
    # Legacy flag, kept in step with role (see _sync_is_admin) for code that still reads it.
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    role: Mapped[str] = mapped_column(String, nullable=False, default="user", server_default="user")
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("0"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)


@event.listens_for(User, "before_insert")
@event.listens_for(User, "before_update")
def _sync_is_admin(_mapper, _conn, user: User) -> None:
    """role is the source of truth; is_admin follows it on every write."""
    user.is_admin = user.role == "admin"
