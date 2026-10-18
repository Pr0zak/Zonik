"""/api/download/batches (DC-21): the web process's batch registry and its cancel.

Route coroutines are called directly.

Run: uv run --with pytest --with pytest-asyncio pytest tests/test_download_batches_api.py
"""
import asyncio

import pytest
from fastapi import HTTPException

import backend.api.download as download
import backend.api.download_batches as api
import backend.services.auto_download as auto

pytestmark = pytest.mark.asyncio

ITEM_KEYS = {"id", "label", "kind", "source", "total", "submitted", "done", "failed", "skipped", "live",
             "pending", "pending_titles", "started_at", "finished_at", "cancelled"}


@pytest.fixture(autouse=True)
def fresh_batches():
    auto._batches.clear()
    yield
    auto._batches.clear()


async def test_get_lists_registered_batches():
    titles = [f"A — Song {i}" for i in range(14)]
    auto._register_batch({"id": "b-1", "label": "Download all", "kind": "bulk"}, "similar", titles)
    out = await api.list_batches()
    assert len(out["items"]) == 1
    item = out["items"][0]
    assert set(item) == ITEM_KEYS
    assert item["id"] == "b-1" and item["label"] == "Download all" and item["kind"] == "bulk"
    assert item["source"] == "similar" and item["total"] == 14 and item["pending"] == 14
    assert item["pending_titles"] == titles[:10]  # capped; the count stays complete
    assert item["cancelled"] is False and item["finished_at"] is None


async def test_running_batches_come_first():
    old = auto._register_batch({"id": "old", "label": "x", "kind": "bulk"}, None, ["A — 1"])
    old.finish()
    auto._register_batch({"id": "new", "label": "y", "kind": "playlist"}, None, ["A — 2"])
    assert [i["id"] for i in (await api.list_batches())["items"]] == ["new", "old"]


async def test_post_cancel_sets_the_event_and_returns_remaining():
    entry = auto._register_batch({"id": "b-2", "label": "Mix", "kind": "playlist"}, "playlist",
                                 ["A — 1", "A — 2", "A — 3"])
    entry.start("A — 1")
    out = await api.cancel_batch("b-2")
    assert out == {"cancelled": True, "remaining": 2}
    assert entry.cancel.is_set() and entry.skipped == 2 and entry.pending_titles == []
    item = (await api.list_batches())["items"][0]
    assert item["cancelled"] is True and item["pending"] == 0 and item["live"] == 1


async def test_post_cancel_unknown_batch_is_404():
    with pytest.raises(HTTPException) as e:
        await api.cancel_batch("nope")
    assert e.value.status_code == 404


async def test_cancel_through_the_route_stops_a_running_import(db_ready, monkeypatch):
    """End to end: a playlist-style run registers, the route cancels it mid-run."""
    monkeypatch.setattr(auto, "_lastfm_configured", lambda: False)  # no length lookup
    gate, started = asyncio.Event(), []

    async def enqueue(artist, track, job_id=None, **_):
        started.append(track)
        await gate.wait()
        return None  # "library already has it": counted as done
    monkeypatch.setattr(download, "enqueue_download", enqueue)

    items = [{"artist": "A", "track": f"T{i}"} for i in range(6)]
    task = asyncio.create_task(auto.download_tracked_many(items, source="playlist", concurrency=2,
                                                          label="Road trip", kind="playlist"))
    for _ in range(300):
        if len(started) == 2:
            break
        await asyncio.sleep(0.01)
    [item] = (await api.list_batches())["items"]
    assert item["pending"] == 4 and item["live"] == 2 and item["label"] == "Road trip"
    assert await api.cancel_batch(item["id"]) == {"cancelled": True, "remaining": 4}
    gate.set()
    await task
    [item] = (await api.list_batches())["items"]
    assert len(started) == 2
    assert (item["done"], item["skipped"], item["live"]) == (2, 4, 0) and item["finished_at"]
