from __future__ import annotations

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from backend.config import get_settings


class Base(DeclarativeBase):
    pass


def get_engine():
    settings = get_settings()
    db_path = Path(settings.database.path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )


engine = get_engine()
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with async_session() as session:
        yield session


async def init_db():
    """Enable WAL mode, create tables, and set up FTS5."""
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        await conn.run_sync(Base.metadata.create_all)

        # Create FTS5 virtual table for full-text search
        await conn.exec_driver_sql("""
            CREATE VIRTUAL TABLE IF NOT EXISTS tracks_fts USING fts5(
                track_id UNINDEXED, title, artist_name, album_title
            )
        """)


async def update_fts_index(db: AsyncSession, track_id: str, title: str,
                           artist_name: str | None, album_title: str | None):
    """Update the FTS5 index for a track."""
    await db.execute(text("DELETE FROM tracks_fts WHERE track_id = :tid"), {"tid": track_id})
    await db.execute(
        text("INSERT INTO tracks_fts(track_id, title, artist_name, album_title) VALUES (:tid, :title, :artist, :album)"),
        {"tid": track_id, "title": title or "", "artist": artist_name or "", "album": album_title or ""},
    )


async def search_fts(db: AsyncSession, query: str, limit: int = 50) -> list[str]:
    """Search FTS5 index, return matching track IDs."""
    fts_query = " ".join(f"{word}*" for word in query.split() if word)
    if not fts_query:
        return []

    try:
        result = await db.execute(
            text("SELECT track_id FROM tracks_fts WHERE tracks_fts MATCH :query ORDER BY rank LIMIT :limit"),
            {"query": fts_query, "limit": limit},
        )
        return [row[0] for row in result.all()]
    except Exception:
        return []
