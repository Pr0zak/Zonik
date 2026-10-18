"""GET /api/download/status and /soulseek-stats: the limits, stage counts, pacer
and connection facts the Downloads page reads (DC-12, DC-13).

Run: uv run --with pytest --with pytest-asyncio pytest tests/test_download_status.py
"""
from datetime import datetime

import pytest

import backend.api.download as download
from backend.database import async_session
from backend.models.job import Job
from backend.soulseek.protocol.types import TransferState
from backend.soulseek.transfer import Transfer

pytestmark = pytest.mark.asyncio


@pytest.fixture
def clean_counters():
    download.stage_counts.clear()
    download._job_stage.clear()
    yield
    download.stage_counts.clear()
    download._job_stage.clear()


async def test_limits_follow_the_settings(monkeypatch):
    from backend import config
    cfg = config.get_settings().soulseek
    monkeypatch.setattr(cfg, "max_concurrent_downloads", 2, raising=False)
    monkeypatch.setattr(cfg, "max_concurrent_searches", 5, raising=False)
    monkeypatch.setattr(cfg, "searches_per_minute", 7, raising=False)
    monkeypatch.setattr(cfg, "search_min_interval_s", 9.5, raising=False)
    monkeypatch.setattr(cfg, "transfer_max_minutes", 12, raising=False)
    monkeypatch.setattr(cfg, "parallel_sources", 1, raising=False)
    lim = download.download_limits()
    assert lim["transfer_slots"] == 2 and lim["search_slots"] == 5
    assert lim["searches_per_minute"] == 7 and lim["search_min_interval_s"] == 9.5
    assert lim["transfer_max_minutes"] == 12 and lim["parallel_sources"] == 1
    # Constants from the code, never hard-coded on the page.
    assert lim["peer_busy_wait_s"] == download.PEER_BUSY_WAIT
    assert lim["peer_queue_s"] == 120 and lim["stall_s"] == 60
    assert lim["peer_queue_sweep_s"] == 180 and lim["connected_no_data_s"] == 120
    assert lim["peer_connect_s"] == 20 and lim["search_timeout_s"] == 25
    assert lim["terminal_keep_s"] == 60 and lim["reconnect_wait_s"] == 30
    assert lim["backoff_days"] == [1, 7, 30] and lim["retired_days"] == 365
    assert lim["backoff_slack_h"] == 6 and lim["upgrade_max_scans"] == 3
    # Read per call: a settings change shows at once.
    monkeypatch.setattr(cfg, "max_concurrent_downloads", 3, raising=False)
    assert download.download_limits()["transfer_slots"] == 3


async def test_status_keeps_old_keys_and_adds_new(db_ready, fake_slsk, clean_counters):
    out = await download.download_status()
    assert out["downloads"] == [] and out["uploads"] == [] and out["logged_in"] is True
    for key in ("limits", "stages", "aggregate_speed", "pacer", "soulseek"):
        assert key in out
    assert out["soulseek"]["connected"] is True and out["soulseek"]["username"] == "fake_user"
    assert out["soulseek"]["disconnected_since"] is None and out["soulseek"]["reconnecting"] is False
    assert out["pacer"] == {"waiting": 0, "sent_last_minute": 0, "next_slot_in_s": 0.0}
    assert out["stages"]["live"] == 0 and out["aggregate_speed"] == 0


async def test_stages_combine_counters_and_transfers(db_ready, fake_slsk, clean_counters):
    download._note_stage("j-search", "searching")
    download._note_stage("j-lock", "peer_lock")
    download._note_stage("j-q", "queued_at_peer")  # overridden by the transfer table
    t = Transfer(username="peer", filename="a.flac", job_id="j-q2")
    t.state = TransferState.QUEUED
    fake_slsk.transfers.add(t)
    t2 = Transfer(username="peer2", filename="b.flac", job_id="j-t")
    t2.state = TransferState.TRANSFERRING
    fake_slsk.transfers.add(t2)
    fake_slsk.pacer = {"waiting": 2, "sent_last_minute": 6, "next_slot_in_s": 7.2}

    out = await download.download_status()
    st = out["stages"]
    assert st["queued_at_peer"] == 1 and st["transferring"] == 1 and st["connecting"] == 0
    assert st["searching"] == 1 and st["peer_lock"] == 1 and st["pacer_waiting"] == 2
    assert st["live"] == sum(st[k] for k in download.STAGES) == 4
    assert out["pacer"]["next_slot_in_s"] == 7.2
    assert len(out["downloads"]) == 2


async def test_db_counts_show_rows_after_a_restart(db_ready, fake_slsk, clean_counters):
    async with async_session() as s:
        s.add(Job(id="r1", type="download", status="running", started_at=datetime.utcnow()))
        s.add(Job(id="p1", type="download", status="pending", started_at=datetime.utcnow()))
        s.add(Job(id="c1", type="download", status="completed", started_at=datetime.utcnow()))
        s.add(Job(id="o1", type="scan", status="running", started_at=datetime.utcnow()))
        await s.commit()
    st = (await download.download_status())["stages"]
    assert st["db_running"] == 1 and st["db_pending"] == 1
    assert st["live"] == 0  # the in-memory counters are empty after a restart


async def test_status_without_a_client(db_ready, monkeypatch, clean_counters):
    import backend.soulseek as soulseek
    monkeypatch.setattr(soulseek, "get_client", lambda: None)
    out = await download.download_status()
    assert out["downloads"] == [] and out["logged_in"] is False
    assert out["soulseek"]["connected"] is False and out["stages"]["live"] == 0
    assert out["limits"]["transfer_slots"] >= 1


async def test_soulseek_stats_additions(db_ready, fake_slsk, monkeypatch):
    fake_slsk.reputation.get_summary = lambda: {"tracked_peers": 0, "peers": []}
    import backend.soulseek.shares as shares
    monkeypatch.setattr(shares, "get_share_counts", lambda: (0, 0))
    import backend.soulseek as soulseek
    fake_slsk.uploads = type("U", (), {"totals": {"completed": 0, "failed": 0, "bytes_sent": 0}})()
    fake_slsk.server.disconnected_since = 123.0
    fake_slsk.server.reconnecting = True
    fake_slsk.session_totals = {"completed": 3, "failed": 1, "bytes": 999}
    fake_slsk.pacer["waiting"] = 1
    out = await download.soulseek_stats()
    assert out["disconnected_since"] == 123.0 and out["reconnecting"] is True
    assert out["pacer_waiting"] == 1
    assert out["session"] == {"completed": 3, "failed": 1, "bytes": 999}
    assert "aggregate_speed" in out and "reputation" in out  # existing keys untouched
    monkeypatch.setattr(soulseek, "get_client", lambda: None)
    out = await download.soulseek_stats()
    assert out["session"] == {"completed": 0, "failed": 0, "bytes": 0} and out["reconnecting"] is False
