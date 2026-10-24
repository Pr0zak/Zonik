"""per-user data: play_history.user_id, recommendations.user_id, user_track_stats, owner backfill

Revision ID: r9s0t1u2v3w4
Revises: q8r9s0t1u2v3
Create Date: 2026-10-23 23:50:00.000000

Everything recorded before multi-user belongs to the owner: the first admin by created_at
(the `admin` account on production). Its id is looked up, never assumed. On an empty users
table (fresh install) there is nothing to backfill.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "r9s0t1u2v3w4"
down_revision: Union[str, None] = "q8r9s0t1u2v3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "user_id" not in {c["name"] for c in insp.get_columns("play_history")}:
        op.add_column("play_history", sa.Column("user_id", sa.String(), nullable=True))
    if "user_id" not in {c["name"] for c in insp.get_columns("recommendations")}:
        op.add_column("recommendations", sa.Column("user_id", sa.String(), nullable=True))
    op.execute("CREATE INDEX IF NOT EXISTS ix_play_history_user_id ON play_history (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_recommendations_user_id ON recommendations (user_id)")

    # create_all may already have made it (upgrade.sh runs before alembic).
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_track_stats (
            user_id VARCHAR NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            track_id VARCHAR NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
            play_count INTEGER NOT NULL DEFAULT 0,
            last_played_at DATETIME,
            skip_count INTEGER NOT NULL DEFAULT 0,
            last_skipped_at DATETIME,
            rating INTEGER,
            PRIMARY KEY (user_id, track_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_track_stats_track_id ON user_track_stats (track_id)")

    owner = bind.execute(sa.text(
        "SELECT id FROM users WHERE role = 'admin' AND disabled = 0 ORDER BY created_at LIMIT 1"
    )).scalar()
    if owner is None:
        return
    params = {"owner": owner}
    bind.execute(sa.text("UPDATE play_history SET user_id = :owner WHERE user_id IS NULL"), params)
    bind.execute(sa.text("UPDATE recommendations SET user_id = :owner WHERE user_id IS NULL"), params)
    # Ownerless playlists become the owner's, shared read-only with everyone else.
    bind.execute(sa.text("UPDATE playlists SET user_id = :owner, is_public = 1 WHERE user_id IS NULL"), params)
    # The single taste profile ("default") becomes the owner's.
    bind.execute(sa.text(
        "UPDATE taste_profiles SET id = :owner WHERE id = 'default' "
        "AND NOT EXISTS (SELECT 1 FROM taste_profiles WHERE id = :owner)"
    ), params)
    # The owner's per-track stats start equal to today's global totals.
    bind.execute(sa.text("""
        INSERT OR IGNORE INTO user_track_stats
            (user_id, track_id, play_count, last_played_at, skip_count, last_skipped_at, rating)
        SELECT :owner, id, COALESCE(play_count, 0), last_played_at,
               COALESCE(skip_count, 0), last_skipped_at, rating
        FROM tracks
        WHERE COALESCE(play_count, 0) > 0 OR COALESCE(skip_count, 0) > 0 OR rating IS NOT NULL
              OR last_played_at IS NOT NULL
    """), params)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_track_stats")
    with op.batch_alter_table("recommendations") as batch:
        batch.drop_column("user_id")
    with op.batch_alter_table("play_history") as batch:
        batch.drop_column("user_id")
