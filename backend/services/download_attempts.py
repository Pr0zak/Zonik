"""Failed-search memory for automatic downloads.

Every auto source (similar, charts, remixes, recommendations) used to retry the
same unfindable tracks every run. A failure now schedules the next try on an
exponential backoff (1 d, 7 d, 30 d) and then retires the track for a year.
A success forgets the track. Manual downloads from the UI never consult this.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.download_attempt import DownloadAttempt
from backend.services.library_match import norm_artist, norm_title

log = logging.getLogger(__name__)

BACKOFF = [1, 7, 30]  # days to wait after the 1st, 2nd, 3rd failure
RETIRED_DAYS = 365    # after len(BACKOFF)+... failures: effectively give up


def attempt_key(artist: str, track: str) -> str:
    return f"{norm_artist(artist)}::{norm_title(track)}"


def backoff_days(attempts: int) -> int:
    """Days until the next try after `attempts` failures (attempts >= 1)."""
    if attempts <= 0:
        return 0
    if attempts <= len(BACKOFF):
        return BACKOFF[attempts - 1]
    return RETIRED_DAYS


def is_retired(attempts: int) -> bool:
    return attempts > len(BACKOFF)


def next_retry(attempts: int, now: datetime | None = None) -> datetime:
    return (now or datetime.utcnow()) + timedelta(days=backoff_days(attempts))


def reason_for(row: DownloadAttempt, now: datetime | None = None) -> str | None:
    now = now or datetime.utcnow()
    if row.next_retry_at is None or row.next_retry_at <= now:
        return None
    if is_retired(row.attempts or 0):
        return f"retired after {row.attempts} failed attempts"
    return f"backoff until {row.next_retry_at:%Y-%m-%d} ({row.attempts} failed)"


async def in_backoff(db: AsyncSession, artist: str, track: str) -> str | None:
    """Why this track must not be tried yet, or None when it may be."""
    row = await db.get(DownloadAttempt, attempt_key(artist, track))
    return reason_for(row) if row else None


async def keys_in_backoff(db: AsyncSession) -> set[str]:
    rows = await db.execute(
        select(DownloadAttempt.key).where(DownloadAttempt.next_retry_at > datetime.utcnow())
    )
    return {k for (k,) in rows.all()}


async def record_outcome(
    db: AsyncSession, artist: str, track: str, source: str | None,
    ok: bool, error: str | None, job_id: str | None,
) -> None:
    """Success forgets the track; failure bumps attempts and schedules the retry."""
    key = attempt_key(artist, track)
    if ok:
        await db.execute(delete(DownloadAttempt).where(DownloadAttempt.key == key))
        await db.commit()
        return
    now = datetime.utcnow()
    row = await db.get(DownloadAttempt, key)
    if row is None:
        row = DownloadAttempt(key=key, artist=artist, track=track, attempts=0)
        db.add(row)
    row.attempts = (row.attempts or 0) + 1
    row.source = source
    row.last_attempt_at = now
    row.next_retry_at = next_retry(row.attempts, now)
    row.last_error = (error or "")[:500] or None
    row.last_job_id = job_id
    await db.commit()
