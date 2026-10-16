"""CLAP similarity on iTunes previews: scoring maths, explanation text and the cache path
(fetch + embed stubbed, cache in an in-memory SQLite)."""
import logging
import os
from datetime import datetime, timedelta

import httpx
import numpy as np
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.config import AssistantConfig, get_settings
from backend.models.preview_embedding import PreviewEmbedding
from backend.services import embeddings as emb_mod
from backend.services import recommender as rec
from backend.services.recommender import (
    _generate_explanation, apply_clap_similarity, clap_cosine, weighted_score,
)


def _unit(seed: int) -> np.ndarray:
    v = np.random.default_rng(seed).standard_normal(512).astype(np.float32)
    return v / np.linalg.norm(v)


# --- scoring maths ----------------------------------------------------------------

def test_weighted_score_without_clap_is_unchanged():
    cfg = AssistantConfig()
    assert abs(weighted_score(cfg, 1, 1, 1, 1, 1) - 1.0) < 1e-9
    # lastfm 0.20 + popularity 0.05 over 0.75
    assert abs(weighted_score(cfg, 0, 0, 1, 1, 0) - 0.25 / 0.75) < 1e-9


def test_weighted_score_with_clap_renormalises():
    cfg = AssistantConfig()
    assert abs(weighted_score(cfg, 1, 1, 1, 1, 1, clap_similarity=1.0) - 1.0) < 1e-9
    assert weighted_score(cfg, 0, 0, 0, 0, 0, clap_similarity=0.0) == 0.0
    # clap 0.10 out of 0.85 total
    assert abs(weighted_score(cfg, 0, 0, 0, 0, 0, clap_similarity=1.0) - 0.10 / 0.85) < 1e-9
    # negative cosine counts as 0, >1 is clamped
    assert weighted_score(cfg, 0, 0, 0, 0, 0, clap_similarity=-0.4) == 0.0
    # audio_match still ignored, clap weight honoured
    cfg2 = AssistantConfig(w_audio_match=5.0, w_clap_similarity=0.75)
    assert abs(weighted_score(cfg2, 0, 0, 0, 0, 0, clap_similarity=1.0) - 0.5) < 1e-9


def test_clap_cosine():
    a, b = _unit(1), _unit(2)
    assert abs(clap_cosine(a.tobytes(), a.tobytes()) - 1.0) < 1e-6
    # unnormalised centroid: cosine is scale-invariant
    assert abs(clap_cosine(a.tobytes(), (a * 0.3).tobytes()) - 1.0) < 1e-6
    assert abs(clap_cosine(a, b) - float(np.dot(a, b))) < 1e-6
    assert clap_cosine(a.tobytes(), np.zeros(512, np.float32).tobytes()) is None
    assert clap_cosine(a.tobytes(), b"\x00" * 12) is None
    assert clap_cosine(b"\x00" * 13, a.tobytes()) is None


def test_apply_clap_similarity_rescores_and_keeps_multipliers():
    cfg = AssistantConfig()
    bd = {"artist_affinity": 0.0, "genre_match": 0.0, "lastfm_similar": 1.0, "popularity": 0.0,
          "novelty": 1.0, "audio_match": 0.0, "clap_similarity": 0.0}
    c = {"score": round(0.25 / 0.75, 3), "breakdown": dict(bd)}
    apply_clap_similarity(c, 0.8, cfg)
    assert c["breakdown"]["clap_similarity"] == 0.8
    assert c["score"] == round((0.20 + 0.05 + 0.10 * 0.8) / 0.85, 3)

    c2 = {"score": 0.0, "breakdown": {**bd, "feedback_multiplier": 1.2, "engagement_artist_multiplier": 0.6,
                                      "engagement_source_multiplier": 0.5}}
    apply_clap_similarity(c2, 0.8, cfg)
    # thumbs override the artist engagement multiplier; the source multiplier always applies
    base = round((0.20 + 0.05 + 0.08) / 0.85, 3)
    assert c2["score"] == round(base * 1.2 * 0.5, 3)


def test_apply_clap_similarity_leaves_claude_score():
    c = {"score": 0.91, "breakdown": {"claude_score": 0.91}}
    apply_clap_similarity(c, 0.123456, AssistantConfig())
    assert c["score"] == 0.91 and c["breakdown"]["clap_similarity"] == 0.123


def test_explanation_mentions_strong_clap():
    cand = {"source": "trending"}
    base = {"artist_affinity": 0.0, "genre_match": 0.0, "lastfm_similar": 0.0, "popularity": 0.4,
            "novelty": 0.0, "audio_match": 0.0}
    strong = _generate_explanation(cand, {**base, "clap_similarity": 0.6})
    assert strong == "Currently trending on Last.fm. widely popular. sounds like what you play"
    weak = _generate_explanation(cand, {**base, "clap_similarity": 0.59})
    assert "sounds like" not in weak and "widely popular" in weak
    # a strong clap term doesn't hide the strongest other signal
    only = _generate_explanation({"source": "x"}, {**base, "popularity": 0.0, "clap_similarity": 0.9})
    assert only == "sounds like what you play"


# --- cache path -------------------------------------------------------------------

@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(PreviewEmbedding.__table__.create)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


def _cand(url, **bd):
    breakdown = {"artist_affinity": 0.0, "genre_match": 0.0, "lastfm_similar": 0.5, "popularity": 0.0,
                 "novelty": 1.0, "audio_match": 0.0, "clap_similarity": 0.0, **bd}
    return {"artist": "a", "track": url, "preview_url": url, "score": 0.0, "breakdown": breakdown}


@pytest.fixture
def stubs(monkeypatch):
    calls = {"embed": [], "available": 0, "unload": 0}
    state = {"available": True, "loaded": False, "vectors": {}}

    async def fake_embed(urls):
        calls["embed"].append(list(urls))
        return {u: state["vectors"][u] for u in urls if u in state["vectors"]}

    def fake_available():
        calls["available"] += 1
        return state["available"]

    def fake_unload():
        calls["unload"] += 1

    monkeypatch.setattr(rec, "_embed_previews", fake_embed)
    monkeypatch.setattr(emb_mod, "clap_model_available", fake_available)
    monkeypatch.setattr(emb_mod, "clap_model_loaded", lambda: state["loaded"])
    monkeypatch.setattr(emb_mod, "unload_clap_model", fake_unload)
    return calls, state


@pytest.mark.asyncio
async def test_cache_hit_and_miss(db, stubs):
    calls, state = stubs
    centroid = _unit(7)
    db.add(PreviewEmbedding(preview_url="u1", embedding=centroid.tobytes(), created_at=datetime.utcnow()))
    db.add(PreviewEmbedding(preview_url="old", embedding=centroid.tobytes(),
                            created_at=datetime.utcnow() - timedelta(days=365)))
    await db.commit()
    state["vectors"] = {"u2": _unit(8).tobytes()}  # u3's embed fails

    cands = [_cand("u1"), _cand("u2"), _cand("u3"), {"artist": "x", "track": "no preview", "score": 0.1,
                                                     "breakdown": {}}]
    stats = await rec.score_previews_with_clap(db, cands, (centroid * 0.5).tobytes())

    assert calls["embed"] == [["u2", "u3"]]  # cached u1 not re-embedded
    assert calls["unload"] == 1  # model wasn't resident before, so it is dropped again
    assert stats == {"scored": 2, "cached": 1, "embedded": 1, "failed": 1}
    assert cands[0]["breakdown"]["clap_similarity"] == 1.0
    assert cands[0]["score"] == round((0.20 * 0.5 + 0.05 + 0.10) / 0.85, 3)
    assert cands[1]["breakdown"]["clap_similarity"] == round(float(np.dot(_unit(8), centroid)), 3)
    assert cands[2]["breakdown"]["clap_similarity"] == 0.0 and cands[2]["score"] == 0.0
    assert "clap_similarity" not in cands[3]["breakdown"]

    urls = set((await db.execute(select(PreviewEmbedding.preview_url))).scalars())
    assert urls == {"u1", "u2"}  # u2 cached, the year-old row pruned

    # second refresh: everything that embedded is cached, the model isn't touched
    calls["embed"].clear()
    calls["available"] = 0
    again = [_cand("u1"), _cand("u2")]
    stats = await rec.score_previews_with_clap(db, again, centroid.tobytes())
    assert calls["embed"] == [] and calls["available"] == 0
    assert stats["scored"] == 2 and stats["cached"] == 2


@pytest.mark.asyncio
async def test_model_unavailable_uses_cache_only(db, stubs):
    calls, state = stubs
    state["available"] = False
    centroid = _unit(3)
    db.add(PreviewEmbedding(preview_url="u1", embedding=centroid.tobytes(), created_at=datetime.utcnow()))
    await db.commit()
    cands = [_cand("u1"), _cand("u2")]
    stats = await rec.score_previews_with_clap(db, cands, centroid.tobytes())
    assert calls["embed"] == [] and calls["unload"] == 0
    assert stats["scored"] == 1 and cands[1]["breakdown"]["clap_similarity"] == 0.0


@pytest.mark.asyncio
async def test_limit_and_resident_model_kept(db, stubs, monkeypatch):
    calls, state = stubs
    state["loaded"] = True
    state["vectors"] = {f"u{i}": _unit(i).tobytes() for i in range(5)}
    monkeypatch.setattr(get_settings().assistant, "clap_preview_limit", 3)
    cands = [_cand(f"u{i}") for i in range(5)]
    stats = await rec.score_previews_with_clap(db, cands, _unit(99).tobytes())
    assert calls["embed"] == [["u0", "u1", "u2"]]
    assert calls["unload"] == 0
    assert stats["scored"] == 3


@pytest.mark.asyncio
async def test_skips_without_touching_db(stubs, monkeypatch, caplog):
    calls, _ = stubs
    caplog.set_level(logging.INFO, logger="backend.services.recommender")
    cands = [_cand("u1")]
    # no centroid: db is never used (None would blow up)
    assert (await rec.score_previews_with_clap(None, cands, None))["scored"] == 0
    monkeypatch.setattr(get_settings().assistant, "clap_previews", False)
    assert (await rec.score_previews_with_clap(None, cands, _unit(1).tobytes()))["scored"] == 0
    monkeypatch.setattr(get_settings().assistant, "clap_previews", True)
    monkeypatch.setattr(get_settings().analysis, "enable_clap", False)
    assert (await rec.score_previews_with_clap(None, cands, _unit(1).tobytes()))["scored"] == 0
    assert calls["embed"] == [] and cands[0]["breakdown"]["clap_similarity"] == 0.0
    assert len([r for r in caplog.records if "Preview CLAP scoring skipped" in r.getMessage()]) == 3


# --- preview download -------------------------------------------------------------

@pytest.mark.asyncio
async def test_download_preview_size_cap_and_cleanup():
    big = b"x" * (rec.PREVIEW_MAX_BYTES + 1)

    def handler(request):
        if request.url.path == "/small":
            return httpx.Response(200, content=b"audio-bytes")
        if request.url.path == "/missing":
            return httpx.Response(404)
        # no content-length: the cap is enforced while streaming
        return httpx.Response(200, content=iter([big[:1024 * 1024]] * 4))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        path = await rec._download_preview(client, "https://x/small")
        assert path and open(path, "rb").read() == b"audio-bytes"
        os.unlink(path)
        assert await rec._download_preview(client, "https://x/missing") is None
        assert await rec._download_preview(client, "https://x/big") is None
