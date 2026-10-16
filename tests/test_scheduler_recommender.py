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
    assert da.attempt_key("Beyoncé feat. Jay-Z", "Halo (Remastered 2014)") == da.attempt_key("beyoncé", "HALO")
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
