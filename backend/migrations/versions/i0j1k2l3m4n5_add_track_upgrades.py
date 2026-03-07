"""add track upgrades table

Revision ID: i0j1k2l3m4n5
Revises: h9i0j1k2l3m4
Create Date: 2026-03-07 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'i0j1k2l3m4n5'
down_revision: Union[str, None] = 'h9i0j1k2l3m4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'track_upgrades',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('track_id', sa.String(), sa.ForeignKey('tracks.id'), nullable=False),
        sa.Column('original_format', sa.String(), nullable=False),
        sa.Column('original_bitrate', sa.Integer(), nullable=True),
        sa.Column('original_file_size', sa.Integer(), nullable=True),
        sa.Column('target_format', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('upgraded_format', sa.String(), nullable=True),
        sa.Column('upgraded_bitrate', sa.Integer(), nullable=True),
        sa.Column('upgraded_file_size', sa.Integer(), nullable=True),
        sa.Column('reason', sa.String(), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('job_id', sa.String(), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_track_upgrades_track_id', 'track_upgrades', ['track_id'])
    op.create_index('ix_track_upgrades_status', 'track_upgrades', ['status'])


def downgrade() -> None:
    op.drop_index('ix_track_upgrades_status', table_name='track_upgrades')
    op.drop_index('ix_track_upgrades_track_id', table_name='track_upgrades')
    op.drop_table('track_upgrades')
