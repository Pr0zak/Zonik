"""_do_download_inner and poll_transfer against a fake Soulseek client and a real
(temporary) SQLite database.

Run: uv run --with pytest --with pytest-asyncio pytest tests/test_download_flow.py
"""
import asyncio
import json
from datetime import datetime

import pytest
from sqlalchemy import select

import backend.api.download as download
from backend.database import async_session
from backend.models.job import Job
from backend.soulseek.protocol.types import TransferState
from fake_soulseek import result

pytestmark = pytest.mark.asyncio

ARTIST, TRACK = "Test Artist", "Test Song"


def fname(n: int = 1) -> str:
    return f"Music\\{ARTIST}\\0{n} - {TRACK}.flac"


@pytest.fixture
def imported(monkeypatch):
    """Stub the importer (it moves files into /music): every file becomes track-1."""
    calls = []

    async def fake_import(sess, path, artist_hint=None, target_track_id=None, reasons=None, existing_ids=None):
        calls.append(path)
        return "track-1"

    import backend.services.scanner as scanner
    monkeypatch.setattr(scanner, "import_downloaded_file", fake_import)
    return calls


@pytest.fixture
def recorder(fake_slsk, monkeypatch):
    """Record every job_update the download code sends (fake_slsk silences them)."""
    sent: list[dict] = []

    async def record(payload):
        sent.append(payload)
    monkeypatch.setattr(download, "broadcast_job_update", record)
    return sent


def log_kinds(row) -> list[str]:
    return [e["k"] for e in json.loads(row.log)]


def stage_sequence(sent: list[dict]) -> list[str]:
    """The distinct stages in the order the broadcasts carried them."""
    seq: list[str] = []
    for m in sent:
        st = m.get("stage")
        if st and (not seq or seq[-1] != st):
            seq.append(st)
    return seq


async def run_job(job_id="job-1"):
    """Write a running job row and run _do_download_inner on it; return the saved row."""
    async with async_session() as s:
        job = Job(id=job_id, type="download", card="dl:discovery", status="running",
                  started_at=datetime.utcnow(),
                  tracks=json.dumps([{"artist": ARTIST, "track": TRACK, "status": "pending"}]))
        s.add(job)
        await s.commit()
        s.expunge(job)
    req = download.DownloadRequest(artist=ARTIST, track=TRACK, source="discovery")
    await download._do_download_inner(None, job, job_id, f"{ARTIST} — {TRACK}", req)
    async with async_session() as s:
        return (await s.execute(select(Job).where(Job.id == job_id))).scalar_one()


# --- _do_download_inner (sequential, parallel_sources = 1) --------------------

async def test_success_imports_and_completes(db_ready, fake_slsk, imported, recorder):
    fake_slsk.results = [result("alpha", fname())]
    row = await run_job()
    assert row.status == "completed"
    res = json.loads(row.result)
    assert res["track_id"] == "track-1" and res["username"] == "alpha"
    assert len(imported) == 1
    assert fake_slsk.transfers.discarded == ["job-1"]  # staging folder dropped
    assert fake_slsk.reputation.failures == []

    # Stages, in order, on the job_update stream.
    seq = stage_sequence(recorder)
    assert seq == ["searching", "peer_lock", "connecting", "importing"]
    short = fname().rsplit("\\", 1)[-1]
    desc = f"{ARTIST} — {TRACK}"
    # Description strings are today's, byte for byte.
    assert [m["description"] for m in recorder] == [
        desc, f"Queued for slot: {desc} — {short}", f"{desc} — {short} (attempt 1/1)",
        f"{desc} — {short} (attempt 1/1)", desc]
    live = recorder[1]
    assert live["card"] == "dl:discovery" and live["attempt"] == 1 and live["of"] == 1
    assert live["username"] == "alpha" and live["stage_since"]
    final = recorder[-1]
    assert final["status"] == "completed" and final["progress"] == 1 and final["total"] == 1
    assert final["stage"] == "importing" and final["card"] == "dl:discovery"
    assert final["track_id"] == "track-1"

    # Timeline in Job.log; the row keeps the file size as progress/total.
    kinds = log_kinds(row)
    assert kinds[0] in ("submitted", "search_slot") and kinds[-1] == "done"
    assert kinds == ["search_slot", "attempt", "connecting", "importing", "done"]
    done = json.loads(row.log)[-1]
    assert done["track_id"] == "track-1" and done["file_size"] == 1000 and done["t"]
    assert row.progress == row.total == 1000
    t0 = json.loads(row.tracks)[0]
    assert t0["status"] == "downloaded" and t0["stage"] == "importing"
    assert t0["attempt"] == 1 and t0["of"] == 1 and t0["track_id"] == "track-1"
    assert "search" not in t0
    # The job is out of the in-memory stage counters once it ended.
    assert "job-1" not in download._job_stage and not download.stage_counts
    assert "job-1" not in download._timelines


async def test_falls_back_to_next_candidate_after_failure(db_ready, fake_slsk, imported):
    fake_slsk.results = [result("alpha", fname(1), speed=2_000_000), result("beta", fname(2), speed=600_000)]
    fake_slsk.behaviour = {"alpha": "fail"}
    row = await run_job()
    assert fake_slsk.downloads == ["alpha", "beta"]
    assert row.status == "completed"
    assert json.loads(row.result)["username"] == "beta"


async def test_all_sources_failing_fails_the_job(db_ready, fake_slsk, imported):
    fake_slsk.results = [result("alpha", fname(1)), result("beta", fname(2), speed=600_000)]
    fake_slsk.behaviour = {"alpha": "fail", "beta": "fail"}
    row = await run_job()
    assert row.status == "failed"
    assert json.loads(row.result)["message"] == "All 2 sources failed"
    assert imported == []
    kinds = log_kinds(row)
    assert kinds[-1] == "failed" and kinds.count("peer_failed") == 2
    end = json.loads(row.log)[-1]
    assert end["error"].startswith("All 2 sources failed") and end["class"] == "peer"
    t0 = json.loads(row.tracks)[0]
    assert t0["status"] == "failed" and t0["error"] == "Denied" and t0["attempt"] == 2
    assert row.progress == 0  # only a completed row carries the file size


async def test_cancel_during_transfer(db_ready, fake_slsk, imported):
    fake_slsk.results = [result("alpha", fname())]
    fake_slsk.behaviour = {"alpha": "queue"}

    async def cancel_soon():
        for _ in range(500):  # once the transfer is queued with the peer
            if fake_slsk.transfers.table:
                break
            await asyncio.sleep(0.01)
        download.cancelled_jobs.add("job-1")

    canceller = asyncio.create_task(cancel_soon())
    row = await run_job()
    await canceller
    assert row.status == "failed"
    assert json.loads(row.result)["error"] == "Cancelled by user"
    assert fake_slsk.transfers.aborted == [("alpha", "Cancelled by user", False)]  # peer not blamed
    assert "job-1" not in download.cancelled_jobs  # forgotten once the job ended
    assert log_kinds(row)[-1] == "cancelled"
    assert json.loads(row.tracks)[0]["status"] == "failed"


async def test_busy_peer_is_deferred_behind_other_sources(db_ready, fake_slsk, imported):
    fake_slsk.results = [result("alpha", fname(1), speed=2_000_000), result("beta", fname(2), speed=600_000)]
    busy = fake_slsk.slot("alpha")
    await busy.acquire()  # another job is downloading from alpha
    try:
        row = await run_job()
    finally:
        busy.release()
    assert fake_slsk.downloads == ["beta"]  # alpha skipped, not waited out
    assert row.status == "completed" and json.loads(row.result)["username"] == "beta"


async def test_unreachable_peer_is_blamed_only_while_logged_in(db_ready, fake_slsk, imported):
    fake_slsk.results = [result("alpha", fname(1)), result("beta", fname(2), speed=600_000)]
    fake_slsk.behaviour = {"alpha": "unreachable"}
    row = await run_job("job-1")
    assert row.status == "completed"
    assert fake_slsk.reputation.failures == ["alpha"]


async def test_unreachable_peer_not_blamed_when_our_link_is_down(db_ready, fake_slsk, imported, monkeypatch):
    fake_slsk.results = [result("alpha", fname(1)), result("beta", fname(2), speed=600_000)]
    fake_slsk.behaviour = {"alpha": "unreachable"}
    real_download = fake_slsk.download

    async def drop_link_then_download(username, filename, job_id=None):
        if username == "alpha":
            fake_slsk.logged_in = False  # the server link drops as we try alpha
        return await real_download(username, filename, job_id=job_id)

    monkeypatch.setattr(fake_slsk, "download", drop_link_then_download)
    row = await run_job("job-1")
    assert fake_slsk.downloads == ["alpha", "beta"]
    assert row.status == "completed"
    assert fake_slsk.reputation.failures == []


# --- poll_transfer ------------------------------------------------------------

async def started(client, how, username="peer"):
    client.behaviour[username] = how
    return await client.download(username, fname(), job_id="job-p")


async def test_poll_completion(fake_slsk):
    t = await started(fake_slsk, "complete")
    status, path, err = await download.poll_transfer(fake_slsk, t, "job-p", queue_timeout=1, stall_timeout=1)
    assert (status, err) == ("completed", None) and path == t.save_path


async def test_poll_stall(fake_slsk):
    t = await started(fake_slsk, "stall")
    status, path, err = await download.poll_transfer(fake_slsk, t, "job-p", queue_timeout=1, stall_timeout=0.05)
    assert status == "failed" and "stalled" in err and path is None
    assert fake_slsk.transfers.aborted == [("peer", "Stalled (no data)", True)]


async def test_poll_queue_timeout(fake_slsk):
    t = await started(fake_slsk, "queue")
    status, _, err = await download.poll_transfer(fake_slsk, t, "job-p", queue_timeout=0.05, stall_timeout=1)
    assert status == "failed" and err == "Peer did not respond in time"
    assert t.state == TransferState.FAILED


async def test_poll_cancel(fake_slsk):
    t = await started(fake_slsk, "queue")
    download.cancelled_jobs.add("job-p")
    status, _, err = await download.poll_transfer(fake_slsk, t, "job-p", queue_timeout=1, stall_timeout=1)
    assert (status, err) == ("cancelled", "Cancelled by user")
    assert fake_slsk.transfers.aborted == [("peer", "Cancelled by user", False)]


async def test_poll_peer_denial(fake_slsk):
    t = await started(fake_slsk, "fail")
    status, _, err = await download.poll_transfer(fake_slsk, t, "job-p", queue_timeout=1, stall_timeout=1)
    assert (status, err) == ("failed", "Denied")


# --- duration gate: soft (outside length) vs strict (library's own copy) ----------

def dur_result(username, seconds, speed=2_000_000):
    from backend.soulseek.protocol.types import FileAttribute, FileInfo, SearchResult
    return SearchResult(username=username, token="t", slots_free=True, avg_speed=speed, files=[
        FileInfo(filename=fname(), size=40 * 1024 * 1024, attrs={FileAttribute.DURATION: seconds})])


async def test_soft_duration_scores_but_never_rejects():
    from backend.soulseek.search import pick_best_results_native
    results = [dur_result("far", 260, speed=2_000_000), dur_result("near", 201, speed=600_000)]
    soft = await pick_best_results_native(results, ARTIST, TRACK, target_duration=200, strict_duration=False)
    assert [c["username"] for c in soft] == ["near", "far"]  # match wins, the miss stays a candidate
    strict = await pick_best_results_native(results, ARTIST, TRACK, target_duration=200, strict_duration=True)
    assert [c["username"] for c in strict] == ["near"]


async def test_lastfm_length_is_soft_in_a_download(db_ready, fake_slsk, imported):
    fake_slsk.results = [dur_result("alpha", 260)]  # Last.fm lists another version's length
    async with async_session() as s:
        s.add(Job(id="job-s", type="download", status="running", started_at=datetime.utcnow()))
        await s.commit()
        job = await s.get(Job, "job-s")
        s.expunge(job)
    req = download.DownloadRequest(artist=ARTIST, track=TRACK, source="similar", expected_duration=200)
    await download._do_download_inner(None, job, "job-s", "d", req)
    assert fake_slsk.downloads == ["alpha"] and job.status == "completed"
    # The same length from the library's own copy is strict: no candidate left.
    req = download.DownloadRequest(artist=ARTIST, track=TRACK, expected_duration=200, strict_duration=True)
    job.status = "running"
    await download._do_download_inner(None, job, "job-s", "d", req)
    assert fake_slsk.downloads == ["alpha"] and job.status == "failed"


# --- stage writer, timeline, row creation, WS replay --------------------------

async def test_track_doc_keeps_sticky_keys_and_status_vocabulary():
    req = download.DownloadRequest(artist="A", track="T")
    prev = {"artist": "A", "track": "T", "status": "queued", "stage": "searching", "stage_since": "x",
            "attempt": 2, "of": 4, "username": "u", "search": {"query_index": 1}, "sources": 3}
    doc = download._track_doc(req, "downloading", prev=prev, stage="connecting", username=None)
    assert doc["status"] == "downloading" and doc["attempt"] == 2 and doc["of"] == 4
    assert "username" not in doc  # None removes a key
    assert "search" not in doc  # search only lives while searching
    assert "sources" not in doc  # not sticky
    with pytest.raises(ValueError):
        download._track_doc(req, "searching")


async def test_timeline_cap_keeps_first_event(db_ready):
    job = Job(id="job-cap", type="download", status="running",
              log=json.dumps([{"t": "t0", "k": "submitted", "card": "dl", "source": None}]))
    for i in range(download.TIMELINE_CAP + 50):
        download._log_event(job, "job-cap", "peer_failed", user=f"u{i}", error="x")
    tl = json.loads(job.log)
    assert len(tl) == download.TIMELINE_CAP
    assert tl[0]["k"] == "submitted" and tl[-1]["user"] == f"u{download.TIMELINE_CAP + 49}"
    download._timelines.pop("job-cap", None)


async def test_enqueue_writes_submitted_and_counts_stages(db_ready, fake_slsk, imported, recorder):
    fake_slsk.results = [result("alpha", fname())]
    jid = await download.enqueue_download(ARTIST, TRACK, job_id="job-e", source="playlist")
    assert jid == "job-e"
    async with async_session() as s:
        row = await s.get(Job, "job-e")
    assert row.status == "completed"
    assert log_kinds(row)[:2] == ["submitted", "search_slot"] and log_kinds(row)[-1] == "done"
    sub = json.loads(row.log)[0]
    assert sub["card"] == "dl:playlist" and sub["source"] == "playlist"
    first = recorder[0]
    assert first["status"] == "running" and first["description"] == f"{ARTIST} — {TRACK}"
    assert first["stage"] == "searching" and first["card"] == "dl:playlist"
    assert not download.stage_counts and "job-e" not in download._job_stage


async def test_stage_counts_follow_live_jobs(db_ready, fake_slsk, imported, recorder):
    fake_slsk.results = [result("alpha", fname())]
    fake_slsk.behaviour = {"alpha": "queue"}
    task = asyncio.create_task(run_job("job-q"))
    for _ in range(500):
        if any(m.get("stage") == "connecting" for m in recorder):  # sent after the save
            break
        await asyncio.sleep(0.01)
    assert download.stage_counts["connecting"] == 1
    assert sum(download.stage_counts.values()) == 1
    async with async_session() as s:  # the live stage is on the row too
        live = await s.get(Job, "job-q")
    assert json.loads(live.tracks)[0]["stage"] == "connecting"
    assert json.loads(live.log)[-1]["k"] == "connecting"
    assert live.result is None  # never written while running
    download.cancelled_jobs.add("job-q")
    await task
    assert not download.stage_counts


async def test_ws_replay_carries_description_card_and_stage(db_ready):
    from backend.api import websocket as ws
    tracks = json.dumps([{"artist": "A", "track": "T", "status": "queued",
                          "stage": "queue_search", "stage_since": "2026-10-18T07:00:00"}])
    out = ws._download_replay_fields(tracks)
    assert out == {"description": "A — T", "stage": "queue_search", "stage_since": "2026-10-18T07:00:00"}
    assert ws._download_replay_fields(None) == {"stage": None, "stage_since": None}
    assert ws._download_replay_fields("not json") == {"stage": None, "stage_since": None}
