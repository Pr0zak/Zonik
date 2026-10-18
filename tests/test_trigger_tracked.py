"""/api/download/trigger: bulk-list sources (Weekly Radar etc.) go through the
failed-search memory; a plain manual trigger does not.

Run: uv run --with pytest --with pytest-asyncio pytest tests/test_trigger_tracked.py
"""
from datetime import datetime, timedelta

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import select, func

import backend.api.download as download
import backend.services.auto_download as auto
from backend.database import async_session
from backend.models.download_attempt import DownloadAttempt
from backend.models.job import Job
from backend.services.download_attempts import attempt_key
from fake_soulseek import result

pytestmark = pytest.mark.asyncio

ARTIST, TRACK = "Test Artist", "Test Song"


@pytest.fixture
def lastfm(monkeypatch):
    import backend.services.lastfm as lf
    calls = []

    async def api(method, params):
        calls.append(params["track"])
        return {"track": {"duration": "200000"}}
    monkeypatch.setattr(lf, "lastfm_api", api)
    monkeypatch.setattr(auto, "_lastfm_configured", lambda: True)
    auto._duration_cache.clear()
    yield calls
    auto._duration_cache.clear()


async def trigger(**kw):
    bt = BackgroundTasks()
    async with async_session() as db:
        resp = await download.trigger_download(download.DownloadRequest(artist=ARTIST, track=TRACK, **kw), bt, db)
    await bt()  # run the download to its end, as the response would
    return resp


async def put_backoff():
    async with async_session() as s:
        s.add(DownloadAttempt(key=attempt_key(ARTIST, TRACK), artist=ARTIST, track=TRACK, attempts=1,
                              next_retry_at=datetime.utcnow() + timedelta(days=1)))
        await s.commit()


async def n_jobs():
    async with async_session() as s:
        return (await s.execute(select(func.count(Job.id)))).scalar_one()


async def attempts():
    async with async_session() as s:
        row = await s.get(DownloadAttempt, attempt_key(ARTIST, TRACK))
        return row.attempts if row else None


async def test_radar_trigger_in_backoff_is_skipped(db_ready, fake_slsk, lastfm):
    await put_backoff()
    resp = await trigger(source="weekly-radar", bulk=True)  # "Download all"
    assert resp["status"] == "skipped" and "backoff" in resp["reason"]
    assert await n_jobs() == 0 and fake_slsk.searches == []


async def test_single_click_in_backoff_downloads_and_records(db_ready, fake_slsk, lastfm):
    await put_backoff()
    fake_slsk.results = [result("alpha", f"Music\\{ARTIST}\\01 - {TRACK}.flac")]
    fake_slsk.behaviour = {"alpha": "fail"}
    resp = await trigger(source="weekly-radar")  # one track's button: bulk False
    assert "job_id" in resp
    assert await attempts() == 2  # outcome still recorded


async def test_radar_trigger_records_failure_and_gates_duration(db_ready, fake_slsk, lastfm):
    fake_slsk.results = [result("alpha", f"Music\\{ARTIST}\\01 - {TRACK}.flac")]
    fake_slsk.behaviour = {"alpha": "fail"}
    resp = await trigger(source="weekly-radar", bulk=True)
    assert "job_id" in resp
    assert lastfm == [TRACK]  # length looked up for the duration gate
    assert await attempts() == 1  # outcome recorded once the job ended


async def test_radar_trigger_success_forgets_the_track(db_ready, fake_slsk, lastfm, monkeypatch):
    import backend.services.scanner as scanner

    async def fake_import(*a, **k):
        return "track-1"
    monkeypatch.setattr(scanner, "import_downloaded_file", fake_import)
    async with async_session() as s:
        s.add(DownloadAttempt(key=attempt_key(ARTIST, TRACK), artist=ARTIST, track=TRACK, attempts=2,
                              next_retry_at=datetime.utcnow() - timedelta(hours=1)))
        await s.commit()
    fake_slsk.results = [result("alpha", f"Music\\{ARTIST}\\01 - {TRACK}.flac")]
    await trigger(source="weekly-radar")
    assert await attempts() is None


@pytest.mark.parametrize("source", [None, "manual", "library"])
async def test_manual_trigger_stays_untracked(db_ready, fake_slsk, lastfm, source):
    await put_backoff()
    fake_slsk.results = [result("alpha", f"Music\\{ARTIST}\\01 - {TRACK}.flac")]
    fake_slsk.behaviour = {"alpha": "fail"}
    resp = await trigger(source=source)
    assert "job_id" in resp  # not skipped despite the backoff
    assert lastfm == []
    assert await attempts() == 1  # nothing recorded


# --- blacklist guard in enqueue_download (DC-22) ------------------------------------

async def add_blacklist(artist=ARTIST, track=TRACK, reason="Stopped from Downloads"):
    import uuid
    from backend.models.blacklist import DownloadBlacklist
    async with async_session() as s:
        s.add(DownloadBlacklist(id=str(uuid.uuid4()), artist=artist, track=track, reason=reason))
        await s.commit()


async def test_enqueue_download_raises_for_blacklisted(db_ready, fake_slsk):
    from backend.services.blacklist import BlacklistedTrack
    await add_blacklist()
    with pytest.raises(BlacklistedTrack) as exc:
        await download.enqueue_download(ARTIST, TRACK, job_id="job-b", source="playlist")
    assert exc.value.reason == "Stopped from Downloads"
    assert await n_jobs() == 0 and fake_slsk.searches == []
    assert not download.live_download_jobs and not download.stage_counts


async def test_worker_side_enqueue_refuses_before_delegating(db_ready, monkeypatch):
    """The arq worker has no client: the guard runs before the web delegation, so a
    blacklisted track never turns into a 'backend unreachable' failed row."""
    import backend.soulseek as soulseek
    from backend.services.blacklist import BlacklistedTrack
    monkeypatch.setattr(soulseek, "get_client", lambda: None)
    delegated = []

    async def delegate(*a, **k):
        delegated.append(a)
        return "x"
    monkeypatch.setattr(download, "_delegate_download_to_web", delegate)
    await add_blacklist(track=None, reason=None)  # whole artist
    with pytest.raises(BlacklistedTrack) as exc:
        await download.enqueue_download(ARTIST, "Any Song", source="similar")
    assert exc.value.reason == "Artist blacklisted" and delegated == []
    assert await n_jobs() == 0


async def test_internal_run_answers_blacklisted(db_ready, fake_slsk):
    await add_blacklist()
    resp = await download.internal_run_download(download.InternalDownloadRequest(
        artist=ARTIST, track=TRACK, job_id="job-i", source="similar", wait=False))
    assert resp == {"job_id": None, "blacklisted": True, "reason": "Stopped from Downloads"}
    assert await n_jobs() == 0


async def test_trigger_still_refuses_blacklisted(db_ready, fake_slsk):
    await add_blacklist()
    async with async_session() as db:
        resp = await download.trigger_download(download.DownloadRequest(artist=ARTIST, track=TRACK),
                                               BackgroundTasks(), db)
    assert resp == {"error": "blacklisted", "reason": "Stopped from Downloads"}


async def test_origin_is_stamped_on_the_row(db_ready, fake_slsk, monkeypatch):
    import json
    import backend.services.scanner as scanner

    async def fake_import(*a, **k):
        return "track-1"
    monkeypatch.setattr(scanner, "import_downloaded_file", fake_import)
    sent = []

    async def record(payload):
        sent.append(payload)
    monkeypatch.setattr(download, "broadcast_job_update", record)
    fake_slsk.results = [result("alpha", f"Music\\{ARTIST}\\01 - {TRACK}.flac")]
    jid = await download.enqueue_download(ARTIST, TRACK, job_id="job-o", source="playlist", origin="playlist:import")
    async with async_session() as s:
        row = await s.get(Job, jid)
    assert row.status == "completed"
    assert json.loads(row.tracks)[0]["origin"] == "playlist:import"  # sticky to the end
    submitted = json.loads(row.log)[0]
    assert submitted["k"] == "submitted" and submitted["origin"] == "playlist:import"
    final = sent[-1]
    assert final["status"] == "completed" and final["card"] == "dl:playlist"
