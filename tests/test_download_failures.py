"""Failure classifier (backend/services/download_failures.py): one class per failed
download row, over every result/tracks shape Zonik writes.

Run: uv run --with pytest --with pytest-asyncio pytest tests/test_download_failures.py
"""
import json

import pytest

from backend.services import download_failures as df
from backend.services.auto_download import is_infra_error

NATIVE = ("Soulseek native client not available (not logged in); "
          "slskd fallback is decommissioned")


def _r(**kw) -> str:
    return json.dumps(kw)


def _t(error: str | None = None, **kw) -> str:
    row = {"artist": "A", "track": "T", "status": "failed", **kw}
    if error is not None:
        row["error"] = error
    return json.dumps([row])


CASES = [
    # (id, status, result_json, tracks_json, class)
    ("cancelled", "failed", _r(error="Cancelled by user"), None, "cancelled"),
    ("restart", "failed", _r(error="Interrupted by restart"), None, "infra"),
    ("restart-timeout", "failed", _r(error="Interrupted by restart or job timeout"), None, "infra"),
    ("not-connected", "failed", _r(error="Soulseek server not connected — try again later"),
     _t("Soulseek server not connected"), "infra"),
    ("unreachable", "failed", _r(error="Soulseek download backend unreachable: x"), None, "infra"),
    ("internal", "failed", _r(error="Internal error: database is locked"), None, "infra"),
    ("native-client", "failed", _r(status="error", message=NATIVE), None, "infra"),
    ("null-result", "failed", None, None, "orphan"),
    ("unparseable", "failed", "Interrupted", None, "orphan"),
    ("non-object", "failed", json.dumps(["x"]), None, "orphan"),
    ("no-results", "failed", _r(message="No results for A - T"), None, "not_found"),
    ("no-other", "failed", _r(message="No other sources for A - T"), None, "not_found"),
    ("no-better", "failed", _r(message="No source better than the current mp3 for A - T"), None, "no_better"),
    ("all-failed-rejected", "failed",
     _r(message="All 2 sources failed", last_error="Not imported: not better than the copy you have",
        failed_sources=["u1", "u2"]),
     _t("Not imported: not better than the copy you have"), "rejected"),
    ("all-failed-legacy-rejected", "failed",
     _r(message="All 1 sources failed", last_error="x"),
     _t("Import rejected — empty, truncated, or unreadable"), "rejected"),
    ("all-failed-peer", "failed",
     _r(message="All 2 sources failed", last_error="Peer did not respond in time"),
     _t("Peer did not respond in time"), "peer"),
    ("parallel-not-imported", "failed",
     _r(message="Not imported: wrong song", username="u1", filename="f.flac", strategy="first"),
     None, "rejected"),
    ("parallel-all-failed", "failed",
     _r(message="All 3 parallel sources failed", last_error="Transfer stalled"), None, "peer"),
    ("completed", "completed", _r(track_id="t1"), None, None),
    ("completed-no-result", "completed", None, None, None),
    ("running", "running", None, None, None),
    ("pending", "pending", None, None, None),
]


@pytest.mark.parametrize("status,result_json,tracks_json,expected",
                         [c[1:] for c in CASES], ids=[c[0] for c in CASES])
def test_failure_class(status, result_json, tracks_json, expected):
    assert df.failure_class(status, result_json, tracks_json) == expected


@pytest.mark.parametrize("status,result_json,tracks_json,expected",
                         [c[1:] for c in CASES], ids=[c[0] for c in CASES])
def test_bucket_is_bucket_of_class(status, result_json, tracks_json, expected):
    bucket = df.failure_bucket(status, result_json, tracks_json)
    if expected is None:
        assert bucket is None
    else:
        assert bucket == df.BUCKET_OF_CLASS[expected]
        assert bucket in df.BUCKETS


def test_earlier_rejection_in_source_errors_does_not_make_a_timeout_rejected():
    result = _r(message="All 2 sources failed", last_error="Peer did not respond in time",
                source_errors=[{"user": "u1", "error": "Not imported: wrong song"},
                               {"user": "u2", "error": "Peer did not respond in time"}])
    tracks = _t("Peer did not respond in time")
    assert df.failure_class("failed", result, tracks) == "peer"


def test_cancel_wins_over_other_text():
    # The finally-block cancel overwrites the result: cancelled, never infra or peer.
    assert df.failure_class("failed", _r(error="Cancelled by user"),
                            _t("Not imported: wrong song")) == "cancelled"


def test_peer_refusal_reason_is_not_cancelled():
    # "Cancelled" is a standard Soulseek denial from the peer: a real track failure.
    assert df.failure_class("failed", _r(message="All 1 sources failed", last_error="Cancelled"),
                            _t("Cancelled")) == "peer"


def test_unparseable_tracks_is_ignored():
    assert df.failure_class("failed", _r(message="All 1 sources failed"), "{not json") == "peer"
    assert df.failure_class("failed", _r(message="All 1 sources failed"), json.dumps([])) == "peer"


def test_buckets_and_labels_cover_every_class():
    assert set(df.BUCKET_OF_CLASS) == set(df.CLASS_LABELS)
    assert set(df.BUCKET_OF_CLASS.values()) == set(df.BUCKETS)
    for cls in ("cancelled", "infra", "orphan"):
        assert df.BUCKET_OF_CLASS[cls] == "infra"


def test_every_infra_message_matches_an_infra_pattern():
    # The SQL filter (result LIKE '%pattern%') must catch every message that
    # is_infra_error accepts, or the SQL bucket and the Python class disagree.
    messages = ["Cancelled by user", "Interrupted by restart", "Interrupted by restart or job timeout",
                "Soulseek server not connected — try again later",
                "Soulseek download backend unreachable: web returned 502",
                "Internal error: database is locked", NATIVE]
    for m in messages:
        assert is_infra_error(m), m
        assert any(p in m for p in df.INFRA_PATTERNS), m


@pytest.mark.parametrize("text,kind", [
    ("Interrupted by restart", "restart"),
    ("Interrupted by restart or job timeout", "restart"),
    ('{"error": "Interrupted by restart"}', "restart"),
    ("Soulseek server not connected — try again later", "outage"),
    (NATIVE, "outage"),
    ("Cancelled by user", "cancel"),
    ("Internal error: database is locked", "internal"),
    ("Soulseek download backend unreachable: connection refused", "unreachable"),
    ("", "orphan"),
    (None, "orphan"),
    ("   ", "orphan"),
])
def test_incident_kind(text, kind):
    assert df.incident_kind(text) == kind


def test_module_is_pure():
    # Importable and callable without a database: synchronous functions only.
    import inspect
    for fn in (df.failure_class, df.failure_bucket, df.incident_kind):
        assert not inspect.iscoroutinefunction(fn)
