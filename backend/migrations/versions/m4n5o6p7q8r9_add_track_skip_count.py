"""add skip_count and last_skipped_at to tracks

Revision ID: m4n5o6p7q8r9
Revises: l3m4n5o6p7q8
Create Date: 2026-09-22 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "m4n5o6p7q8r9"
down_revision: Union[str, None] = "l3m4n5o6p7q8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tracks", sa.Column("skip_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("tracks", sa.Column("last_skipped_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tracks") as batch:
        batch.drop_column("last_skipped_at")
        batch.drop_column("skip_count")
