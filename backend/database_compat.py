"""Dialect-aware SQL helpers for SQLite/PostgreSQL compatibility.

Usage:
    from backend.database_compat import date_trunc, extract_hour, json_extract

These return SQLAlchemy constructs that work on both dialects.
"""
from __future__ import annotations

from sqlalchemy import func, text, literal_column


def is_postgres() -> bool:
    from backend.database import _is_postgres
    return _is_postgres()


def date_trunc(unit: str, column):
    """Truncate a datetime column to a time unit (hour, day, week, month).

    SQLite: strftime, PostgreSQL: date_trunc
    """
    if is_postgres():
        return func.date_trunc(unit, column)

    fmt_map = {
        "hour": "%Y-%m-%d %H:00:00",
        "day": "%Y-%m-%d",
        "week": "%Y-%W",
        "month": "%Y-%m",
        "year": "%Y",
    }
    fmt = fmt_map.get(unit, "%Y-%m-%d")
    return func.strftime(fmt, column)


def extract_hour(column):
    """Extract hour from a datetime column.

    SQLite: strftime('%H', col), PostgreSQL: extract(hour from col)
    """
    if is_postgres():
        return func.extract("hour", column)
    return func.cast(func.strftime("%H", column), type_=None)


def duration_seconds(start_col, end_col):
    """Compute duration in seconds between two datetime columns.

    SQLite: julianday diff * 86400, PostgreSQL: EXTRACT(EPOCH FROM diff)
    """
    if is_postgres():
        return func.extract("epoch", end_col - start_col)
    return (func.julianday(end_col) - func.julianday(start_col)) * 86400
