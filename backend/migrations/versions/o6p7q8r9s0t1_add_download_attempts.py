"""add download_attempts (failed-search memory for automatic downloads)

Revision ID: o6p7q8r9s0t1
Revises: n5o6p7q8r9s0
Create Date: 2026-10-16 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "o6p7q8r9s0t1"
down_revision: Union[str, None] = "n5o6p7q8r9s0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS: upgrade.sh's init_db() (create_all) creates the table before alembic runs.
    op.execute("""
        CREATE TABLE IF NOT EXISTS download_attempts (
            key VARCHAR NOT NULL PRIMARY KEY,
            artist VARCHAR NOT NULL,
            track VARCHAR NOT NULL,
            source VARCHAR,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_attempt_at DATETIME,
            next_retry_at DATETIME,
            last_error TEXT,
            last_job_id VARCHAR
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_download_attempts_next_retry_at ON download_attempts (next_retry_at)")


def downgrade() -> None:
    op.drop_index("ix_download_attempts_next_retry_at", table_name="download_attempts")
    op.drop_table("download_attempts")
