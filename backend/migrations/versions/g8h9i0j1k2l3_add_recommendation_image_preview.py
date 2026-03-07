"""add image_url and preview_url to recommendations

Revision ID: g8h9i0j1k2l3
Revises: f7g8h9i0j1k2
Create Date: 2026-03-06 20:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'g8h9i0j1k2l3'
down_revision: Union[str, None] = 'f7g8h9i0j1k2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('recommendations', sa.Column('image_url', sa.String(), nullable=True))
    op.add_column('recommendations', sa.Column('preview_url', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('recommendations', 'preview_url')
    op.drop_column('recommendations', 'image_url')
