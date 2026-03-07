"""add performance indexes

Revision ID: h9i0j1k2l3m4
Revises: g8h9i0j1k2l3
Create Date: 2026-03-07 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'h9i0j1k2l3m4'
down_revision: Union[str, None] = 'g8h9i0j1k2l3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(op.f('ix_tracks_artist_id'), 'tracks', ['artist_id'])
    op.create_index(op.f('ix_tracks_album_id'), 'tracks', ['album_id'])
    op.create_index(op.f('ix_favorites_track_id'), 'favorites', ['track_id'])
    op.create_index(op.f('ix_favorites_album_id'), 'favorites', ['album_id'])
    op.create_index(op.f('ix_favorites_artist_id'), 'favorites', ['artist_id'])
    op.create_index(op.f('ix_jobs_type'), 'jobs', ['type'])
    op.create_index(op.f('ix_jobs_status'), 'jobs', ['status'])


def downgrade() -> None:
    op.drop_index(op.f('ix_jobs_status'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_type'), table_name='jobs')
    op.drop_index(op.f('ix_favorites_artist_id'), table_name='favorites')
    op.drop_index(op.f('ix_favorites_album_id'), table_name='favorites')
    op.drop_index(op.f('ix_favorites_track_id'), table_name='favorites')
    op.drop_index(op.f('ix_tracks_album_id'), table_name='tracks')
    op.drop_index(op.f('ix_tracks_artist_id'), table_name='tracks')
