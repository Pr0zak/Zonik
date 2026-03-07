"""add recommendations and taste_profiles tables

Revision ID: f7g8h9i0j1k2
Revises: e6f7g8h9i0j1
Create Date: 2026-03-06 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f7g8h9i0j1k2'
down_revision: Union[str, None] = 'e6f7g8h9i0j1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'recommendations',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('artist', sa.String(), nullable=False),
        sa.Column('track', sa.String(), nullable=False),
        sa.Column('source', sa.String(), nullable=True),
        sa.Column('source_detail', sa.Text(), nullable=True),
        sa.Column('score', sa.Float(), server_default='0.0'),
        sa.Column('score_breakdown', sa.Text(), nullable=True),
        sa.Column('status', sa.String(), server_default='pending'),
        sa.Column('feedback', sa.String(), nullable=True),
        sa.Column('explanation', sa.Text(), nullable=True),
        sa.Column('lastfm_listeners', sa.Integer(), nullable=True),
        sa.Column('lastfm_match', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_recommendations_status', 'recommendations', ['status'])
    op.create_index('ix_recommendations_score', 'recommendations', ['score'])

    op.create_table(
        'taste_profiles',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('profile_data', sa.Text(), nullable=False),
        sa.Column('clap_centroid', sa.LargeBinary(), nullable=True),
        sa.Column('track_count', sa.Integer(), server_default='0'),
        sa.Column('favorite_count', sa.Integer(), server_default='0'),
        sa.Column('analyzed_count', sa.Integer(), server_default='0'),
        sa.Column('computed_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('taste_profiles')
    op.drop_index('ix_recommendations_score', 'recommendations')
    op.drop_index('ix_recommendations_status', 'recommendations')
    op.drop_table('recommendations')
