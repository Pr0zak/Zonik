"""The tracked automatic-download path (backend/services/auto_download.py), the
web's wait=false internal-run, and the scheduler's polling batch, on a real
(temporary) SQLite database.

Run: uv run --with pytest --with pytest-asyncio pytest tests/test_auto_download.py
"""
import asyncio
import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

import backend.api.download as download
import backend.services.auto_download as auto
from backend.database import async_session
from backend.models.download_attempt import DownloadAttempt
from backend.models.job import Job
from backend.services.download_attempts import attempt_key
from fake_soulseek import result

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def fresh_duration_cache():
    auto._duration_cache.clear()
    yield
    auto._duration_cache.clear()


@pytest.fixture
def no_lastfm(monkeypatch):
    """Last.fm configured but answering nothing (records which tracks were asked)."""
    return stub_lastfm(monkeypatch, lambda track: None)


def stub_lastfm(monkeypatch, answer, delay=0.0):
    import backend.services.lastfm as lastfm
    calls = []

    async def api(method, params):
        calls.append(params["track"])
        if delay:
            await asyncio.sleep(delay)
        return answer(params["track"])
    monkeypatch.setattr(lastfm, "lastfm_api", api)
    monkeypatch.setattr(auto, "_lastfm_configured", lambda: True)
    return calls


async def write_job(job_id, status, result_payload=None):
    async with async_session() as s:
        s.add(Job(id=job_id, type="download", status=status, started_at=datetime.utcnow(),
                  result=json.dumps(result_payload) if result_payload is not None else None))
        await s.commit()


async def attempt_row(artist, track):
    async with async_session() as s:
        return await s.get(DownloadAttempt, attempt_key(artist, track))


@pytest.fixture
def fake_enqueue(monkeypatch):
    """Replace enqueue_download: writes a job row with the scripted outcome."""
    calls = []
    script: dict[str, tuple[str, dict | None]] = {}

    async def enqueue(artist, track, job_id=None, source=None, target_track_id=None, *,
                      album=None, expected_duration=None, wait=True, **kwargs):
        calls.append({"artist": artist, "track": track, "album": album, "job_id": job_id, "source": source,
                      "expected_duration": expected_duration, "wait": wait})
        status, payload = script.get(track, ("completed", {"track_id": "t1"}))
        await write_job(job_id, status, payload)
        return job_id
    monkeypatch.setattr(download, "enqueue_download", enqueue)
    enqueue.calls = calls
    enqueue.script = script
    return enqueue


# --- download_tracked -----------------------------------------------------------

async def test_backoff_skips_without_downloading(db_ready, fake_enqueue, no_lastfm):
    async with async_session() as s:
        s.add(DownloadAttempt(key=attempt_key("A", "Song"), artist="A", track="Song", attempts=1,
                              next_retry_at=datetime.utcnow() + timedelta(days=1)))
        await s.commit()
    out = await auto.download_tracked("A", "Song", source="similar")
    assert out["skipped"] and "backoff" in out["skipped"] and out["ok"] is None
    assert fake_enqueue.calls == []
    # Retries ask for it explicitly: no skip.
    out = await auto.download_tracked("A", "Song", source="similar", skip_in_backoff=False)
    assert out["ok"] is True and len(fake_enqueue.calls) == 1


async def test_failure_is_recorded(db_ready, fake_enqueue, no_lastfm):
    fake_enqueue.script["Song"] = ("failed", {"message": "No results for A - Song"})
    out = await auto.download_tracked("A", "Song", source="discovery")
    assert out["ok"] is False and "No results" in out["error"]
    row = await attempt_row("A", "Song")
    assert row.attempts == 1 and row.source == "discovery" and row.last_job_id == out["job_id"]
    assert row.next_retry_at > datetime.utcnow()


async def test_success_forgets_the_track(db_ready, fake_enqueue, no_lastfm):
    async with async_session() as s:
        s.add(DownloadAttempt(key=attempt_key("A", "Song"), artist="A", track="Song", attempts=2,
                              next_retry_at=datetime.utcnow() - timedelta(hours=1)))
        await s.commit()
    out = await auto.download_tracked("A", "Song", source="similar")
    assert out["ok"] is True and out["error"] is None
    assert await attempt_row("A", "Song") is None


async def test_infra_failure_records_nothing(db_ready, fake_enqueue, no_lastfm):
    fake_enqueue.script["Song"] = ("failed", {"error": "Soulseek server not connected — try again later"})
    out = await auto.download_tracked("A", "Song", source="similar")
    assert out["ok"] is None
    assert await attempt_row("A", "Song") is None


async def test_upgrade_source_neither_checks_nor_feeds_backoff(db_ready, fake_enqueue, no_lastfm):
    async with async_session() as s:
        s.add(DownloadAttempt(key=attempt_key("A", "Song"), artist="A", track="Song", attempts=1,
                              next_retry_at=datetime.utcnow() + timedelta(days=1)))
        await s.commit()
    fake_enqueue.script["Song"] = ("failed", {"message": "No source better than the current mp3"})
    out = await auto.download_tracked("A", "Song", source="upgrade", target_track_id="trk")
    assert out["ok"] is False and len(fake_enqueue.calls) == 1
    assert (await attempt_row("A", "Song")).attempts == 1  # unchanged
    assert no_lastfm == []  # target track's own duration is used, no lookup


async def test_duration_lookup_from_lastfm(db_ready, fake_enqueue, monkeypatch):
    calls = stub_lastfm(monkeypatch, lambda t: {"track": {"duration": "215400" if t == "Song" else "0"}})

    await auto.download_tracked("A", "Song", source="similar")
    await auto.download_tracked("A", "Song", source="similar")  # cached
    await auto.download_tracked("A", "Other", source="similar")  # 0 → no gate
    await auto.download_tracked("A", "Given", source="similar", expected_duration=100)
    assert [c["expected_duration"] for c in fake_enqueue.calls] == [215, 215, None, 100]
    assert calls == ["Song", "Other"]


async def test_duration_lookup_failure_is_tolerated_and_not_cached(db_ready, fake_enqueue, monkeypatch):
    calls = stub_lastfm(monkeypatch, lambda t: None)  # 429 / non-200 / error: lastfm_api gives None
    out = await auto.download_tracked("A", "Song", source="similar")
    assert out["ok"] is True and fake_enqueue.calls[0]["expected_duration"] is None
    await auto.download_tracked("A", "Song", source="similar")
    assert calls == ["Song", "Song"]  # a failure is asked again, not cached as "no length"


async def test_duration_lookup_times_out(db_ready, fake_enqueue, monkeypatch):
    monkeypatch.setattr(auto, "DURATION_LOOKUP_TIMEOUT", 0.05)
    stub_lastfm(monkeypatch, lambda t: {"track": {"duration": "200000"}}, delay=5)
    out = await auto.download_tracked("A", "Song", source="similar")
    assert out["ok"] is True and fake_enqueue.calls[0]["expected_duration"] is None
    assert auto._duration_cache == {}


async def test_no_length_lookup_for_manual_or_upgrade(db_ready, fake_enqueue, no_lastfm):
    await auto.download_tracked("A", "Song", source=None)
    await auto.download_tracked("A", "Song2", source="upgrade")
    await auto.download_tracked("A", "Song3", source="manual")
    assert no_lastfm == []
    assert await attempt_row("A", "Song") is None  # untracked: nothing recorded


async def test_deduped_submission_is_not_recorded_twice(db_ready, monkeypatch, no_lastfm):
    """enqueue dedups onto a job another caller owns: its outcome is that caller's to record."""
    await write_job("owner-job", "failed", {"message": "No results for A - Song"})

    async def enqueue(artist, track, job_id=None, **_):
        return "owner-job"
    monkeypatch.setattr(download, "enqueue_download", enqueue)
    out = await auto.download_tracked("A", "Song", source="similar")
    assert out["ok"] is False and out["job_id"] == "owner-job"
    assert await attempt_row("A", "Song") is None


async def test_enqueue_error_wins_over_missing_row(db_ready, monkeypatch, no_lastfm):
    async def enqueue(*a, **k):
        raise RuntimeError("database is locked")
    monkeypatch.setattr(download, "enqueue_download", enqueue)
    out = await auto.download_tracked("A", "Song", source="similar")
    assert out["ok"] is None and out["error"].startswith("Internal error: database is locked")
    assert await attempt_row("A", "Song") is None


async def test_reaped_and_internal_failures_count_as_unknown(db_ready):
    await write_job("reaped", "failed")  # boot reaper, old schema: no result
    assert (await auto.download_job_outcome("reaped"))[0] is None
    await write_job("restart", "failed", {"error": "Interrupted by restart"})
    assert (await auto.download_job_outcome("restart"))[0] is None
    await write_job("internal", "failed", {"error": "Internal error: database is locked"})
    assert (await auto.download_job_outcome("internal"))[0] is None
    assert await auto.download_job_outcome("nope") == (None, "download job not found")


async def test_worker_reaper_writes_an_unknown_reason(db_ready):
    from backend.workers import reap_stuck_jobs
    async with async_session() as s:
        s.add(Job(id="stuck", type="download", status="running",
                  started_at=datetime.utcnow() - timedelta(hours=3)))
        await s.commit()
    await reap_stuck_jobs()
    async with async_session() as s:
        row = await s.get(Job, "stuck")
    assert row.status == "failed" and "Interrupted by restart" in row.result
    assert (await auto.download_job_outcome("stuck"))[0] is None


async def test_download_tracked_many_dedupes_and_bounds(db_ready, fake_enqueue, no_lastfm):
    items = [{"artist": "A", "track": "Song"}, {"artist": "a", "track": "song"},
             {"artist": "B", "track": "Two"}, {"artist": "", "track": "x"}]
    outs = await auto.download_tracked_many(items, source="playlist", concurrency=2)
    assert sorted(o["track"] for o in outs) == ["Song", "Two"]
    assert all(c["source"] == "playlist" for c in fake_enqueue.calls)


# --- blacklist (DC-22) ------------------------------------------------------------

async def blacklist(artist, track=None, reason=None):
    import uuid
    from backend.models.blacklist import DownloadBlacklist
    async with async_session() as s:
        s.add(DownloadBlacklist(id=str(uuid.uuid4()), artist=artist, track=track, reason=reason))
        await s.commit()


async def test_submit_tracked_skips_blacklisted(db_ready, fake_enqueue, no_lastfm):
    async with async_session() as s:
        s.add(DownloadAttempt(key=attempt_key("A", "Song"), artist="A", track="Song", attempts=1,
                              next_retry_at=datetime.utcnow() - timedelta(hours=1)))
        await s.commit()
    await blacklist("A", "Song", "Stopped from Downloads")
    await blacklist("Banned")  # artist-level, no reason
    out = await auto.submit_tracked("A", "song", source="similar")
    assert out == {"job_id": None, "skipped": "blacklisted: Stopped from Downloads", "error": None,
                   "deduped": False, "blacklisted": True}
    out = await auto.submit_tracked("banned", "Anything", source=None, skip_in_backoff=False)
    assert out["skipped"] == "blacklisted: Artist blacklisted" and out["blacklisted"] is True
    assert fake_enqueue.calls == []
    assert no_lastfm == []  # refused before the length lookup
    assert (await attempt_row("A", "Song")).attempts == 1  # ledger untouched
    # Another track by the same artist is not affected by a track-level entry.
    out = await auto.submit_tracked("A", "Other", source="similar")
    assert out["job_id"] and not out["skipped"]


async def test_download_tracked_many_reports_blacklist_skip(db_ready, fake_enqueue, no_lastfm):
    await blacklist("A", "Song", "nope")
    outs = await auto.download_tracked_many([{"artist": "A", "track": "Song"}, {"artist": "B", "track": "Two"}],
                                            source="playlist")
    by_track = {o["track"]: o for o in outs}
    assert by_track["Song"]["skipped"] == "blacklisted: nope" and by_track["Song"]["ok"] is None
    assert by_track["Two"]["ok"] is True
    assert [c["track"] for c in fake_enqueue.calls] == ["Two"]
    assert await attempt_row("A", "Song") is None  # a skip is never recorded


async def test_blacklisted_track_exception_is_a_skip(db_ready, monkeypatch, no_lastfm):
    from backend.services.blacklist import BlacklistedTrack

    async def enqueue(*a, **k):
        raise BlacklistedTrack("added meanwhile")
    monkeypatch.setattr(download, "enqueue_download", enqueue)
    out = await auto.submit_tracked("A", "Song", source="similar")
    assert out == {"job_id": None, "skipped": "blacklisted: added meanwhile", "error": None,
                   "deduped": False, "blacklisted": True}
    out = await auto.download_tracked("A", "Song", source="similar")
    assert out["skipped"] == "blacklisted: added meanwhile" and out["ok"] is None and out["error"] is None
    assert await attempt_row("A", "Song") is None


async def test_submit_tracked_real_enqueue_skips_blacklisted(db_ready, fake_slsk, no_lastfm, monkeypatch):
    """The real enqueue_download's guard, reached when the entry appears after
    submit_tracked's own check (simulated by skipping that check)."""
    async with async_session() as s:
        s.add(DownloadAttempt(key=attempt_key("Test Artist", "Test Song"), artist="Test Artist",
                              track="Test Song", attempts=2, next_retry_at=datetime.utcnow() - timedelta(hours=1)))
        await s.commit()
    await blacklist("Test Artist", "Test Song", "Stopped from Downloads")
    out = await auto.download_tracked("Test Artist", "Test Song", source="similar")
    assert out["skipped"] == "blacklisted: Stopped from Downloads" and out["ok"] is None

    async def not_checked(db, artist, track):
        return None
    monkeypatch.setattr(auto, "is_blacklisted", not_checked)
    sub = await auto.submit_tracked("Test Artist", "Test Song", source="similar", skip_in_backoff=False)
    assert sub == {"job_id": None, "skipped": "blacklisted: Stopped from Downloads", "error": None,
                   "deduped": False, "blacklisted": True}
    assert fake_slsk.searches == []
    async with async_session() as s:
        assert (await s.execute(select(Job))).scalars().all() == []
    assert (await attempt_row("Test Artist", "Test Song")).attempts == 2  # unchanged


# --- is_infra_error ---------------------------------------------------------------

def test_infra_error_unchanged_and_reexported():
    from backend.workers import scheduler
    assert scheduler._is_infra_error is auto.is_infra_error
    assert auto.is_infra_error("Soulseek download backend unreachable: connection refused")
    assert auto.is_infra_error("Soulseek server not connected — try again later")
    assert auto.is_infra_error("Cancelled by user")
    assert auto.is_infra_error("Soulseek native client not available (not logged in); "
                               "slskd fallback is decommissioned")
    assert not auto.is_infra_error("Cancelled")
    assert not auto.is_infra_error("[Errno 107] Transport endpoint is not connected")
    assert not auto.is_infra_error("Peer did not respond in time")
    assert not auto.is_infra_error(None)


# --- wait=false: the web creates the row and runs the download in the background --

async def test_internal_run_without_wait(db_ready, fake_slsk, monkeypatch, no_lastfm):
    import backend.services.scanner as scanner

    async def fake_import(sess, path, artist_hint=None, target_track_id=None, reasons=None, existing_ids=None):
        return "track-9"
    monkeypatch.setattr(scanner, "import_downloaded_file", fake_import)
    fake_slsk.results = [result("alpha", "Music\\Test Artist\\01 - Test Song.flac")]
    fake_slsk.behaviour = {"alpha": "queue"}  # hold the transfer until the test lets it go

    resp = await download.internal_run_download(download.InternalDownloadRequest(
        artist="Test Artist", track="Test Song", job_id="job-w", source="similar", wait=False))
    assert resp == {"job_id": "job-w"}
    async with async_session() as s:
        row = (await s.execute(select(Job).where(Job.id == "job-w"))).scalar_one()
    assert row.status in ("pending", "running")
    assert "job-w" in download.live_download_jobs
    assert await auto.unsettled_jobs(["job-w"]) == {"job-w"}
    out = await auto.finish_tracked("job-w", "Test Artist", "Test Song", "similar")
    assert out["ok"] is None  # still running: nothing recorded
    assert await attempt_row("Test Artist", "Test Song") is None

    # Let the peer send the file.
    for _ in range(200):
        t = next(iter(fake_slsk.transfers.table.values()), None)
        if t is not None:
            break
        await asyncio.sleep(0.01)
    from backend.soulseek.protocol.types import TransferState
    t.received_bytes = t.total_bytes = 10
    t.save_path = "/nonexistent/staged.flac"
    t.state = TransferState.COMPLETED
    for _ in range(300):
        if not await auto.unsettled_jobs(["job-w"]):
            break
        await asyncio.sleep(0.01)
    out = await auto.finish_tracked("job-w", "Test Artist", "Test Song", "similar")
    assert out["ok"] is True
    assert "job-w" not in download.live_download_jobs
    await asyncio.gather(*download._background_downloads)


# --- the scheduler's polling batch ------------------------------------------------

async def test_batch_records_finished_and_returns_unknown_at_deadline(db_ready, monkeypatch):
    from backend.workers import scheduler

    async def ready():
        return True
    monkeypatch.setattr(scheduler, "_download_backend_ready", ready)
    # 2 s: "Works"/"Fails" settle after 0.05 s, so a loaded machine (suite run next to
    # the frontend build) still sees them finish well before the deadline; "Hangs" never does.
    monkeypatch.setattr(scheduler, "AUTO_DOWNLOAD_BATCH_MINUTES", 2 / 60)
    monkeypatch.setattr(scheduler, "AUTO_DOWNLOAD_POLL_SECONDS", 0.02)
    monkeypatch.setattr(scheduler, "AUTO_DOWNLOAD_MAX_OUTSTANDING", 2)

    submitted = []

    async def submit(artist, track, *, source, target_track_id=None, job_id=None, wait=True, **_):
        assert wait is False
        submitted.append(track)
        if track == "Skipped":
            return {"job_id": None, "skipped": "backoff", "error": None, "deduped": False}
        await write_job(job_id, "running")
        if track == "Fails":
            async def finish_later():
                await asyncio.sleep(0.05)
                async with async_session() as s:
                    row = await s.get(Job, job_id)
                    row.status = "failed"
                    row.result = json.dumps({"message": "No results for x"})
                    await s.commit()
            asyncio.create_task(finish_later())
        elif track == "Works":
            async def finish_later():
                await asyncio.sleep(0.05)
                async with async_session() as s:
                    row = await s.get(Job, job_id)
                    row.status = "completed"
                    await s.commit()
            asyncio.create_task(finish_later())
        return {"job_id": job_id, "skipped": None, "error": None, "deduped": False}
    monkeypatch.setattr(auto, "submit_tracked", submit)

    missing = [{"artist": "A", "track": t} for t in ("Works", "Fails", "Skipped", "Hangs")]
    outs = await scheduler._auto_download_missing(missing, "discover_similar")
    by_track = {o["track"]: o for o in outs}
    assert submitted == ["Works", "Fails", "Skipped", "Hangs"]
    assert by_track["Works"]["ok"] is True
    assert by_track["Fails"]["ok"] is False
    assert by_track["Hangs"]["ok"] is None  # still running at the deadline
    assert "Skipped" not in by_track
    assert (await attempt_row("A", "Fails")).attempts == 1
    assert await attempt_row("A", "Hangs") is None


# --- recommendations bulk download ------------------------------------------------

async def test_rec_bulk_download_sets_status_from_outcome(db_ready, fake_enqueue, no_lastfm):
    from backend.api import recommendations as recs_api
    from backend.models.recommendation import Recommendation

    async with async_session() as s:
        for rid, track in (("r1", "Works"), ("r2", "Fails"), ("r3", "Hangs"), ("r4", "Backoff")):
            s.add(Recommendation(id=rid, artist="A", track=track, source="tag", score=0.9, status="pending"))
        s.add(DownloadAttempt(key=attempt_key("A", "Backoff"), artist="A", track="Backoff", attempts=1,
                              next_retry_at=datetime.utcnow() + timedelta(days=1)))
        await s.commit()
    fake_enqueue.script["Fails"] = ("failed", {"message": "No results for A - Fails"})
    fake_enqueue.script["Hangs"] = ("running", None)

    await recs_api._download_recs(["r1", "r2", "r3", "r4"])
    async with async_session() as s:
        got = {r.id: r for r in (await s.execute(select(Recommendation))).scalars().all()}
    assert got["r1"].status == "downloaded"
    assert got["r2"].status == "failed" and "No results" in got["r2"].source_detail
    assert got["r3"].status == "pending"  # unknown outcome
    assert got["r4"].status == "pending"  # skipped for backoff


# --- detached (wait=false) run failing before the download proper ---------------

async def test_detached_failure_marks_row_failed_as_internal(db_ready, fake_slsk, monkeypatch, no_lastfm):
    async def broken(job_id, *args):
        raise RuntimeError("database is locked")
    monkeypatch.setattr(download, "_run_download_job", broken)
    resp = await download.internal_run_download(download.InternalDownloadRequest(
        artist="Test Artist", track="Test Song", job_id="job-d", source="similar", wait=False))
    assert resp == {"job_id": "job-d"}
    await asyncio.gather(*download._background_downloads)
    async with async_session() as s:
        row = await s.get(Job, "job-d")
    assert row.status == "failed" and "Internal error: database is locked" in row.result
    out = await auto.finish_tracked("job-d", "Test Artist", "Test Song", "similar")
    assert out["ok"] is None  # our failure, not the track's
    assert await attempt_row("Test Artist", "Test Song") is None


# --- the scheduler tick deadline ----------------------------------------------------

async def test_tick_deadline_cuts_a_second_batch_short(db_ready, monkeypatch):
    import time
    from backend.workers import scheduler

    async def ready():
        return True
    monkeypatch.setattr(scheduler, "_download_backend_ready", ready)
    monkeypatch.setattr(scheduler, "AUTO_DOWNLOAD_POLL_SECONDS", 0.02)
    submitted = []

    async def submit(artist, track, *, source, job_id=None, **_):
        submitted.append(track)
        await write_job(job_id, "running")  # never finishes
        return {"job_id": job_id, "skipped": None, "error": None, "deduped": False}
    monkeypatch.setattr(auto, "submit_tracked", submit)

    scheduler._tick_deadline.set(time.monotonic() + 0.4)  # what start_tick does, shortened
    started = time.monotonic()
    first = await scheduler._auto_download_missing([{"artist": "A", "track": "One"}], "discover_similar")
    assert time.monotonic() - started < 5  # stopped by the tick, not the 45-min batch deadline
    assert [o["ok"] for o in first] == [None]
    second = await scheduler._auto_download_missing([{"artist": "A", "track": "Two"}], "lastfm_top_tracks")
    assert second == [] and submitted == ["One"]  # no new batch after the tick deadline


# --- a blacklisted upgrade in the scheduled scan ------------------------------------

async def test_blacklisted_upgrade_goes_back_to_pending(db_ready, monkeypatch):
    """_prepare_upgrade moves the row to "downloading" before submit_tracked; a blacklist
    skip starts no job, so the row must not stay stuck at "downloading"."""
    from backend.models.blacklist import DownloadBlacklist
    from backend.models.track import Track
    from backend.models.upgrade import TrackUpgrade
    from backend.workers import scheduler

    async def ready():
        return True
    monkeypatch.setattr(scheduler, "_download_backend_ready", ready)

    async with async_session() as s:
        s.add(Track(id="trk-bl", title="Banned", file_path="/m/banned.mp3", format="mp3", bitrate=192))
        s.add(TrackUpgrade(id="up-bl", track_id="trk-bl", original_format="mp3", reason="low_bitrate",
                           status="pending", attempts=1, max_attempts=3))
        s.add(DownloadBlacklist(id="bl-1", artist="A", track="Banned", reason="nope"))
        await s.commit()

    outs = await scheduler._auto_download_missing(
        [{"artist": "A", "track": "Banned", "upgrade_id": "up-bl", "track_id": "trk-bl"}], "upgrade_scan")
    assert outs == []
    async with async_session() as s:
        row = await s.get(TrackUpgrade, "up-bl")
        jobs = (await s.execute(select(Job))).scalars().all()
    assert row.status == "pending" and row.attempts == 1  # attempt refunded, not stuck downloading
    assert jobs == []
