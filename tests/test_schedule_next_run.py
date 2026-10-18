"""next_run() / next_download_runs() mirror the worker's scheduling rule
(backend/workers/__init__.py run_scheduled_tasks) and GET /api/schedule
exposes next_run_at + download_source."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend.api.schedule import (
    DOWNLOAD_TASK_SOURCES,
    next_download_runs,
    next_run,
)


def task(name="lastfm_top_tracks", *, enabled=True, interval_hours=24, run_at=None,
         day_of_week=None, last_run_at=None):
    return SimpleNamespace(task_name=name, enabled=enabled, interval_hours=interval_hours,
                           run_at=run_at, day_of_week=day_of_week, last_run_at=last_run_at)


NOW = datetime(2026, 10, 18, 10, 0, 0)  # a Sunday, naive UTC


def test_run_at_later_today():
    t = task(run_at="14:30", last_run_at=NOW - timedelta(hours=30))
    assert next_run(t, NOW) == datetime(2026, 10, 18, 14, 30)


def test_run_at_already_passed_rolls_to_tomorrow():
    t = task(run_at="04:00", last_run_at=NOW - timedelta(hours=30))
    assert next_run(t, NOW) == datetime(2026, 10, 19, 4, 0)


def test_run_at_current_minute_is_now():
    now = datetime(2026, 10, 18, 4, 0, 20)
    t = task(run_at="04:00", last_run_at=None)
    assert next_run(t, now) == now


def test_interval_not_elapsed_waits_for_first_slot_after_interval():
    # Last ran yesterday 04:00 with a 48 h interval → eligible 2026-10-19 04:00,
    # which is itself a slot.
    t = task(interval_hours=48, run_at="04:00", last_run_at=datetime(2026, 10, 17, 4, 0))
    assert next_run(t, NOW) == datetime(2026, 10, 19, 4, 0)
    # Ran a bit late (04:07) → eligible 04:07 on the 19th, so the slot is the 20th.
    t = task(interval_hours=48, run_at="04:00", last_run_at=datetime(2026, 10, 17, 4, 7))
    assert next_run(t, NOW) == datetime(2026, 10, 20, 4, 0)


def test_interval_only_task():
    t = task(run_at=None, interval_hours=6, last_run_at=NOW - timedelta(hours=2))
    assert next_run(t, NOW) == NOW + timedelta(hours=4)
    # overdue → due now
    t = task(run_at=None, interval_hours=6, last_run_at=NOW - timedelta(hours=9))
    assert next_run(t, NOW) == NOW
    # never ran → due now
    assert next_run(task(run_at=None, last_run_at=None), NOW) == NOW


def test_disabled_is_none():
    assert next_run(task(enabled=False, run_at="04:00"), NOW) is None


def test_weekly_day_of_week_is_ignored():
    # Weekly task pinned to Monday (0) that last ran Friday 06:00: the worker
    # ignores day_of_week, so it runs at the first 06:00 after 168 h — next Friday.
    last = datetime(2026, 10, 16, 6, 0)  # Friday
    t = task("upgrade_scan", interval_hours=168, run_at="06:00", day_of_week=0, last_run_at=last)
    assert next_run(t, NOW) == datetime(2026, 10, 23, 6, 0)
    t_none = task("upgrade_scan", interval_hours=168, run_at="06:00", day_of_week=None, last_run_at=last)
    assert next_run(t, NOW) == next_run(t_none, NOW)


def test_unparseable_run_at_is_ignored_like_the_worker():
    t = task(run_at="garbage", interval_hours=6, last_run_at=NOW - timedelta(hours=2))
    assert next_run(t, NOW) == NOW + timedelta(hours=4)


def test_aware_now_is_treated_as_utc():
    t = task(run_at="14:30", last_run_at=None)
    aware = NOW.replace(tzinfo=timezone.utc)
    assert next_run(t, aware) == datetime(2026, 10, 18, 14, 30)


def test_next_download_runs_sorted_and_filtered():
    tasks = [
        task("lastfm_top_tracks", run_at="16:00"),
        task("discover_similar", run_at="12:00"),
        task("upgrade_scan", enabled=False, run_at="11:00"),
        task("library_scan", run_at="10:30"),  # not a download task
        task("remix_discovery", run_at="09:00"),  # tomorrow
    ]
    runs = next_download_runs(tasks, NOW)
    assert [r["task_name"] for r in runs] == ["discover_similar", "lastfm_top_tracks", "remix_discovery"]
    assert runs[0] == {
        "task_name": "discover_similar",
        "label": "Similar Track Discovery",
        "source": "similar",
        "next_run_at": "2026-10-18T12:00:00",
    }
    assert runs[2]["next_run_at"] == "2026-10-19T09:00:00"


def test_download_task_sources():
    assert DOWNLOAD_TASK_SOURCES == {
        "lastfm_top_tracks": "discovery",
        "discover_similar": "similar",
        "remix_discovery": "remix",
        "recommendation_refresh": "recommendation",
        "upgrade_scan": "upgrade",
    }


@pytest.mark.asyncio
async def test_list_schedule_adds_fields(db_ready):
    from backend.api.schedule import list_schedule
    from backend.database import async_session
    async with async_session() as db:
        items = await list_schedule(db=db)
    by_name = {i["task_name"]: i for i in items}
    assert by_name["upgrade_scan"]["download_source"] == "upgrade"
    assert by_name["library_scan"]["download_source"] is None
    # defaults are disabled
    assert all("next_run_at" in i for i in items)
    assert by_name["library_scan"]["next_run_at"] is None
