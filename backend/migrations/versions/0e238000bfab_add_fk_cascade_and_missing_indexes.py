"""add FK cascade and missing indexes

Revision ID: 0e238000bfab
Revises: k2l3m4n5o6p7
Create Date: 2026-03-18 11:52:36.671845

SQLite doesn't support ALTER TABLE for FK changes, so we use raw SQL
to recreate tables with CASCADE constraints via rename-copy-drop pattern.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0e238000bfab'
down_revision: Union[str, None] = 'k2l3m4n5o6p7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _sqlite_recreate_table(table_name: str, new_ddl: str, columns: str):
    """Recreate a SQLite table with new schema (rename-copy-drop pattern)."""
    op.execute(sa.text(f"ALTER TABLE {table_name} RENAME TO _{table_name}_old"))
    op.execute(sa.text(new_ddl))
    op.execute(sa.text(f"INSERT INTO {table_name} ({columns}) SELECT {columns} FROM _{table_name}_old"))
    op.execute(sa.text(f"DROP TABLE _{table_name}_old"))


def upgrade() -> None:
    conn = op.get_bind()
    is_sqlite = conn.dialect.name == "sqlite"

    # --- New indexes (IF NOT EXISTS for idempotency) ---
    if is_sqlite:
        op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_albums_artist_id ON albums (artist_id)"))
        op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_playlists_user_id ON playlists (user_id)"))
        op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_users_subsonic_api_key ON users (subsonic_api_key)"))
        op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_recommendations_status ON recommendations (status)"))
    else:
        op.create_index('ix_albums_artist_id', 'albums', ['artist_id'])
        op.create_index('ix_playlists_user_id', 'playlists', ['user_id'])
        op.create_index('ix_users_subsonic_api_key', 'users', ['subsonic_api_key'])
        op.create_index('ix_recommendations_status', 'recommendations', ['status'])

    if is_sqlite:
        # SQLite: recreate tables with CASCADE FKs via raw SQL

        # --- bookmarks: add CASCADE + user_id index ---
        _sqlite_recreate_table('bookmarks', """
            CREATE TABLE bookmarks (
                id VARCHAR NOT NULL,
                user_id VARCHAR NOT NULL,
                track_id VARCHAR NOT NULL,
                position_ms INTEGER NOT NULL,
                comment TEXT,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                PRIMARY KEY (id),
                CONSTRAINT uq_bookmark_user_track UNIQUE (user_id, track_id),
                FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
                FOREIGN KEY(track_id) REFERENCES tracks (id) ON DELETE CASCADE
            )
        """, "id, user_id, track_id, position_ms, comment, created_at, updated_at")
        op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_bookmarks_user_id ON bookmarks (user_id)"))

        # --- favorites: add CASCADE ---
        _sqlite_recreate_table('favorites', """
            CREATE TABLE favorites (
                id VARCHAR NOT NULL,
                user_id VARCHAR NOT NULL,
                track_id VARCHAR,
                album_id VARCHAR,
                artist_id VARCHAR,
                starred_at DATETIME NOT NULL,
                PRIMARY KEY (id),
                CONSTRAINT uq_fav_user_track UNIQUE (user_id, track_id),
                CONSTRAINT uq_fav_user_album UNIQUE (user_id, album_id),
                CONSTRAINT uq_fav_user_artist UNIQUE (user_id, artist_id),
                FOREIGN KEY(user_id) REFERENCES users (id),
                FOREIGN KEY(track_id) REFERENCES tracks (id) ON DELETE CASCADE,
                FOREIGN KEY(album_id) REFERENCES albums (id) ON DELETE CASCADE,
                FOREIGN KEY(artist_id) REFERENCES artists (id) ON DELETE CASCADE
            )
        """, "id, user_id, track_id, album_id, artist_id, starred_at")
        # Re-create existing indexes on favorites
        op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_favorites_track_id ON favorites (track_id)"))
        op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_favorites_album_id ON favorites (album_id)"))
        op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_favorites_artist_id ON favorites (artist_id)"))

        # --- play_queue: CASCADE on user_id, SET NULL on current_track_id ---
        _sqlite_recreate_table('play_queue', """
            CREATE TABLE play_queue (
                user_id VARCHAR NOT NULL,
                current_track_id VARCHAR,
                position_ms INTEGER NOT NULL,
                track_ids TEXT,
                updated_at DATETIME NOT NULL,
                PRIMARY KEY (user_id),
                FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
                FOREIGN KEY(current_track_id) REFERENCES tracks (id) ON DELETE SET NULL
            )
        """, "user_id, current_track_id, position_ms, track_ids, updated_at")

        # --- track_upgrades: CASCADE on track_id ---
        _sqlite_recreate_table('track_upgrades', """
            CREATE TABLE track_upgrades (
                id VARCHAR NOT NULL,
                track_id VARCHAR NOT NULL,
                original_format VARCHAR NOT NULL,
                original_bitrate INTEGER,
                original_file_size INTEGER,
                target_format VARCHAR,
                status VARCHAR NOT NULL,
                upgraded_format VARCHAR,
                upgraded_bitrate INTEGER,
                upgraded_file_size INTEGER,
                track_title VARCHAR,
                track_artist VARCHAR,
                reason VARCHAR NOT NULL,
                error_message TEXT,
                job_id VARCHAR,
                attempts INTEGER NOT NULL,
                max_attempts INTEGER NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME,
                completed_at DATETIME,
                PRIMARY KEY (id),
                FOREIGN KEY(track_id) REFERENCES tracks (id) ON DELETE CASCADE
            )
        """, "id, track_id, original_format, original_bitrate, original_file_size, target_format, status, upgraded_format, upgraded_bitrate, upgraded_file_size, track_title, track_artist, reason, error_message, job_id, attempts, max_attempts, created_at, updated_at, completed_at")
        # Re-create existing indexes on track_upgrades
        op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_track_upgrades_track_id ON track_upgrades (track_id)"))
        op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_track_upgrades_status ON track_upgrades (status)"))

    else:
        # PostgreSQL: use standard ALTER TABLE
        with op.batch_alter_table('bookmarks') as batch_op:
            batch_op.create_index('ix_bookmarks_user_id', ['user_id'])
            batch_op.drop_constraint('bookmarks_user_id_fkey', type_='foreignkey')
            batch_op.drop_constraint('bookmarks_track_id_fkey', type_='foreignkey')
            batch_op.create_foreign_key('bookmarks_user_id_fkey', 'users', ['user_id'], ['id'], ondelete='CASCADE')
            batch_op.create_foreign_key('bookmarks_track_id_fkey', 'tracks', ['track_id'], ['id'], ondelete='CASCADE')

        with op.batch_alter_table('favorites') as batch_op:
            batch_op.drop_constraint('favorites_track_id_fkey', type_='foreignkey')
            batch_op.drop_constraint('favorites_album_id_fkey', type_='foreignkey')
            batch_op.drop_constraint('favorites_artist_id_fkey', type_='foreignkey')
            batch_op.create_foreign_key('favorites_track_id_fkey', 'tracks', ['track_id'], ['id'], ondelete='CASCADE')
            batch_op.create_foreign_key('favorites_album_id_fkey', 'albums', ['album_id'], ['id'], ondelete='CASCADE')
            batch_op.create_foreign_key('favorites_artist_id_fkey', 'artists', ['artist_id'], ['id'], ondelete='CASCADE')

        with op.batch_alter_table('play_queue') as batch_op:
            batch_op.drop_constraint('play_queue_user_id_fkey', type_='foreignkey')
            batch_op.drop_constraint('play_queue_current_track_id_fkey', type_='foreignkey')
            batch_op.create_foreign_key('play_queue_user_id_fkey', 'users', ['user_id'], ['id'], ondelete='CASCADE')
            batch_op.create_foreign_key('play_queue_current_track_id_fkey', 'tracks', ['current_track_id'], ['id'], ondelete='SET NULL')

        with op.batch_alter_table('track_upgrades') as batch_op:
            batch_op.drop_constraint('track_upgrades_track_id_fkey', type_='foreignkey')
            batch_op.create_foreign_key('track_upgrades_track_id_fkey', 'tracks', ['track_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    # Drop new indexes
    op.drop_index('ix_recommendations_status', 'recommendations')
    op.drop_index('ix_users_subsonic_api_key', 'users')
    op.drop_index('ix_playlists_user_id', 'playlists')
    op.drop_index('ix_albums_artist_id', 'albums')

    # Note: FK CASCADE removal on SQLite would require another table recreate.
    # Downgrade leaves CASCADE in place — harmless, and avoids data-loss risk.
