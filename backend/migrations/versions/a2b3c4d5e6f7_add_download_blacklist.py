"""add download blacklist

Revision ID: a2b3c4d5e6f7
Revises: fc896cecfe77
Create Date: 2026-03-04 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, None] = 'fc896cecfe77'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('download_blacklist',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('artist', sa.String(), nullable=False),
        sa.Column('track', sa.String(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('download_blacklist')
