"""add play_history table and tracks.rating column

Revision ID: e6f7g8h9i0j1
Revises: d5e6f7g8h9i0
Create Date: 2026-03-06 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e6f7g8h9i0j1'
down_revision: Union[str, None] = 'd5e6f7g8h9i0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'play_history',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('track_id', sa.String(), nullable=False),
        sa.Column('played_at', sa.DateTime(), nullable=False),
        sa.Column('source', sa.String(), server_default='web'),
        sa.ForeignKeyConstraint(['track_id'], ['tracks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_play_history_track_id', 'play_history', ['track_id'])
    op.create_index('ix_play_history_played_at', 'play_history', ['played_at'])

    op.add_column('tracks', sa.Column('rating', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('tracks', 'rating')
    op.drop_index('ix_play_history_played_at', 'play_history')
    op.drop_index('ix_play_history_track_id', 'play_history')
    op.drop_table('play_history')
