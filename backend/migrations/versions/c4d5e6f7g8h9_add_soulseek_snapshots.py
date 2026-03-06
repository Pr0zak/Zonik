"""add soulseek_snapshots table

Revision ID: c4d5e6f7g8h9
Revises: b3c4d5e6f7g8
Create Date: 2026-03-05 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4d5e6f7g8h9'
down_revision: Union[str, None] = 'b3c4d5e6f7g8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'soulseek_snapshots',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('connected', sa.Boolean(), nullable=True),
        sa.Column('peers', sa.Integer(), nullable=True),
        sa.Column('active_transfers', sa.Integer(), nullable=True),
        sa.Column('completed_transfers', sa.Integer(), nullable=True),
        sa.Column('failed_transfers', sa.Integer(), nullable=True),
        sa.Column('queued_transfers', sa.Integer(), nullable=True),
        sa.Column('bytes_transferred', sa.Integer(), nullable=True),
        sa.Column('speed', sa.Integer(), nullable=True),
        sa.Column('active_searches', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_soulseek_snapshots_timestamp', 'soulseek_snapshots', ['timestamp'])


def downgrade() -> None:
    op.drop_index('ix_soulseek_snapshots_timestamp')
    op.drop_table('soulseek_snapshots')
