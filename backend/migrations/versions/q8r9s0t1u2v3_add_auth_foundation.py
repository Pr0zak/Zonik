"""auth foundation: user role/display_name/disabled/last_login_at, auth_sessions, device_tokens

Revision ID: q8r9s0t1u2v3
Revises: p7q8r9s0t1u2
Create Date: 2026-10-23 12:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "q8r9s0t1u2v3"
down_revision: Union[str, None] = "p7q8r9s0t1u2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent: upgrade.sh's init_db() (create_all) creates the two new tables before
    # alembic runs, and a fresh install's users table already has every column.
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())

    user_cols = {c["name"] for c in insp.get_columns("users")}
    if "display_name" not in user_cols:
        op.add_column("users", sa.Column("display_name", sa.String(), nullable=True))
    if "role" not in user_cols:
        op.add_column("users", sa.Column("role", sa.String(), nullable=False, server_default="user"))
    if "disabled" not in user_cols:
        op.add_column("users", sa.Column("disabled", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    if "last_login_at" not in user_cols:
        op.add_column("users", sa.Column("last_login_at", sa.DateTime(), nullable=True))
    # Existing admins (the owner's "admin" row on production) become role=admin; nothing else
    # about them changes: same id, username, password and API key.
    op.execute("UPDATE users SET role = 'admin' WHERE is_admin = 1")
    op.execute("UPDATE users SET disabled = 0 WHERE disabled IS NULL")

    if "auth_sessions" not in tables:
        op.create_table(
            "auth_sessions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("token_hash", sa.String(), nullable=False, unique=True),
            sa.Column("label", sa.String(), nullable=True),
            sa.Column("ip", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
        )
    if "device_tokens" not in tables:
        op.create_table(
            "device_tokens",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("token_hash", sa.String(), nullable=False, unique=True),
            sa.Column("label", sa.String(), nullable=True),
            sa.Column("platform", sa.String(), nullable=False, server_default="other"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(), nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
        )
    op.execute("CREATE INDEX IF NOT EXISTS ix_auth_sessions_user_id ON auth_sessions (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_device_tokens_user_id ON device_tokens (user_id)")


def downgrade() -> None:
    op.drop_table("device_tokens")
    op.drop_table("auth_sessions")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("last_login_at")
        batch.drop_column("disabled")
        batch.drop_column("role")
        batch.drop_column("display_name")
