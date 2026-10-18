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


# --- R2-A1: GET /api/jobs/{id}?detail=1 ----------------------------------------------

LEGACY_GET_KEYS = {"id", "type", "status", "progress", "total", "result", "log", "tracks",
                   "started_at", "finished_at"}


async def _seed_detail():
    from backend.models.download_attempt import DownloadAttempt
    from backend.services.download_attempts import attempt_key

    log = [
        {"t": "2026-10-18T07:00:00", "k": "submitted", "card": "dl:similar", "source": "similar"},
        {"t": "2026-10-18T07:00:05", "k": "query_start", "i": 1, "n": 2, "q": "bublé home", "kind": "variant"},
        {"t": "2026-10-18T07:00:30", "k": "searched", "funnel": {"files_seen": 14, "kept": 0}},
        "a stray string entry",  # not a DC-2 event: dropped from the timeline
        {"t": "2026-10-18T07:01:00", "k": "failed", "error": "No results for x", "class": "not_found"},
    ]
    result = {
        "message": "All 2 sources failed", "last_error": "Peer never answered in 120 s",
        "search": {"queries": [{"q": "bublé home", "kind": "variant", "peers": 11, "files": 23}],
                   "files_seen": 23, "kept": 2, "rejected": {"title": 21}},
        "candidates": [{"username": "dblbbr", "filename": "a.flac", "score": 58},
                       {"username": "piaga", "filename": "b.mp3", "score": 40}, "junk"],
        "source_errors": [{"user": "dblbbr", "error": "Peer never answered in 120 s", "at": "2026-10-18T07:05:00"}],
        "username": "piaga",
    }
    tracks = [{"artist": "Michael Bublé", "track": "Home", "status": "failed", "stage": "queued_at_peer",
               "stage_since": "2026-10-18T07:04:00", "attempt": 2, "of": 2, "username": "piaga",
               "error": "Peer never answered in 120 s",
               "source_errors": [{"user": "dblbbr", "error": "Peer never answered in 120 s",
                                  "at": "2026-10-18T07:05:00"},
                                 {"user": "piaga", "error": "Peer never answered in 120 s",
                                  "at": "2026-10-18T07:07:00"}]}]
    async with async_session() as s:
        s.add(DownloadAttempt(key=attempt_key("Michael Bublé", "Home"), artist="Michael Bublé", track="Home",
                              attempts=2, next_retry_at=NOW + timedelta(days=7), last_error="All 2 sources failed"))
        await s.commit()
    await seed(
        {"id": "det", "status": "failed", "card": "dl:similar", "result": json.dumps(result),
         "tracks": json.dumps(tracks), "log": json.dumps(log)},
        {"id": "det-old", "status": "failed", "card": "dl:similar", "result": json.dumps(result),
         "tracks": json.dumps(tracks), "finished_at": NOW - timedelta(days=2), "started_at": NOW - timedelta(days=2)},
        {"id": "nolog", "status": "running", "card": "dl:manual", "result": None, "log": None,
         "tracks": _tracks("N", "Nolog", status="downloading", stage="searching",
                           search={"query_index": 1, "query_total": 4, "files_seen": 3, "kept": 0})},
        {"id": "bare", "status": "failed", "card": None, "result": "not json {", "log": "nor this",
         "tracks": None},
        {"id": "upg-log", "type": "upgrade", "status": "completed", "card": None, "result": None,
         "log": json.dumps(["step one", "step two"]), "tracks": None},
    )


async def test_get_job_plain_is_legacy_plus_card(db_ready):
    await _seed_detail()
    async with async_session() as db:
        out = await jobs.get_job("det", db=db)
    outcome_keys = set(jobs.job_outcome("failed", out["result"]))
    assert set(out) == LEGACY_GET_KEYS | {"card"} | outcome_keys
    assert out["card"] == "dl:similar"
    assert isinstance(out["result"], str) and isinstance(out["tracks"], str) and isinstance(out["log"], str)
    assert isinstance(out["progress"], int) and isinstance(out["total"], int)
    assert out["failed_sources"] == ["piaga"] and isinstance(out["error"], str)
    for k in ("timeline", "peers", "ledger", "failure_class", "result_json"):
        assert k not in out


async def test_get_job_detail_adds_parsed_siblings(db_ready, fake_slsk):
    await _seed_detail()
    rep = fake_slsk.reputation
    for _ in range(9):
        await rep.record_success("dblbbr")
    for _ in range(3):
        await rep.record_failure("piaga")
    rep.scores["dblbbr"] = 10
    rep.scores["piaga"] = -14
    rep.recent.add("piaga")

    async with async_session() as db:
        plain = await jobs.get_job("det", db=db)
    async with async_session() as db:
        out = await jobs.get_job("det", detail=True, db=db)
    # Every plain key, same value and type.
    assert {k: out[k] for k in plain} == plain

    assert out["result_json"]["message"] == "All 2 sources failed"
    assert out["tracks_json"][0]["artist"] == "Michael Bublé"
    assert [e["k"] for e in out["timeline"]] == ["submitted", "query_start", "searched", "failed"]
    assert out["search"]["files_seen"] == 23
    assert [c["username"] for c in out["candidates"]] == ["dblbbr", "piaga"]  # non-dicts dropped
    assert [e["user"] for e in out["source_errors"]] == ["dblbbr", "piaga"]  # live tracks[0] list wins
    assert out["failure_class"] == "peer"
    assert (out["stage"], out["stage_since"]) == ("queued_at_peer", "2026-10-18T07:04:00")
    assert (out["attempt"], out["of"]) == (2, 2)
    assert out["ledger"]["attempts"] == 2 and out["ledger"]["retired"] is False
    assert out["next"]["kind"] == "retry" and out["next"]["attempts"] == 2
    assert out["times_failed_30d"] == 2  # itself + det-old
    assert out["outcome"] is None and out["track"] is None and out["upgrade"] is None
    assert out["peers"] == {
        "dblbbr": {"successes": 9, "failures": 0, "score": 10, "recent_failure": False},
        "piaga": {"successes": 0, "failures": 3, "score": -14, "recent_failure": True},
    }


async def test_get_job_detail_null_and_malformed_columns(db_ready, fake_slsk):
    await _seed_detail()
    async with async_session() as db:
        out = await jobs.get_job("nolog", detail=True, db=db)
    assert out["timeline"] == [] and out["result_json"] is None and out["candidates"] == []
    assert out["search"] == {"query_index": 1, "query_total": 4, "files_seen": 3, "kept": 0}
    assert out["stage"] == "searching" and out["failure_class"] is None
    assert out["peers"] == {} and out["next"]["kind"] == "none" and out["card"] == "dl:manual"

    async with async_session() as db:
        out = await jobs.get_job("bare", detail=True, db=db)
    assert out["timeline"] == [] and out["result_json"] is None and out["tracks_json"] is None
    assert out["failure_class"] == "orphan" and out["source_errors"] == [] and out["card"] is None

    # A non-download job: its own log shape is not a DC-2 timeline; no joins.
    async with async_session() as db:
        out = await jobs.get_job("upg-log", detail=True, db=db)
    assert out["timeline"] == [] and out["log"] == json.dumps(["step one", "step two"])
    assert out["ledger"] is None and out["peers"] == {}


async def test_get_job_detail_without_client(db_ready, monkeypatch):
    import backend.soulseek as soulseek
    monkeypatch.setattr(soulseek, "get_client", lambda: None)
    await _seed_detail()
    async with async_session() as db:
        out = await jobs.get_job("det", detail=True, db=db)
    assert out["peers"] == {} and out["ledger"]["attempts"] == 2
    async with async_session() as db:
        assert await jobs.get_job("missing", detail=True, db=db) == {"error": "Job not found"}


# --- R2-B5: GET /failed-tracks and GET /runs -----------------------------------------

async def _seed_failed_tracks():
    from backend.models.download_attempt import DownloadAttempt
    from backend.services.download_attempts import attempt_key

    nf = json.dumps({"message": "No results for Rep - Eat"})
    stalled = json.dumps({"message": "All 1 sources failed", "last_error": "Transfer stalled",
                          "source_errors": [{"user": "u9", "error": "Transfer stalled"}]})
    async with async_session() as s:
        s.add(DownloadAttempt(key=attempt_key("Rep", "Eat"), artist="Rep", track="Eat", attempts=3,
                              next_retry_at=NOW + timedelta(days=30)))
        await s.commit()
    await seed(
        # One track failing three times (case and spacing differ; same attempt_key).
        {"id": "rep1", "status": "failed", "card": "dl:similar", "result": nf, "tracks": _tracks("Rep", "Eat"),
         "finished_at": NOW - timedelta(hours=3)},
        {"id": "rep2", "status": "failed", "card": "dl:similar", "result": nf, "tracks": _tracks("rep", "eat"),
         "finished_at": NOW - timedelta(hours=2)},
        {"id": "rep3", "status": "failed", "card": "dl:similar", "result": stalled,
         "tracks": _tracks("Rep", "Eat ", error="Transfer stalled",
                           source_errors=[{"user": "u9", "error": "Transfer stalled", "at": "x"}]),
         "finished_at": NOW - timedelta(hours=1)},
        {"id": "nf1", "status": "failed", "card": "dl:discovery", "result": nf, "tracks": _tracks("Solo", "Once")},
        {"id": "rs1", "status": "failed", "card": "dl:playlist", "result": json.dumps({"error": "Interrupted by restart"}),
         "tracks": _tracks("Re", "Start", status="downloading")},
        {"id": "cx1", "status": "failed", "card": "dl:manual", "result": json.dumps({"error": "Cancelled by user"}),
         "tracks": _tracks("Can", "Celled")},
        {"id": "notrack", "status": "failed", "card": "dl:manual", "result": nf, "tracks": None},
        {"id": "ok1", "status": "completed", "card": "dl:similar", "result": json.dumps({"track_id": "t"}),
         "tracks": json.dumps([{"artist": "Fine", "track": "Song", "status": "downloaded"}])},
        {"id": "old", "status": "failed", "card": "dl:similar", "result": nf, "tracks": _tracks("Rep", "Eat"),
         "finished_at": OLD, "started_at": OLD},  # outside SINCE
    )


async def test_failed_tracks_collapse_per_track(db_ready):
    await _seed_failed_tracks()
    async with async_session() as db:
        out = await jobs.failed_tracks(type="download,bulk_download", since=SINCE_ISO, db=db)
    items = out["items"]
    by_key = {(i["artist"], i["track"]): i for i in items}

    rep = next(i for i in items if i["count"] == 3)
    assert sorted(rep["job_ids"]) == ["rep1", "rep2", "rep3"]
    assert rep["last_job"]["id"] == "rep3" and rep["class"] == "peer"  # the newest row decides
    assert rep["times_failed_30d"] == 4  # three in scope + the 2-day-old row (30-day window)
    assert rep["last_job"]["message"] == "All 1 sources failed"
    assert rep["last_job"]["source_errors"][0]["user"] == "u9"
    assert rep["ledger"]["attempts"] == 3 and rep["next"]["kind"] == "retry"
    assert rep["attempt_key"] and rep["card"] == "dl:similar"

    assert by_key[("Solo", "Once")]["class"] == "not_found"
    assert by_key[("Solo", "Once")]["next"]["kind"] == "none"
    assert by_key[("Re", "Start")]["class"] == "infra" and by_key[("Re", "Start")]["times_failed_30d"] == 0
    assert by_key[("Can", "Celled")]["class"] == "cancelled"
    lone = next(i for i in items if i["attempt_key"] is None)
    assert lone["job_ids"] == ["notrack"] and lone["class"] == "not_found"
    assert len(items) == 5  # completed row and out-of-scope row excluded

    # Pipeline order: peer, not_found (2), then infra-bucket entries.
    assert [i["class"] for i in items][:3] == ["peer", "not_found", "not_found"]
    assert {i["class"] for i in items[3:]} == {"infra", "cancelled"}

    t = out["totals"]
    assert t["retry"] + t["retired"] + t["none"] == len(items)
    assert t["retry"] == 1 and t["by_class"] == {"peer": 1, "not_found": 2, "infra": 1, "cancelled": 1}
    assert sum(i["count"] for i in items) == 7

    # class filter: a class, or a bucket name.
    async with async_session() as db:
        nf = await jobs.failed_tracks(since=SINCE_ISO, cls="not_found", db=db)
    assert {i["class"] for i in nf["items"]} == {"not_found"} and nf["totals"]["by_class"] == {"not_found": 2}
    async with async_session() as db:
        infra = await jobs.failed_tracks(since=SINCE_ISO, cls="infra", db=db)
    assert {i["class"] for i in infra["items"]} == {"infra", "cancelled"}


async def test_failed_tracks_sorted_by_times_failed_inside_class(db_ready):
    nf = json.dumps({"message": "No results for x"})
    await seed(
        {"id": "a1", "status": "failed", "result": nf, "tracks": _tracks("A", "One")},
        {"id": "b1", "status": "failed", "result": nf, "tracks": _tracks("B", "Two")},
        {"id": "b2", "status": "failed", "result": nf, "tracks": _tracks("B", "Two"),
         "finished_at": NOW - timedelta(minutes=3)},
    )
    async with async_session() as db:
        out = await jobs.failed_tracks(db=db)
    assert [(i["artist"], i["times_failed_30d"]) for i in out["items"]] == [("B", 2), ("A", 1)]


def _batched(artist, batch, status="downloaded"):
    return json.dumps([{"artist": artist, "track": "S", "status": status, "batch": batch}])


async def test_runs_group_by_batch_then_card_gap(db_ready):
    t0 = NOW - timedelta(hours=5)
    pl = {"id": "b-1", "label": "Road Trip", "kind": "playlist"}
    nf = json.dumps({"message": "No results for x"})
    await seed(
        # A stamped playlist batch: two done (one already had), one not found, one live.
        {"id": "p1", "status": "completed", "card": "dl:playlist", "result": json.dumps({"track_id": "x"}),
         "tracks": _batched("P1", pl), "started_at": t0, "finished_at": t0 + timedelta(minutes=2)},
        {"id": "p2", "status": "completed", "card": "dl:playlist",
         "result": json.dumps({"already_in_library": True}), "tracks": _batched("P2", pl),
         "started_at": t0 + timedelta(minutes=1), "finished_at": t0 + timedelta(minutes=3)},
        {"id": "p3", "status": "failed", "card": "dl:playlist", "result": nf,
         "tracks": _batched("P3", pl, "failed"), "started_at": t0 + timedelta(minutes=50),  # no gap split in a batch
         "finished_at": t0 + timedelta(minutes=51)},
        {"id": "p4", "status": "running", "card": "dl:playlist", "result": None,
         "tracks": _batched("P4", pl, "downloading"), "started_at": t0 + timedelta(minutes=52)},
        # Unstamped similar rows: 0, +10 min (same run), +45 min (25 min after the last finish: new run).
        {"id": "s1", "status": "completed", "card": "dl:similar", "result": json.dumps({"track_id": "y"}),
         "tracks": _tracks("S1", "x", status="downloaded"), "started_at": t0, "finished_at": t0 + timedelta(minutes=5)},
        {"id": "s2", "status": "failed", "card": "dl:similar", "result": json.dumps({"error": "Interrupted by restart"}),
         "tracks": _tracks("S2", "x"), "started_at": t0 + timedelta(minutes=10),
         "finished_at": t0 + timedelta(minutes=20)},
        {"id": "s3", "status": "failed", "card": "dl:similar",
         "result": json.dumps({"message": "All 1 sources failed"}), "tracks": _tracks("S3", "x"),
         "started_at": t0 + timedelta(minutes=45), "finished_at": t0 + timedelta(minutes=46)},
        # A 15-minute gap after the last activity stays in the same run.
        {"id": "s4", "status": "completed", "card": "dl:similar", "result": json.dumps({"track_id": "z"}),
         "tracks": _tracks("S4", "x", status="downloaded"), "started_at": t0 + timedelta(minutes=61),
         "finished_at": t0 + timedelta(minutes=62)},
        # Another card at the same time is its own run.
        {"id": "m1", "status": "failed", "card": "dl:manual", "result": nf, "tracks": _tracks("M", "x"),
         "started_at": t0 + timedelta(minutes=1), "finished_at": t0 + timedelta(minutes=2)},
    )
    async with async_session() as db:
        out = await jobs.download_runs(type="download,bulk_download", db=db)
    runs = out["items"]
    by_first = {r["job_ids"][0]: r for r in runs}
    assert len(runs) == 4

    b = by_first["p1"]
    assert b["id"] == "b-1" and b["label"] == "Road Trip" and b["kind"] == "playlist" and b["card"] == "dl:playlist"
    assert b["job_ids"] == ["p1", "p2", "p3", "p4"]
    assert b["counts"] == {"total": 4, "new": 1, "replaced": 0, "already_had": 1, "not_found": 1, "peer": 0,
                           "rejected": 0, "no_better": 0, "infra": 0, "live": 1}
    assert b["start"] == t0.isoformat()

    first = by_first["s1"]
    assert first["job_ids"] == ["s1", "s2"] and first["kind"] is None and first["label"] == "Similar"
    assert first["counts"]["new"] == 1 and first["counts"]["infra"] == 1 and first["counts"]["total"] == 2
    assert first["id"] == f"dl:similar@{t0.isoformat()}"
    assert first["end"] == (t0 + timedelta(minutes=20)).isoformat()
    second = by_first["s3"]
    assert second["job_ids"] == ["s3", "s4"] and second["counts"]["peer"] == 1 and second["counts"]["new"] == 1

    assert by_first["m1"]["label"] == "Manual" and by_first["m1"]["counts"]["not_found"] == 1
    # Newest first.
    assert [r["start"] for r in runs] == sorted((r["start"] for r in runs), reverse=True)

    # Ids are stable across reloads.
    async with async_session() as db:
        again = await jobs.download_runs(type="download,bulk_download", db=db)
    assert [r["id"] for r in again["items"]] == [r["id"] for r in runs]


async def test_runs_and_failed_tracks_respect_since(db_ready):
    nf = json.dumps({"message": "No results for x"})
    await seed({"id": "o", "status": "failed", "result": nf, "tracks": _tracks("O", "x"),
                "started_at": OLD, "finished_at": OLD})
    async with async_session() as db:
        assert (await jobs.download_runs(since=SINCE_ISO, db=db))["items"] == []
    async with async_session() as db:
        out = await jobs.failed_tracks(since=SINCE_ISO, db=db)
    assert out == {"items": [], "totals": {"retry": 0, "retired": 0, "none": 0, "by_class": {}}}


async def test_failed_tracks_and_runs_declared_before_job_id():
    paths = [(r.path, sorted(r.methods)) for r in jobs.router.routes]
    for p in ("/failed-tracks", "/runs"):
        assert paths.index((p, ["GET"])) < paths.index(("/{job_id}", ["GET"]))


async def test_query_params_over_http(db_ready):
    """`?detail=1` and `?class=` parse through FastAPI (direct calls above bypass it)."""
    import httpx
    from fastapi import FastAPI

    await _seed_failed_tracks()
    app = FastAPI()
    app.include_router(jobs.router, prefix="/api/jobs")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        plain = (await c.get("/api/jobs/rep3")).json()
        detail = (await c.get("/api/jobs/rep3", params={"detail": "1"})).json()
        nf = (await c.get("/api/jobs/failed-tracks", params={"class": "not_found"})).json()
        runs = (await c.get("/api/jobs/runs")).json()
    assert "timeline" not in plain and plain["card"] == "dl:similar"
    assert detail["timeline"] == [] and detail["failure_class"] == "peer" and detail["times_failed_30d"] == 4
    assert nf["items"] and {i["class"] for i in nf["items"]} == {"not_found"}
    assert runs["items"]
