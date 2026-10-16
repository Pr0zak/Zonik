"""Pure-logic tests for the download backoff, engagement feedback and score renormalisation."""
from datetime import datetime, timedelta
from types import SimpleNamespace

from backend.config import AssistantConfig
from backend.models.download_attempt import DownloadAttempt
from backend.services import download_attempts as da
from backend.services.recommender import (
    compute_engagement, engagement_multiplier, score_candidate, weighted_score,
)


def test_attempt_key_normalises_like_library_match():
    assert da.attempt_key("Beyoncé feat. Jay-Z", "Halo") == da.attempt_key("beyoncé", "HALO")
    assert da.attempt_key("A, B", "Song") == da.attempt_key("a", "song")
    assert "::" in da.attempt_key("x", "y")


def test_backoff_schedule():
    assert [da.backoff_days(n) for n in (1, 2, 3)] == [1, 7, 30]
    assert da.backoff_days(0) == 0
    assert da.backoff_days(4) == 365
    assert not da.is_retired(3) and da.is_retired(4)


def test_reason_for_window():
    now = datetime.utcnow()
    row = DownloadAttempt(key="a::b", artist="a", track="b", attempts=2, next_retry_at=now + timedelta(days=3))
    assert "backoff" in da.reason_for(row, now)
    row.next_retry_at = now - timedelta(seconds=1)
    assert da.reason_for(row, now) is None
    row.attempts, row.next_retry_at = 4, now + timedelta(days=300)
    assert "retired" in da.reason_for(row, now)


def test_engagement_multiplier_formula():
    assert engagement_multiplier(5, 9, 10) == 1.0          # too few samples
    assert engagement_multiplier(0, 10, 10) == 0.6
    assert engagement_multiplier(10, 10, 10) == 1.4
    assert engagement_multiplier(5, 10, 10) == 1.0
    assert engagement_multiplier(1, 2, 2) == 1.0


def test_compute_engagement_source_and_artist():
    rows = [("similar_track", "good", True, 40)] * 8 + [("similar_track", "meh", False, 40)] * 2
    src, art = compute_engagement(rows)
    assert src["similar_track"] == round(0.6 + 0.8 * 0.8, 3)
    assert art["good"] == 1.4
    assert art["meh"] == 0.6


def test_compute_engagement_stale_unplayed_single():
    src, art = compute_engagement([("tag", "old", False, 45), ("tag", "fresh", False, 5)])
    assert src == {}
    assert art == {"old": 0.7}


def test_weighted_score_renormalised():
    cfg = AssistantConfig()
    # All live signals at 1.0 must reach exactly 1.0 (previously capped at 0.75).
    assert abs(weighted_score(cfg, 1, 1, 1, 1, 1) - 1.0) < 1e-9
    assert weighted_score(cfg, 0, 0, 0, 0, 0) == 0.0
    # Ignores the dead weights even when configured.
    cfg2 = AssistantConfig(w_audio_match=5.0, w_clap_similarity=5.0)
    assert abs(weighted_score(cfg2, 1, 1, 1, 1, 1) - 1.0) < 1e-9


def test_score_candidate_reports_dead_terms_as_zero():
    score, bd = score_candidate(
        {"artist": "Nobody", "track": "x", "source": "trending", "lastfm_listeners": 1_000_000, "lastfm_match": 1.0},
        {"favorite_artists": [], "top_artists": [], "genre_distribution": {}, "audio": {"avg_bpm": 120}},
    )
    assert bd["audio_match"] == 0.0 and bd["clap_similarity"] == 0.0
    # lastfm 0.20 + popularity 0.05 + novelty 0.05 over a 0.75 total weight
    assert score == round(0.30 / 0.75, 3)


# --- review fixes -----------------------------------------------------------------

def test_attempt_key_keeps_version_suffix_and_handles_non_latin():
    assert da.attempt_key("A", "Song (X Remix)") != da.attempt_key("A", "Song")
    assert da.attempt_key("A", "Song [Live]") != da.attempt_key("A", "Song (Remix)")
    k1, k2 = da.attempt_key("中文", "歌曲"), da.attempt_key("日本", "曲")
    assert k1 != k2 and k1 != "::"


def test_library_match_strict_title():
    from backend.services.library_match import norm_title, norm_title_strict
    assert norm_title("Song (X Remix)") == norm_title("Song")
    assert norm_title_strict("Song (X Remix)") == "songxremix"


def test_retry_delay_has_slack():
    assert da.retry_delay(1) == timedelta(days=1) - timedelta(hours=6)
    assert da.retry_delay(4) < timedelta(days=365)


def test_fresh_unplayed_downloads_do_not_count():
    rows = [("tag", "newbie", False, 1)] * 12 + [("tag", "newbie", False, 3)] * 2
    assert compute_engagement(rows) == ({}, {})
    # played rows count at any age
    src, art = compute_engagement([("tag", "x", True, 1)] * 10)
    assert src["tag"] == 1.4 and art["x"] == 1.4


def test_chart_gate_realistic_profile():
    profile = {
        "favorite_artists": ["Radiohead", "Muse"],
        "top_artists": [{"name": "Radiohead", "plays": 200}, {"name": "Coldplay", "plays": 80}],
        "genre_distribution": {"alternative rock": 0.35, "electronic": 0.2, "indie": 0.15},
        "audio": {"avg_bpm": 118},
    }
    threshold = AssistantConfig().chart_min_score
    fav, _ = score_candidate(
        {"artist": "Radiohead", "track": "x", "source": "trending", "source_detail": "Last.fm trending",
         "lastfm_listeners": 800_000, "lastfm_match": 0.0, "tags": ["alternative rock", "indie"]}, profile)
    other, _ = score_candidate(
        {"artist": "Some Pop Star", "track": "y", "source": "trending", "source_detail": "Last.fm trending",
         "lastfm_listeners": 900_000, "lastfm_match": 0.0, "tags": ["pop", "dance pop"]}, profile)
    assert fav >= threshold > other


def _fake_session(row):
    class _Res:
        def first(self):
            return row

    class _Sess:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, *a, **k):
            return _Res()

    return lambda: _Sess()


def test_download_job_outcome(monkeypatch):
    import asyncio
    import json as _json
    from backend.workers import scheduler

    def outcome(row, job_id="j"):
        monkeypatch.setattr(scheduler, "async_session", _fake_session(row))
        return asyncio.run(scheduler._download_job_outcome(job_id))

    assert outcome(None, job_id=None) == (True, None)  # library already has it
    assert outcome(("completed", _json.dumps({"track_id": "t1"})))[0] is True
    assert outcome(("completed", _json.dumps({"already_in_library": True})))[0] is True
    ok, err = outcome(("failed", _json.dumps({"message": "No results for x"})))
    assert ok is False and "No results" in err
    for msg in ("Soulseek backend unreachable", "Soulseek server not connected", "Cancelled by user"):
        ok, err = outcome(("failed", _json.dumps({"error": msg})))
        assert ok is None and err == msg
    assert outcome(("running", None)) == (None, None)
    assert outcome(None)[0] is False  # job row missing
