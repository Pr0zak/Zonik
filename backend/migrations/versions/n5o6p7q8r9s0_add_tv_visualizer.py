"""add tv_visualizer_config and tv_effect_stats

Revision ID: n5o6p7q8r9s0
Revises: m4n5o6p7q8r9
Create Date: 2026-10-04 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "n5o6p7q8r9s0"
down_revision: Union[str, None] = "m4n5o6p7q8r9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS throughout: upgrade.sh's init_db() (create_all) makes these tables before
    # alembic ever runs, so this has to be safe to replay over them.
    op.execute("""
        CREATE TABLE IF NOT EXISTS tv_visualizer_config (
            id INTEGER NOT NULL PRIMARY KEY,
            config TEXT NOT NULL DEFAULT '{}',
            updated_at DATETIME NOT NULL,
            updated_by VARCHAR
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS tv_effect_stats (
            id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
            device_id VARCHAR NOT NULL,
            device_name VARCHAR,
            effect VARCHAR NOT NULL,
            day VARCHAR NOT NULL,
            seconds_shown FLOAT NOT NULL DEFAULT 0,
            frames INTEGER NOT NULL DEFAULT 0,
            kicks INTEGER NOT NULL DEFAULT 0,
            times_shown INTEGER NOT NULL DEFAULT 0,
            last_shown_at DATETIME,
            CONSTRAINT uq_tv_effect_stats UNIQUE (device_id, effect, day)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_tv_effect_stats_device_id ON tv_effect_stats (device_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tv_effect_stats_effect ON tv_effect_stats (effect)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tv_effect_stats_day ON tv_effect_stats (day)")


def downgrade() -> None:
    op.drop_index("ix_tv_effect_stats_day", table_name="tv_effect_stats")
    op.drop_index("ix_tv_effect_stats_effect", table_name="tv_effect_stats")
    op.drop_index("ix_tv_effect_stats_device_id", table_name="tv_effect_stats")
    op.drop_table("tv_effect_stats")
    op.drop_table("tv_visualizer_config")
