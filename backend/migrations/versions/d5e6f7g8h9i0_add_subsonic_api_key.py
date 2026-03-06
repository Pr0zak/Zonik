"""add subsonic_api_key to users

Revision ID: d5e6f7g8h9i0
Revises: c4d5e6f7g8h9
Create Date: 2026-03-06 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd5e6f7g8h9i0'
down_revision: Union[str, None] = 'c4d5e6f7g8h9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('subsonic_api_key', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'subsonic_api_key')
