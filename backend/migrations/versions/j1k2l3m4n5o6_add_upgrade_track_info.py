"""add track_title and track_artist to track_upgrades

Revision ID: j1k2l3m4n5o6
Revises: i0j1k2l3m4n5
Create Date: 2026-03-08 04:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'j1k2l3m4n5o6'
down_revision: Union[str, None] = 'i0j1k2l3m4n5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('track_upgrades', sa.Column('track_title', sa.String(), nullable=True))
    op.add_column('track_upgrades', sa.Column('track_artist', sa.String(), nullable=True))

    # Backfill from tracks table
    op.execute("""
        UPDATE track_upgrades SET
            track_title = (SELECT tracks.title FROM tracks WHERE tracks.id = track_upgrades.track_id),
            track_artist = (SELECT artists.name FROM tracks JOIN artists ON tracks.artist_id = artists.id WHERE tracks.id = track_upgrades.track_id)
        WHERE track_id IN (SELECT id FROM tracks)
    """)


def downgrade() -> None:
    op.drop_column('track_upgrades', 'track_artist')
    op.drop_column('track_upgrades', 'track_title')
