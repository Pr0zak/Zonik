"""track_beat_grids: cached beat grids for the TV visualizer

Revision ID: s0t1u2v3w4x5
Revises: r9s0t1u2v3w4
Create Date: 2026-11-15 12:00:00.000000

A new table only; init_db's create_all also creates it on servers upgraded by upgrade.sh.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "s0t1u2v3w4x5"
down_revision: Union[str, None] = "r9s0t1u2v3w4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if "track_beat_grids" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "track_beat_grids",
        sa.Column("track_id", sa.String(), sa.ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("bpm", sa.Float()),
        sa.Column("downbeat_s", sa.Float()),
        sa.Column("beats_per_bar", sa.Integer()),
        sa.Column("confidence", sa.Float()),
        sa.Column("bar_energy", sa.Text()),
        sa.Column("drops", sa.Text()),
        sa.Column("error", sa.String()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("computed_at", sa.DateTime()),
    )


def downgrade() -> None:
    op.drop_table("track_beat_grids")
