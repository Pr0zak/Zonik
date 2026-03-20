"""add app_logs table

Revision ID: a1b2c3d4e5f6
Revises: 0e238000bfab
Create Date: 2026-03-20 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "0e238000bfab"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS app_logs (
            id VARCHAR NOT NULL PRIMARY KEY,
            device VARCHAR NOT NULL,
            app_version VARCHAR NOT NULL,
            timestamp VARCHAR NOT NULL,
            logs TEXT NOT NULL,
            username VARCHAR,
            created_at DATETIME
        )
    """)


def downgrade() -> None:
    op.drop_table("app_logs")
