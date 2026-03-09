from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from backend.config import get_settings


class Base(DeclarativeBase):
    pass


def _is_postgres() -> bool:
    return get_settings().database.backend == "postgresql"


def get_engine():
    settings = get_settings()

    if settings.database.backend == "postgresql" and settings.database.url:
        url = settings.database.url
        if not url.startswith("postgresql+asyncpg://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return create_async_engine(url, echo=False, pool_size=10, max_overflow=20)

    # Default: SQLite
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
    """Initialize database: create tables, set up search, apply optimizations."""
    async with engine.begin() as conn:
        if not _is_postgres():
            # SQLite optimizations
            await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
            await conn.exec_driver_sql("PRAGMA synchronous=NORMAL")
            await conn.exec_driver_sql("PRAGMA cache_size=-32000")  # 32MB cache
            await conn.exec_driver_sql("PRAGMA mmap_size=268435456")  # 256MB mmap

        await conn.run_sync(Base.metadata.create_all)

        if not _is_postgres():
            # SQLite: FTS5 virtual table for full-text search
            await conn.exec_driver_sql("""
                CREATE VIRTUAL TABLE IF NOT EXISTS tracks_fts USING fts5(
                    track_id UNINDEXED, title, artist_name, album_title
                )
            """)
        else:
            # PostgreSQL: tsvector column + GIN index for full-text search
            # Create helper function and trigger for auto-updating tsvector
            await conn.exec_driver_sql("""
                CREATE TABLE IF NOT EXISTS tracks_search (
                    track_id VARCHAR PRIMARY KEY,
                    title TEXT DEFAULT '',
                    artist_name TEXT DEFAULT '',
                    album_title TEXT DEFAULT '',
                    search_vector TSVECTOR
                )
            """)
            await conn.exec_driver_sql("""
                CREATE INDEX IF NOT EXISTS idx_tracks_search_vector
                ON tracks_search USING GIN(search_vector)
            """)


async def update_fts_index(db: AsyncSession, track_id: str, title: str,
                           artist_name: str | None, album_title: str | None):
    """Update the full-text search index for a track."""
    if _is_postgres():
        search_text = " ".join(filter(None, [title, artist_name, album_title]))
        await db.execute(text("""
            INSERT INTO tracks_search (track_id, title, artist_name, album_title, search_vector)
            VALUES (:tid, :title, :artist, :album, to_tsvector('english', :search_text))
            ON CONFLICT (track_id) DO UPDATE SET
                title = :title, artist_name = :artist, album_title = :album,
                search_vector = to_tsvector('english', :search_text)
        """), {"tid": track_id, "title": title or "", "artist": artist_name or "",
               "album": album_title or "", "search_text": search_text})
    else:
        await db.execute(text("DELETE FROM tracks_fts WHERE track_id = :tid"), {"tid": track_id})
        await db.execute(
            text("INSERT INTO tracks_fts(track_id, title, artist_name, album_title) VALUES (:tid, :title, :artist, :album)"),
            {"tid": track_id, "title": title or "", "artist": artist_name or "", "album": album_title or ""},
        )


async def search_fts(db: AsyncSession, query: str, limit: int = 50) -> list[str]:
    """Search full-text index, return matching track IDs."""
    if not query or not query.strip():
        return []

    try:
        if _is_postgres():
            # PostgreSQL: plainto_tsquery for simpler query syntax
            result = await db.execute(
                text("""
                    SELECT track_id FROM tracks_search
                    WHERE search_vector @@ plainto_tsquery('english', :query)
                    ORDER BY ts_rank(search_vector, plainto_tsquery('english', :query)) DESC
                    LIMIT :limit
                """),
                {"query": query, "limit": limit},
            )
        else:
            # SQLite: FTS5 with prefix matching
            fts_query = " ".join(f"{word}*" for word in query.split() if word)
            if not fts_query:
                return []
            result = await db.execute(
                text("SELECT track_id FROM tracks_fts WHERE tracks_fts MATCH :query ORDER BY rank LIMIT :limit"),
                {"query": fts_query, "limit": limit},
            )
        return [row[0] for row in result.all()]
    except Exception as e:
        log.debug("FTS search failed for %r: %s", query, e)
        return []
