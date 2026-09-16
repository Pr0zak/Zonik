"""add ai_usage table

Revision ID: l3m4n5o6p7q8
Revises: a1b2c3d4e5f6
Create Date: 2026-09-16 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "l3m4n5o6p7q8"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS ai_usage (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            created_at DATETIME NOT NULL,
            feature VARCHAR NOT NULL,
            model VARCHAR NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            cache_read_tokens INTEGER NOT NULL DEFAULT 0,
            cache_write_tokens INTEGER NOT NULL DEFAULT 0,
            cost_usd FLOAT NOT NULL DEFAULT 0.0,
            latency_ms INTEGER NOT NULL DEFAULT 0,
            success BOOLEAN NOT NULL DEFAULT 1,
            error VARCHAR
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_ai_usage_created_at ON ai_usage (created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ai_usage_feature ON ai_usage (feature)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ai_usage_model ON ai_usage (model)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ai_usage_model")
    op.execute("DROP INDEX IF EXISTS ix_ai_usage_feature")
    op.execute("DROP INDEX IF EXISTS ix_ai_usage_created_at")
    op.drop_table("ai_usage")
