"""add FK cascade and missing indexes

Revision ID: 0e238000bfab
Revises: k2l3m4n5o6p7
Create Date: 2026-03-18 11:52:36.671845
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0e238000bfab'
down_revision: Union[str, None] = 'k2l3m4n5o6p7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- New indexes ---
    with op.batch_alter_table('albums', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_albums_artist_id'), ['artist_id'], unique=False)

    with op.batch_alter_table('playlists', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_playlists_user_id'), ['user_id'], unique=False)

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_subsonic_api_key'), ['subsonic_api_key'], unique=False)

    # --- FK cascade on bookmarks (+ new user_id index) ---
    with op.batch_alter_table('bookmarks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_bookmarks_user_id'), ['user_id'], unique=False)
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.create_foreign_key(None, 'users', ['user_id'], ['id'], ondelete='CASCADE')
        batch_op.create_foreign_key(None, 'tracks', ['track_id'], ['id'], ondelete='CASCADE')

    # --- FK cascade on favorites ---
    with op.batch_alter_table('favorites', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.create_foreign_key(None, 'tracks', ['track_id'], ['id'], ondelete='CASCADE')
        batch_op.create_foreign_key(None, 'albums', ['album_id'], ['id'], ondelete='CASCADE')
        batch_op.create_foreign_key(None, 'artists', ['artist_id'], ['id'], ondelete='CASCADE')

    # --- FK cascade on play_queue ---
    with op.batch_alter_table('play_queue', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.create_foreign_key(None, 'users', ['user_id'], ['id'], ondelete='CASCADE')
        batch_op.create_foreign_key(None, 'tracks', ['current_track_id'], ['id'], ondelete='SET NULL')

    # --- FK cascade on track_upgrades ---
    with op.batch_alter_table('track_upgrades', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.create_foreign_key(None, 'tracks', ['track_id'], ['id'], ondelete='CASCADE')

    # --- Add status index on recommendations ---
    with op.batch_alter_table('recommendations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_recommendations_status'), ['status'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('recommendations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_recommendations_status'))

    with op.batch_alter_table('track_upgrades', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.create_foreign_key(None, 'tracks', ['track_id'], ['id'])

    with op.batch_alter_table('play_queue', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.create_foreign_key(None, 'users', ['user_id'], ['id'])
        batch_op.create_foreign_key(None, 'tracks', ['current_track_id'], ['id'])

    with op.batch_alter_table('favorites', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.create_foreign_key(None, 'artists', ['artist_id'], ['id'])
        batch_op.create_foreign_key(None, 'albums', ['album_id'], ['id'])
        batch_op.create_foreign_key(None, 'tracks', ['track_id'], ['id'])

    with op.batch_alter_table('bookmarks', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.create_foreign_key(None, 'users', ['user_id'], ['id'])
        batch_op.create_foreign_key(None, 'tracks', ['track_id'], ['id'])
        batch_op.drop_index(batch_op.f('ix_bookmarks_user_id'))

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_subsonic_api_key'))

    with op.batch_alter_table('playlists', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_playlists_user_id'))

    with op.batch_alter_table('albums', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_albums_artist_id'))
