"""/api/jobs routes the Downloads page reads: failure buckets (SQL) agree with the
Python failure classifier, `since` scoping, counts, list-item fields.

Route coroutines are called directly inside `async with async_session() as db`.

Run: uv run --with pytest --with pytest-asyncio pytest tests/test_jobs_api.py
"""
import json
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import select

import backend.api.jobs as jobs
from backend.database import async_session
from backend.models.job import Job
from backend.services import download_failures as df
from test_download_failures import CASES  # every result/tracks shape Zonik writes

pytestmark = pytest.mark.asyncio

NOW = datetime.utcnow()
SINCE = NOW - timedelta(hours=6)
OLD = NOW - timedelta(days=2)  # before SINCE
SINCE_ISO = SINCE.isoformat() + "Z"


def _tracks(artist="A", track="T", **kw) -> str:
    return json.dumps([{"artist": artist, "track": track, "status": "failed", **kw}])


async def seed(*rows: dict) -> list[str]:
    ids = []
    async with async_session() as s:
        for r in rows:
            jid = r.pop("id", None) or str(uuid.uuid4())
            ids.append(jid)
            r.setdefault("type", "download")
            r.setdefault("card", "dl:manual")
            r.setdefault("started_at", NOW - timedelta(minutes=5))
            if r.get("status") in ("completed", "failed") and "finished_at" not in r:
                r["finished_at"] = NOW - timedelta(minutes=1)
            s.add(Job(id=jid, **r))
        await s.commit()
    return ids


def failed_shapes(finished_at=None) -> list[dict]:
    """One failed row per classifier shape (status failed only), keyed by case id."""
    out = []
    for cid, status, result, tracks, cls in CASES:
        if status != "failed":
            continue
        row = {"id": f"case-{cid}", "status": "failed", "result": result,
               "tracks": tracks if tracks is not None else _tracks()}
        if finished_at is not None:
            row["finished_at"] = finished_at
        out.append(row)
    return out


async def bucket_members() -> dict[str, set[str]]:
    out = {}
    async with async_session() as s:
        for key in jobs.FAILURE_REASONS:
            rows = (await s.execute(select(Job.id).where(Job.status == "failed", jobs._failure_filter(key)))).all()
            out[key] = {r[0] for r in rows}
    return out


async def test_five_buckets_partition_failed_rows_and_agree_with_classifier(db_ready):
    rows = failed_shapes()
    rows.append({"id": "src-err-only", "status": "failed",
                 "result": json.dumps({"message": "All 2 sources failed", "last_error": "Peer did not respond in time",
                                       "source_errors": [{"user": "u1", "error": "Not imported: wrong song"},
                                                         {"user": "u2", "error": "Peer did not respond in time"}]}),
                 "tracks": _tracks(error="Peer did not respond in time",
                                   source_errors=[{"user": "u1", "error": "Not imported: wrong song"}])})
    rows.append({"id": "malformed-tracks", "status": "failed",
                 "result": json.dumps({"message": "All 1 sources failed"}), "tracks": "{not json"})
    rows.append({"id": "null-tracks", "status": "failed",
                 "result": json.dumps({"message": "No results for A - T"}), "tracks": None})
    rows.append({"id": "orphan-dismissed", "status": "failed",
                 "result": json.dumps({"incident_dismissed": True}), "tracks": _tracks()})
    rows.append({"id": "empty-object", "status": "failed", "result": "{}", "tracks": _tracks()})
    rows.append({"id": "restart-dismissed", "status": "failed",
                 "result": json.dumps({"error": "Interrupted by restart", "incident_dismissed": True}),
                 "tracks": _tracks()})
    rows.append({"id": "peer-cancelled-denial", "status": "failed",
                 "result": json.dumps({"message": "All 1 sources failed", "last_error": "Cancelled"}),
                 "tracks": _tracks(error="Cancelled")})
    await seed(*[dict(r) for r in rows], {"status": "completed", "result": json.dumps({"track_id": "x"})},
               {"status": "running"})

    members = await bucket_members()
    assert set(members) == set(df.BUCKETS)
    seen: dict[str, str] = {}
    for key, ids in members.items():
        for jid in ids:
            assert jid not in seen, f"{jid} in both {seen.get(jid)} and {key}"
            seen[jid] = key
    assert set(seen) == {r["id"] for r in rows}  # every failed row lands somewhere

    # The agreement test: SQL bucket == BUCKET_OF_CLASS[failure_class(...)]
    for r in rows:
        cls = df.failure_class("failed", r["result"], r["tracks"])
        assert seen[r["id"]] == df.BUCKET_OF_CLASS[cls], (r["id"], cls, seen[r["id"]])
    assert seen["src-err-only"] == "peer"
    assert seen["peer-cancelled-denial"] == "peer"
    assert seen["case-cancelled"] == "infra"
    assert seen["case-null-result"] == "infra"

    async with async_session() as db:
        summary = await jobs.failure_summary(type="download,bulk_download", db=db)
    assert sum(g["count"] for g in summary) == len(rows)
    assert {g["reason"] for g in summary} <= set(jobs.FAILURE_REASONS)
    assert any(g["reason"] == "infra" for g in summary)


async def test_retry_failed_peer_leaves_infra_rows(db_ready, monkeypatch):
    calls = []

    async def fake_retry(items):
        calls.append(items)
    monkeypatch.setattr(jobs, "_retry_downloads", fake_retry)
    await seed(
        {"id": "peer1", "status": "failed", "result": json.dumps({"message": "All 1 sources failed"}),
         "tracks": _tracks("P", "One", error="Transfer stalled")},
        {"id": "cancel1", "status": "failed", "result": json.dumps({"error": "Cancelled by user"}),
         "tracks": _tracks("C", "One")},
        {"id": "restart1", "status": "failed", "result": json.dumps({"error": "Interrupted by restart"}),
         "tracks": _tracks("R", "One", status="downloading")},
        {"id": "orphan1", "status": "failed", "result": None, "tracks": _tracks("O", "One", status="queued")},
    )
    bt = BackgroundTasks()
    async with async_session() as db:
        resp = await jobs.retry_failed(bt, type="download,bulk_download", reason="peer", db=db)
    await bt()
    assert resp == {"ok": True, "jobs": 1, "tracks": 1}
    assert [it["job_id"] for it in calls[0]] == ["peer1"]
    async with async_session() as s:
        left = {r[0] for r in (await s.execute(select(Job.id))).all()}
    assert left == {"cancel1", "restart1", "orphan1"}


async def test_list_items_carry_class_stage_and_source_errors(db_ready):
    errs = [{"user": "alpha", "error": "Denied", "at": "2026-10-18T07:09:01"}]
    await seed(
        {"id": "live", "status": "running", "result": None,
         "tracks": json.dumps([{"artist": "A", "track": "T", "status": "downloading", "stage": "queued_at_peer",
                                "stage_since": "2026-10-18T07:11:42", "attempt": 2, "of": 4,
                                "source_errors": errs,
                                "search": None}])},
        {"id": "nf", "status": "failed",
         "result": json.dumps({"message": "No results for A - T",
                               "search": {"queries": [], "kept": 0, "files_seen": 3}}),
         "tracks": json.dumps([{"artist": "A", "track": "T", "status": "failed", "stage": "searching"}])},
        {"id": "pf", "status": "failed",
         "result": json.dumps({"message": "All 1 sources failed", "source_errors": [{"user": "b", "error": "x"}]}),
         "tracks": json.dumps([{"artist": "A", "track": "T", "status": "failed"}])},
        {"id": "other", "type": "scan", "status": "completed"},
    )
    async with async_session() as db:
        out = await jobs.list_jobs(limit=25, type="download,bulk_download", db=db)
    by_id = {i["id"]: i for i in out["items"]}
    assert set(by_id) == {"live", "nf", "pf"}
    live = by_id["live"]
    assert live["failure_class"] is None
    assert (live["stage"], live["attempt"], live["of"]) == ("queued_at_peer", 2, 4)
    assert live["stage_since"] == "2026-10-18T07:11:42"
    assert live["source_errors"] == errs
    assert isinstance(live["tracks"], str) and live["result"] is None  # contract: strings stay strings
    nf = by_id["nf"]
    assert nf["failure_class"] == "not_found" and nf["search"]["files_seen"] == 3
    assert nf["source_errors"] == [] and nf["stage"] == "searching"
    assert by_id["pf"]["failure_class"] == "peer"
    assert by_id["pf"]["source_errors"] == [{"user": "b", "error": "x"}]  # from the result when tracks lack it
    assert by_id["pf"]["error"] == "All 1 sources failed"  # job_outcome keys unchanged

    async with async_session() as db:
        other = await jobs.list_jobs(limit=25, type="scan", db=db)
    assert "failure_class" not in other["items"][0]  # only download rows get the fields


async def test_since_scopes_list_counts_failures_and_clear(db_ready):
    await seed(
        {"id": "c-new", "status": "completed", "type": "download"},
        {"id": "c-old", "status": "completed", "type": "bulk_download", "finished_at": OLD, "started_at": OLD},
        {"id": "f-new", "status": "failed", "result": json.dumps({"message": "No results for A - T"}),
         "tracks": _tracks()},
        {"id": "f-old", "status": "failed", "result": json.dumps({"message": "No results for B - T"}),
         "tracks": _tracks("B"), "finished_at": OLD, "started_at": OLD},
        {"id": "run", "status": "running"},
        {"id": "pend", "status": "pending", "type": "bulk_download"},
        {"id": "scan", "type": "scan", "status": "completed"},
    )
    async with async_session() as db:
        c = await jobs.job_counts(type="download,bulk_download", since=SINCE_ISO, db=db)
    assert (c["completed"], c["failed"], c["running"], c["pending"]) == (2, 2, 1, 1)  # all-time, no longer zero
    assert c["all"] == 6 and c["active"] == 2
    assert (c["completed_since"], c["failed_since"]) == (1, 1)
    assert c["completed_today"] == 1 and c["completed_week"] == 2

    async with async_session() as db:
        c2 = await jobs.job_counts(type="download,bulk_download", db=db)
    assert (c2["completed_since"], c2["failed_since"]) == (2, 2)  # all-time without `since`
    async with async_session() as db:
        c3 = await jobs.job_counts(type="download", db=db)  # single type still works
    assert c3["completed"] == 1 and c3["pending"] == 0

    async with async_session() as db:
        lst = await jobs.list_jobs(limit=25, type="download,bulk_download", status="completed,failed",
                                   since=SINCE_ISO, db=db)
    assert {i["id"] for i in lst["items"]} == {"c-new", "f-new"}
    async with async_session() as db:  # the rolling alias still works
        lst = await jobs.list_jobs(limit=25, type="download,bulk_download", status="completed",
                                   timeframe="today", db=db)
    assert {i["id"] for i in lst["items"]} == {"c-new"}
    async with async_session() as db:  # an aware non-UTC offset is converted to UTC
        aware = (SINCE + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S") + "+02:00"
        lst = await jobs.list_jobs(limit=25, type="download,bulk_download", status="failed", since=aware, db=db)
    assert {i["id"] for i in lst["items"]} == {"f-new"}

    async with async_session() as db:
        f = await jobs.failure_summary(type="download,bulk_download", since=SINCE_ISO, db=db)
    assert f == [{"reason": "not_found", "label": jobs.FAILURE_REASONS["not_found"], "count": 1}]

    async with async_session() as db:
        res = await jobs.clear_jobs(type="download,bulk_download", status="completed,failed", since=SINCE_ISO, db=db)
    assert res["deleted"] == 2
    async with async_session() as s:
        left = {r[0] for r in (await s.execute(select(Job.id))).all()}
    assert left == {"c-old", "f-old", "run", "pend", "scan"}


async def test_retry_failed_respects_since(db_ready, monkeypatch):
    async def fake_retry(items):
        pass
    monkeypatch.setattr(jobs, "_retry_downloads", fake_retry)
    await seed(
        {"id": "f-new", "status": "failed", "result": json.dumps({"message": "No results for A - T"}),
         "tracks": _tracks()},
        {"id": "f-old", "status": "failed", "result": json.dumps({"message": "No results for B - T"}),
         "tracks": _tracks("B"), "finished_at": OLD, "started_at": OLD},
    )
    async with async_session() as db:
        resp = await jobs.retry_failed(BackgroundTasks(), type="download,bulk_download", since=SINCE_ISO, db=db)
    assert resp["jobs"] == 1
    async with async_session() as s:
        left = {r[0] for r in (await s.execute(select(Job.id))).all()}
    assert left == {"f-old"}


async def test_parse_since():
    assert jobs._parse_since(None) is None
    assert jobs._parse_since("garbage") is None
    assert jobs._parse_since("2026-10-18T05:00:00.000Z") == datetime(2026, 10, 18, 5, 0)
    assert jobs._parse_since("2026-10-18T07:00:00+02:00") == datetime(2026, 10, 18, 5, 0)
    assert jobs._parse_since("2026-10-18T07:00:00 02:00") == datetime(2026, 10, 18, 5, 0)  # unencoded '+'
    assert jobs._parse_since("2026-10-18T05:00:00") == datetime(2026, 10, 18, 5, 0)


async def test_infra_reason_registered():
    assert list(jobs.FAILURE_REASONS) == list(df.BUCKETS)
    assert jobs.FAILURE_REASONS["infra"].startswith("Not the track's fault")


# --- R1-C2: delete, scoped clear, retry replaces, stop-trying -----------------

async def _ids() -> set[str]:
    async with async_session() as s:
        return {r[0] for r in (await s.execute(select(Job.id))).all()}


async def test_delete_job(db_ready):
    await seed({"id": "done", "status": "completed"}, {"id": "live", "status": "running"},
               {"id": "scan", "type": "scan", "status": "completed"})
    async with async_session() as db:
        assert await jobs.delete_job("done", db=db) == {"deleted": 1}
    async with async_session() as db:
        assert await jobs.delete_job("live", db=db) == {"error": "Job is active"}
    async with async_session() as db:
        assert await jobs.delete_job("missing", db=db) == {"error": "Job not found"}
    async with async_session() as db:
        assert await jobs.delete_job("scan", db=db) == {"error": "Not a download job"}
    assert await _ids() == {"live", "scan"}


async def test_delete_route_declared_after_clear():
    paths = [(r.path, sorted(r.methods)) for r in jobs.router.routes]
    assert paths.index(("/clear", ["DELETE"])) < paths.index(("/{job_id}", ["DELETE"]))


async def test_clear_never_deletes_active_rows(db_ready):
    await seed({"id": "done", "status": "completed"}, {"id": "live", "status": "running"},
               {"id": "pend", "status": "pending"},
               {"id": "bad", "status": "failed", "result": json.dumps({"message": "All 1 sources failed"}),
                "tracks": _tracks()})
    async with async_session() as db:
        res = await jobs.clear_jobs(type="download,bulk_download", status="running,pending,completed", db=db)
    assert res["deleted"] == 1
    async with async_session() as db:
        assert await jobs.clear_jobs(type="download", status="running,pending", db=db) == {"deleted": 0}
    assert await _ids() == {"live", "pend", "bad"}


async def test_retry_job_replaces_the_row(db_ready, monkeypatch):
    calls = []

    async def fake_retry(items):
        calls.append(items)
    monkeypatch.setattr(jobs, "_retry_downloads", fake_retry)
    await seed({"id": "f1", "status": "failed", "card": "dl:upgrade",
                "result": json.dumps({"message": "All 1 sources failed"}),
                "tracks": _tracks("A", "T", status="downloading")},  # a reaped row stays retryable
               {"id": "ok", "status": "completed"})
    bt = BackgroundTasks()
    async with async_session() as db:
        resp = await jobs.retry_job("f1", bt, db=db)
    await bt()
    assert resp == {"ok": True, "total": 1, "replaced_job_id": "f1"}
    assert calls == [[{"artist": "A", "track": "T", "source": "upgrade", "job_id": "f1"}]]
    assert await _ids() == {"ok"}
    async with async_session() as db:
        assert await jobs.retry_job("ok", BackgroundTasks(), db=db) == {"error": "Job not retryable"}


async def test_stop_trying(db_ready):
    from backend.models.blacklist import DownloadBlacklist
    from backend.models.download_attempt import DownloadAttempt
    from backend.models.track import Track
    from backend.models.upgrade import TrackUpgrade
    from backend.services.download_attempts import attempt_key

    key = attempt_key("Michael Bublé", "Jingle Bells")
    async with async_session() as s:
        s.add(Track(id="trk1", title="Jingle Bells", file_path="/m/jb.mp3", format="mp3", bitrate=320))
        s.add(DownloadAttempt(key=key, artist="Michael Bublé", track="Jingle Bells", attempts=4,
                              next_retry_at=NOW + timedelta(days=300)))
        s.add(TrackUpgrade(id="u1", track_id="trk1", original_format="mp3", reason="lossy_to_lossless",
                           status="failed", job_id="other-job"))
        s.add(TrackUpgrade(id="u2", track_id="trk1", original_format="mp3", reason="lossy_to_lossless",
                           status="completed", job_id="old"))
        await s.commit()
    await seed({"id": "f1", "status": "failed", "result": json.dumps({"message": "No source better than x",
                                                                        "track_id": "trk1"}),
                "tracks": _tracks("Michael Bublé", "Jingle Bells")},
               {"id": "f2", "status": "failed", "result": json.dumps({"message": "No results for x"}),
                "tracks": _tracks("Michael Bublé", "Jingle Bells (Live)")},
               {"id": "live", "status": "running", "tracks": _tracks("Michael Bublé", "Jingle Bells (Live)")})

    async with async_session() as db:
        resp = await jobs.stop_trying("f1", None, db=db)
    assert resp["attempt_deleted"] is True and resp["upgrades_skipped"] == 1 and resp["removed"] is False
    async with async_session() as s:
        bl = await s.get(DownloadBlacklist, resp["blacklisted"])
        assert (bl.artist, bl.track, bl.reason) == ("Michael Bublé", "Jingle Bells", "Stopped from Downloads")
        assert await s.get(DownloadAttempt, key) is None
        assert (await s.get(TrackUpgrade, "u1")).status == "skipped"
        assert (await s.get(TrackUpgrade, "u2")).status == "completed"
    assert "f1" in await _ids()

    # A second stop on the same track reuses the entry instead of adding a duplicate.
    async with async_session() as db:
        again = await jobs.stop_trying("f1", jobs.StopTryingRequest(remove=True), db=db)
    assert again["blacklisted"] == resp["blacklisted"] and again["attempt_deleted"] is False
    assert again["removed"] is True and "f1" not in await _ids()

    # remove on an active row blacklists but keeps the row.
    async with async_session() as db:
        live = await jobs.stop_trying("live", jobs.StopTryingRequest(remove=True), db=db)
    assert live["removed"] is False and "live" in await _ids()
    async with async_session() as s:
        n = (await s.execute(select(DownloadBlacklist))).scalars().all()
    assert len(n) == 2
    async with async_session() as db:
        assert await jobs.stop_trying("missing", None, db=db) == {"error": "Job not found"}


# --- R1-D2: joins, outcome/next, times_failed_30d, GET /summary ---------------

async def _seed_d2():
    from backend.models.download_attempt import DownloadAttempt
    from backend.models.track import Track
    from backend.models.upgrade import TrackUpgrade
    from backend.services.download_attempts import attempt_key

    async with async_session() as s:
        s.add(Track(id="trkN", title="New", file_path="/m/new.flac", format="flac", bitrate=1000,
                    file_size=30_000_000, play_count=2, last_played_at=NOW, duration_seconds=200.0))
        s.add(Track(id="trkH", title="Had", file_path="/m/had.mp3", format="mp3", bitrate=320, play_count=9,
                    last_played_at=NOW))
        s.add(Track(id="trkU", title="Up", file_path="/m/up.flac", format="flac", play_count=0))
        s.add(Track(id="trkF", title="UpFail", file_path="/m/upfail.mp3", format="mp3", bitrate=192))
        s.add(TrackUpgrade(id="up-ok", track_id="trkU", original_format="mp3", original_bitrate=320,
                           upgraded_format="flac", upgraded_bitrate=1000, status="completed", job_id="c-upg",
                           reason="lossy_to_lossless", attempts=1, max_attempts=3))
        s.add(TrackUpgrade(id="up-fail", track_id="trkF", original_format="mp3", original_bitrate=192,
                           status="failed", job_id="f-upg", reason="low_bitrate", attempts=2, max_attempts=3))
        s.add(DownloadAttempt(key=attempt_key("Retry Artist", "Retry Song"), artist="Retry Artist",
                              track="Retry Song", attempts=1, next_retry_at=NOW + timedelta(hours=18),
                              last_error="No results for Retry Artist - Retry Song"))
        s.add(DownloadAttempt(key=attempt_key("Gone Artist", "Gone Song"), artist="Gone Artist",
                              track="Gone Song", attempts=4, next_retry_at=NOW + timedelta(days=359)))
        await s.commit()

    def done(artist, track, **res):
        return json.dumps(res), json.dumps([{"artist": artist, "track": track, "status": "downloaded"}])

    r, t = done("N", "New", track_id="trkN", file_size=30_000_000, filename="01 New.flac")
    rows = [{"id": "c-new", "status": "completed", "card": "dl:similar", "result": r, "tracks": t}]
    r, t = done("H", "Had", track_id="trkH", already_in_library=True, file_size=9_000_000)
    rows.append({"id": "c-had", "status": "completed", "card": "dl:similar", "result": r, "tracks": t})
    r, t = done("U", "Up", track_id="trkU", file_size=20_000_000, filename="up.flac")
    rows.append({"id": "c-upg", "status": "completed", "card": "dl:upgrade", "result": r, "tracks": t})
    r, t = done("G", "Gone", track_id="deleted-track", file_size=5_000_000, filename="gone.mp3")
    rows.append({"id": "c-gone", "status": "completed", "card": "dl:manual", "result": r, "tracks": t,
                 "finished_at": NOW - timedelta(seconds=10)})
    nf = json.dumps({"message": "No results for x"})
    rows += [
        {"id": "f-tr1", "status": "failed", "card": "dl:similar", "result": nf,
         "tracks": _tracks("Retry Artist", "Retry Song")},
        {"id": "f-tr1-old", "status": "failed", "card": "dl:similar", "result": nf,
         "tracks": _tracks("retry artist", "Retry Song"), "finished_at": NOW - timedelta(days=3),
         "started_at": NOW - timedelta(days=3)},
        {"id": "f-tr1-restart", "status": "failed", "card": "dl:similar",
         "result": json.dumps({"error": "Interrupted by restart"}), "tracks": _tracks("Retry Artist", "Retry Song"),
         "finished_at": NOW - timedelta(days=1), "started_at": NOW - timedelta(days=1)},
        {"id": "f-tr1-ancient", "status": "failed", "card": "dl:similar", "result": nf,
         "tracks": _tracks("Retry Artist", "Retry Song"), "finished_at": NOW - timedelta(days=40),
         "started_at": NOW - timedelta(days=40)},
        {"id": "f-tr4", "status": "failed", "card": "dl:discovery", "result": nf,
         "tracks": _tracks("Gone Artist", "Gone Song")},
        {"id": "f-upg", "status": "failed", "card": "dl:upgrade",
         "result": json.dumps({"message": "No source better than the current mp3 for x"}),
         "tracks": _tracks("UF", "UpFail")},
        {"id": "f-man", "status": "failed", "card": "dl:manual",
         "result": json.dumps({"message": "All 1 sources failed", "last_error": "Transfer stalled"}),
         "tracks": _tracks("M", "Manual", error="Transfer stalled")},
        {"id": "live", "status": "running", "tracks": _tracks("L", "Live", status="downloading")},
    ]
    await seed(*rows)


async def test_list_items_carry_joins(db_ready):
    await _seed_d2()
    async with async_session() as db:
        out = await jobs.list_jobs(limit=50, type="download,bulk_download", db=db)
    by = {i["id"]: i for i in out["items"]}

    assert by["c-new"]["outcome"] == "new"
    assert by["c-new"]["track"] == {"id": "trkN", "format": "flac", "bitrate": 1000, "file_size": 30_000_000,
                                    "play_count": 2, "last_played_at": NOW.isoformat(), "duration_seconds": 200.0}
    assert by["c-new"]["upgrade"] is None and by["c-new"]["ledger"] is None
    assert by["c-new"]["next"]["kind"] == "none"
    assert by["c-had"]["outcome"] == "already_had"
    assert by["c-upg"]["outcome"] == "replaced"
    assert by["c-upg"]["upgrade"] == {"original_format": "mp3", "original_bitrate": 320, "upgraded_format": "flac",
                                      "upgraded_bitrate": 1000, "attempts": 1, "max_attempts": 3,
                                      "status": "completed"}
    assert by["c-gone"]["track"] is None and by["c-gone"]["outcome"] == "new"  # deleted track: null, no 500

    tr1 = by["f-tr1"]
    assert tr1["ledger"]["attempts"] == 1 and tr1["ledger"]["retired"] is False
    assert tr1["ledger"]["last_error"].startswith("No results for")
    assert tr1["next"]["kind"] == "retry" and tr1["next"]["at"] == tr1["ledger"]["next_retry_at"]
    assert tr1["next"]["attempts"] == 1 and tr1["next"]["max_attempts"] == 4
    assert tr1["times_failed_30d"] == 2  # itself + 3 days ago; the restart and the 40-day-old row don't count
    assert by["f-tr1-restart"]["times_failed_30d"] == 2  # same key, same count
    assert tr1["outcome"] is None and tr1["track"] is None

    tr4 = by["f-tr4"]
    assert tr4["ledger"]["retired"] is True and tr4["next"]["kind"] == "retired"
    assert tr4["times_failed_30d"] == 1

    upg = by["f-upg"]
    assert upg["next"] == {"kind": "scans", "at": None, "attempts": 2, "max_attempts": 3}
    assert upg["upgrade"]["status"] == "failed" and upg["upgrade"]["attempts"] == 2

    man = by["f-man"]
    assert man["next"]["kind"] == "none" and man["ledger"] is None and man["times_failed_30d"] == 1
    assert by["live"]["next"]["kind"] == "none" and by["live"]["outcome"] is None


async def test_summary_numbers_add_up(db_ready):
    await _seed_d2()
    async with async_session() as db:
        s = await jobs.jobs_summary(type="download,bulk_download", since=SINCE_ISO, db=db)
    assert s["outcomes"] == {"new": 2, "replaced": 1, "already_had": 1}
    async with async_session() as db:
        c = await jobs.job_counts(type="download,bulk_download", since=SINCE_ISO, db=db)
    assert sum(s["outcomes"].values()) == c["completed_since"]
    assert s["bytes_added"] == 30_000_000 + 20_000_000 + 5_000_000  # already_had excluded
    assert s["pct_lossless"] == 67  # flac (track), flac (track), mp3 (filename) — already_had excluded
    assert s["played_since"] == 1  # trkN played after it finished; trkH is already_had; trkU never played

    # In scope: f-tr1, f-tr4, f-upg, f-man (the 3-day, 1-day and 40-day rows are outside `since`)
    assert s["failed"]["total"] == 4 == c["failed_since"]
    assert s["failed"]["not_found"] == 2 and s["failed"]["no_better"] == 1 and s["failed"]["peer"] == 1
    assert s["failed"]["infra"] == 0 and s["failed"]["rejected"] == 0
    assert s["failed_by_class"]["not_found"] == 2 and sum(s["failed_by_class"].values()) == 4
    assert s["next"] == {"retry": 2, "retired": 1, "none": 1}  # f-tr1 + f-upg (2 of 3) · f-tr4 · f-man
    assert sum(s["next"].values()) == s["failed"]["total"]
    assert s["last_finished"]["id"] == "c-gone"  # the newest finished_at
    assert (s["last_finished"]["artist"], s["last_finished"]["track"]) == ("G", "Gone")
    assert s["last_finished"]["status"] == "completed" and s["last_finished"]["card"] == "dl:manual"
    assert {"artist", "track", "card", "finished_at"} <= set(s["last_finished"])


async def test_summary_empty_scope(db_ready):
    async with async_session() as db:
        s = await jobs.jobs_summary(since=SINCE_ISO, db=db)
    assert s["outcomes"] == {"new": 0, "replaced": 0, "already_had": 0}
    assert s["bytes_added"] == 0 and s["pct_lossless"] is None and s["last_finished"] is None
    assert s["failed"]["total"] == 0 and s["next"] == {"retry": 0, "retired": 0, "none": 0}


async def test_summary_declared_before_job_id():
    paths = [(r.path, sorted(r.methods)) for r in jobs.router.routes]
    assert paths.index(("/summary", ["GET"])) < paths.index(("/{job_id}", ["GET"]))


# --- R1-E2: incidents ------------------------------------------------------------

async def _seed_incidents():
    restart_at = NOW - timedelta(hours=3)
    rows = [{"id": f"rs{i}", "status": "failed", "card": "dl:playlist", "finished_at": restart_at,
             "started_at": restart_at - timedelta(minutes=2),
             "result": json.dumps({"error": "Interrupted by restart"}),
             "tracks": _tracks(f"Artist {i}", "Song", status="downloading")} for i in range(5)]
    rows.append({"id": "orph", "status": "failed", "card": "dl:similar", "finished_at": NOW - timedelta(hours=1),
                 "result": None, "tracks": _tracks("Orphan", "Song", status="queued")})
    rows.append({"id": "peer", "status": "failed", "result": json.dumps({"message": "All 1 sources failed"}),
                 "tracks": _tracks("P", "S", error="Transfer stalled")})
    rows.append({"id": "old-restart", "status": "failed", "finished_at": NOW - timedelta(days=9),
                 "started_at": NOW - timedelta(days=9), "result": json.dumps({"error": "Interrupted by restart"}),
                 "tracks": _tracks("Old", "Song")})
    await seed(*rows)


async def test_incidents_list_dismiss_and_retry(db_ready, monkeypatch):
    calls = []

    async def fake_retry(items):
        calls.append(items)
    monkeypatch.setattr(jobs, "_retry_downloads", fake_retry)
    await _seed_incidents()

    async with async_session() as db:
        out = await jobs.list_incidents(type="download,bulk_download", db=db)  # default: last 7 days
    by_kind = {i["kind"]: i for i in out["items"]}
    assert set(by_kind) == {"restart", "orphan"}  # the 9-day-old restart and the peer row are not in it
    rs = by_kind["restart"]
    assert rs["count"] == 5 and rs["by_card"] == {"dl:playlist": 5} and rs["dismissed"] is False
    assert sorted(rs["job_ids"]) == [f"rs{i}" for i in range(5)]

    # Dismiss flags every member; GET shows dismissed; the class is unchanged.
    async with async_session() as db:
        assert await jobs.dismiss_incident(rs["id"], db=db) == {"dismissed": 5}
    async with async_session() as db:
        out2 = await jobs.list_incidents(db=db)
    again = {i["id"]: i for i in out2["items"]}
    assert again[rs["id"]]["dismissed"] is True and again[rs["id"]]["count"] == 5
    async with async_session() as s:
        row = await s.get(Job, "rs0")
    assert json.loads(row.result) == {"error": "Interrupted by restart", "incident_dismissed": True}

    # Dismissing the orphan keeps it an orphan (same incident id) in SQL and Python.
    orph = by_kind["orphan"]
    async with async_session() as db:
        assert await jobs.dismiss_incident(orph["id"], db=db) == {"dismissed": 1}
    async with async_session() as db:
        out3 = await jobs.list_incidents(db=db)
    assert {i["id"]: i["dismissed"] for i in out3["items"]}[orph["id"]] is True
    members = await bucket_members()
    assert "orph" in members["infra"] and "peer" in members["peer"]
    async with async_session() as db:
        assert await jobs.dismiss_incident(orph["id"], db=db) == {"dismissed": 0}  # idempotent

    # Retry deletes the members and hands their tracks to _retry_downloads.
    bt = BackgroundTasks()
    async with async_session() as db:
        resp = await jobs.retry_incident(rs["id"], bt, db=db)
    await bt()
    assert resp == {"ok": True, "jobs": 5, "tracks": 5}
    assert sorted(it["job_id"] for it in calls[0]) == [f"rs{i}" for i in range(5)]
    assert all(it["source"] == "playlist" for it in calls[0])
    assert {"rs0", "rs1"}.isdisjoint(await _ids()) and {"orph", "peer", "old-restart"} <= await _ids()

    async with async_session() as db:
        assert await jobs.retry_incident("restart:1999-01-01T00:00:00", BackgroundTasks(), db=db) == \
            {"error": "Incident not found"}
    async with async_session() as db:
        assert await jobs.dismiss_incident("nope", db=db) == {"error": "Incident not found"}


async def test_incidents_since_scope(db_ready):
    await _seed_incidents()
    async with async_session() as db:
        out = await jobs.list_incidents(since=(NOW - timedelta(days=30)).isoformat(), db=db)
    restarts = [i for i in out["items"] if i["kind"] == "restart"]
    assert sorted(i["count"] for i in restarts) == [1, 5]  # the 9-day-old batch is its own incident
    async with async_session() as db:
        out = await jobs.list_incidents(since=(NOW - timedelta(minutes=90)).isoformat(), db=db)
    assert [i["kind"] for i in out["items"]] == ["orphan"]


async def test_incident_routes_declared_before_job_id():
    paths = [(r.path, sorted(r.methods)) for r in jobs.router.routes]
    assert paths.index(("/incidents", ["GET"])) < paths.index(("/{job_id}", ["GET"]))
