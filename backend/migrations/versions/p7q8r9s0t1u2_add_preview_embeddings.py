"""add preview_embeddings (CLAP embeddings of iTunes preview clips)

Revision ID: p7q8r9s0t1u2
Revises: o6p7q8r9s0t1
Create Date: 2026-10-16 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "p7q8r9s0t1u2"
down_revision: Union[str, None] = "o6p7q8r9s0t1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS: upgrade.sh's init_db() (create_all) creates the table before alembic runs.
    op.execute("""
        CREATE TABLE IF NOT EXISTS preview_embeddings (
            preview_url TEXT NOT NULL,
            model TEXT NOT NULL,
            embedding BLOB NOT NULL,
            created_at DATETIME NOT NULL,
            PRIMARY KEY (preview_url, model)
        )
    """)


def downgrade() -> None:
    op.drop_table("preview_embeddings")
