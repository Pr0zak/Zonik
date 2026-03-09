"""add track_moods table

Revision ID: k2l3m4n5o6p7
Revises: j1k2l3m4n5o6
Create Date: 2026-03-08
"""
from alembic import op
import sqlalchemy as sa

revision = "k2l3m4n5o6p7"
down_revision = "j1k2l3m4n5o6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "track_moods",
        sa.Column("track_id", sa.String(), sa.ForeignKey("tracks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("moods", sa.String(), server_default=""),
        sa.Column("primary_mood", sa.String(), nullable=True),
        sa.Column("confidence", sa.Float(), server_default="0.0"),
        sa.Column("source", sa.String(), server_default="clap"),
        sa.Column("created_at", sa.DateTime()),
    )


def downgrade() -> None:
    op.drop_table("track_moods")
