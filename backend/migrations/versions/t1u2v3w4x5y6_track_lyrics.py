"""track_lyrics: lyrics found for each track (tags, .lrc files, LRCLIB)

Revision ID: t1u2v3w4x5y6
Revises: s0t1u2v3w4x5
Create Date: 2026-11-20 12:00:00.000000

A new table only; init_db's create_all also creates it on servers upgraded by upgrade.sh.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "t1u2v3w4x5y6"
down_revision: Union[str, None] = "s0t1u2v3w4x5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "track_lyrics" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "track_lyrics",
        sa.Column("track_id", sa.String(), sa.ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("source", sa.String()),
        sa.Column("synced", sa.Boolean(), server_default=sa.false()),
        sa.Column("lines", sa.Text()),
        sa.Column("checked_at", sa.DateTime()),
    )


def downgrade() -> None:
    op.drop_table("track_lyrics")
