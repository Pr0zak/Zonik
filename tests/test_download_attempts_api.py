"""/api/download/attempts (DC-14): the retry ledger list, the quiet-state summary
(next download runs + rows coming due) and run-now.

Route coroutines are called directly inside `async with async_session() as db`.

Run: uv run --with pytest --with pytest-asyncio pytest tests/test_download_attempts_api.py
"""
from datetime import datetime, timedelta

import pytest
from fastapi import BackgroundTasks, HTTPException

import backend.api.download_attempts as api
import backend.services.auto_download as auto
from backend.database import async_session
from backend.models.download_attempt import DownloadAttempt
from backend.models.schedule import ScheduleTask
from backend.services.download_attempts import attempt_key, ledger_by_keys, row_to_dict

pytestmark = pytest.mark.asyncio

NOW = datetime.utcnow()
ITEM_KEYS = {"key", "artist", "track", "source", "attempts", "last_attempt_at", "next_retry_at",
             "last_error", "last_job_id", "retired", "reason"}


async def seed_ledger():
    """Overdue (due now), due tomorrow, retired (attempts=4, a year out)."""
    rows = [
        ("Overdue Artist", "Late Song", "similar", 1, NOW - timedelta(hours=3)),
        ("Tomorrow Artist", "Soon Song", "discovery", 2, NOW + timedelta(days=1)),
        ("Retired Artist", "Gone Song", "remix", 4, NOW + timedelta(days=359)),
    ]
    async with async_session() as s:
        for artist, track, source, n, nxt in rows:
            s.add(DownloadAttempt(
                key=attempt_key(artist, track), artist=artist, track=track, source=source,
                attempts=n, last_attempt_at=NOW - timedelta(days=1), next_retry_at=nxt,
                last_error="No results for x", last_job_id=f"job-{n}",
            ))
        await s.commit()


async def seed_schedule():
    async with async_session() as s:
        # enabled, never ran → due now (no run_at)
        s.add(ScheduleTask(task_name="discover_similar", enabled=True, interval_hours=48))
        # enabled, ran recently → next run after the interval
        s.add(ScheduleTask(task_name="lastfm_top_tracks", enabled=True, interval_hours=24,
                           last_run_at=NOW - timedelta(hours=1)))
        # disabled download task and an enabled non-download task: both left out
        s.add(ScheduleTask(task_name="remix_discovery", enabled=False, interval_hours=24))
        s.add(ScheduleTask(task_name="library_scan", enabled=True, interval_hours=24))
        await s.commit()


async def test_list_counts_shape_and_retired(db_ready):
    await seed_ledger()
    async with async_session() as db:
        resp = await api.list_attempts(due_before=None, limit=200, db=db)
    assert resp["count_total"] == 3
    assert resp["count_due"] == 1
    items = resp["items"]
    assert [i["artist"] for i in items] == ["Overdue Artist", "Tomorrow Artist", "Retired Artist"]
    assert all(set(i) == ITEM_KEYS for i in items)
    overdue, tomorrow, retired = items
    assert overdue["key"] == attempt_key("Overdue Artist", "Late Song")
    assert overdue["reason"] is None and overdue["retired"] is False
    assert tomorrow["retired"] is False and tomorrow["reason"].startswith("backoff until")
    assert retired["retired"] is True and retired["reason"].startswith("retired after 4")
    assert isinstance(overdue["next_retry_at"], str) and overdue["last_job_id"] == "job-1"


async def test_list_due_before_filters_items(db_ready):
    await seed_ledger()
    in_two_days = (NOW + timedelta(days=2)).isoformat() + "Z"
    async with async_session() as db:
        resp = await api.list_attempts(due_before=in_two_days, limit=200, db=db)
        capped = await api.list_attempts(due_before=None, limit=1, db=db)
    assert resp["count_total"] == 3 and resp["count_due"] == 2
    assert [i["artist"] for i in resp["items"]] == ["Overdue Artist", "Tomorrow Artist"]
    assert len(capped["items"]) == 1 and capped["count_total"] == 3


async def test_bad_due_before_is_400(db_ready):
    async with async_session() as db:
        with pytest.raises(HTTPException) as e:
            await api.list_attempts(due_before="not-a-date", limit=200, db=db)
    assert e.value.status_code == 400


async def test_summary_next_runs_and_due_counts(db_ready):
    await seed_ledger()
    await seed_schedule()
    in_two_days = (NOW + timedelta(days=2)).isoformat()
    async with async_session() as db:
        resp = await api.attempts_summary(due_before=in_two_days, db=db)
        plain = await api.attempts_summary(due_before=None, db=db)
    assert resp["due_now"] == 1 and resp["due_before"] == 2 and resp["total"] == 3
    runs = resp["next_runs"]
    assert [r["task_name"] for r in runs] == ["discover_similar", "lastfm_top_tracks"]
    assert [r["source"] for r in runs] == ["similar", "discovery"]
    assert set(runs[0]) == {"task_name", "label", "source", "next_run_at"}
    assert runs[0]["next_run_at"] <= runs[1]["next_run_at"]
    # The soonest run (discover_similar) is due now: only the overdue row is due by then.
    assert resp["due_by_next_run"] == 1
    assert plain["due_before"] == plain["due_now"] == 1


async def test_summary_without_download_tasks(db_ready):
    await seed_ledger()
    async with async_session() as db:
        resp = await api.attempts_summary(due_before=None, db=db)
    assert resp["next_runs"] == [] and resp["due_by_next_run"] is None


async def test_run_queues_only_due_rows_without_backoff(db_ready, monkeypatch):
    await seed_ledger()
    calls = []

    async def recorder(items, **kw):
        calls.append((items, kw))
        return []
    monkeypatch.setattr(auto, "download_tracked_many", recorder)

    bt = BackgroundTasks()
    async with async_session() as db:
        resp = await api.run_due(bt, due_before=None, db=db)
    await bt()
    assert resp == {"queued": 1}
    assert calls == [([{"artist": "Overdue Artist", "track": "Late Song", "source": "similar"}],
                      {"skip_in_backoff": False})]


async def test_run_with_due_before_and_nothing_due(db_ready, monkeypatch):
    await seed_ledger()
    calls = []

    async def recorder(items, **kw):
        calls.append((items, kw))
        return []
    monkeypatch.setattr(auto, "download_tracked_many", recorder)

    bt = BackgroundTasks()
    async with async_session() as db:
        resp = await api.run_due(bt, due_before=(NOW + timedelta(days=2)).isoformat(), db=db)
    await bt()
    assert resp == {"queued": 2}
    assert [i["artist"] for i in calls[0][0]] == ["Overdue Artist", "Tomorrow Artist"]

    calls.clear()
    bt = BackgroundTasks()
    async with async_session() as db:
        resp = await api.run_due(bt, due_before=(NOW - timedelta(days=1)).isoformat(), db=db)
    await bt()
    assert resp == {"queued": 0} and calls == []


async def test_service_helpers(db_ready):
    await seed_ledger()
    k = attempt_key("Retired Artist", "Gone Song")
    async with async_session() as db:
        found = await ledger_by_keys(db, [k, "nobody::nothing", k, ""])
    assert set(found) == {k}
    d = row_to_dict(found[k], NOW)
    assert d["retired"] is True and d["attempts"] == 4


async def test_router_is_mounted():
    from backend.main import app
    paths = {getattr(r, "path", None) for r in app.routes}
    assert {"/api/download/attempts", "/api/download/attempts/summary",
            "/api/download/attempts/run"} <= paths
