"""CLAP similarity on iTunes previews: scoring maths, explanation text and the cache path
(fetch + embed stubbed, cache in an in-memory SQLite)."""
import asyncio
import functools
import logging
import os
import tempfile
import threading
import time
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

MODEL = emb_mod.clap_model_name()


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
    db.add(PreviewEmbedding(preview_url="u1", model=MODEL, embedding=centroid.tobytes(), created_at=datetime.utcnow()))
    # same URL embedded by another CLAP model: must be a cache miss
    db.add(PreviewEmbedding(preview_url="u2", model="some/other-clap", embedding=centroid.tobytes(),
                            created_at=datetime.utcnow()))
    db.add(PreviewEmbedding(preview_url="old", model=MODEL, embedding=centroid.tobytes(),
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

    keys = set((await db.execute(select(PreviewEmbedding.preview_url, PreviewEmbedding.model))).all())
    # u2 cached for this model alongside the other model's row; the year-old row pruned
    assert keys == {("u1", MODEL), ("u2", MODEL), ("u2", "some/other-clap")}

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
    db.add(PreviewEmbedding(preview_url="u1", model=MODEL, embedding=centroid.tobytes(), created_at=datetime.utcnow()))
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


@pytest.mark.asyncio
async def test_web_process_scores_cached_only(db, stubs, caplog):
    calls, state = stubs
    caplog.set_level(logging.INFO, logger="backend.services.recommender")
    centroid = _unit(4)
    db.add(PreviewEmbedding(preview_url="u1", model=MODEL, embedding=centroid.tobytes(), created_at=datetime.utcnow()))
    await db.commit()
    state["vectors"] = {"u2": _unit(5).tobytes()}
    cands = [_cand("u1"), _cand("u2")]
    stats = await rec.score_previews_with_clap(db, cands, centroid.tobytes(), allow_model_load=False)
    assert calls["embed"] == [] and calls["available"] == 0 and calls["unload"] == 0
    assert stats["scored"] == 1 and cands[1]["breakdown"]["clap_similarity"] == 0.0
    assert any("1 uncached preview(s) left for the nightly worker" in r.getMessage() for r in caplog.records)


# --- _embed_previews: temp files, slots, timeout ------------------------------------

def _preview_files(d):
    return sorted(n for n in os.listdir(d) if n.startswith(rec.PREVIEW_TMP_PREFIX))


def _mock_client(monkeypatch, handler):
    orig_client = httpx.AsyncClient
    monkeypatch.setattr(rec.httpx, "AsyncClient",
                        functools.partial(orig_client, transport=httpx.MockTransport(handler)))


@pytest.mark.asyncio
async def test_embed_previews_cleans_up(monkeypatch, tmp_path):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    stale = tmp_path / f"{rec.PREVIEW_TMP_PREFIX}stale.m4a"
    stale.write_bytes(b"x")
    os.utime(stale, (time.time() - 7200, time.time() - 7200))
    fresh = tmp_path / f"{rec.PREVIEW_TMP_PREFIX}inflight.m4a"
    fresh.write_bytes(b"x")

    async def handler(request):
        if request.url.path == "/missing":
            return httpx.Response(404)
        if request.url.path == "/slow":
            async def trickle():
                for _ in range(50):
                    await asyncio.sleep(0.05)
                    yield b"x"
            return httpx.Response(200, content=trickle())
        return httpx.Response(200, content=b"audio")

    _mock_client(monkeypatch, handler)
    monkeypatch.setattr(rec, "PREVIEW_TOTAL_TIMEOUT_S", 0.3)

    on_disk_max = 0
    embedded = []

    async def fake_embed(path):
        nonlocal on_disk_max
        assert os.path.exists(path)
        # files this pass created (minus the recent leftover that belongs to someone else)
        on_disk_max = max(on_disk_max, len(_preview_files(tmp_path)) - 1)
        embedded.append(path)
        await asyncio.sleep(0.01)
        return _unit(1).tobytes()

    monkeypatch.setattr(rec, "_embed_preview_file", fake_embed)
    urls = [f"https://x/ok{i}" for i in range(10)] + ["https://x/missing", "https://x/slow"]
    out = await rec._embed_previews(urls)

    assert set(out) == {f"https://x/ok{i}" for i in range(10)}
    assert len(embedded) == 10
    assert on_disk_max <= rec.PREVIEW_CONCURRENCY
    # failed download, timed-out download and every embedded file are gone; the stale
    # leftover was swept, a recent one (possibly another refresh's) is kept
    assert _preview_files(tmp_path) == [fresh.name]


@pytest.mark.asyncio
async def test_embed_previews_removes_file_when_embed_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    _mock_client(monkeypatch, lambda r: httpx.Response(200, content=b"audio"))

    async def failing_embed(path):
        assert os.path.exists(path)
        raise RuntimeError("boom")

    monkeypatch.setattr(rec, "_embed_preview_file", failing_embed)
    assert await rec._embed_previews(["https://x/a", "https://x/b"]) == {}
    assert _preview_files(tmp_path) == []


# --- model lock and in-use counter ----------------------------------------------------

@pytest.fixture
def fake_model(monkeypatch):
    loads = []

    def fake_do_load():
        loads.append(threading.get_ident())
        time.sleep(0.05)
        emb_mod._model, emb_mod._processor = object(), object()

    monkeypatch.setattr(emb_mod, "_do_load", fake_do_load)
    monkeypatch.setattr(emb_mod, "_model", None)
    monkeypatch.setattr(emb_mod, "_processor", None)
    monkeypatch.setattr(emb_mod, "_in_use", 0)
    return loads


def test_concurrent_loads_load_once(fake_model):
    threads = [threading.Thread(target=emb_mod.clap_model_available) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(fake_model) == 1 and emb_mod.clap_model_loaded()


def test_unload_skipped_while_in_use(fake_model):
    with emb_mod._use_model() as (model, _):
        assert model is not None and emb_mod._in_use == 1
        assert emb_mod.unload_clap_model() is False
        assert emb_mod.clap_model_loaded()
    assert emb_mod._in_use == 0
    assert emb_mod.unload_clap_model() is True
    assert not emb_mod.clap_model_loaded()
    # the counter is released even when the caller raises; the next use reloads
    with pytest.raises(RuntimeError):
        with emb_mod._use_model():
            raise RuntimeError("inference failed")
    assert emb_mod._in_use == 0 and len(fake_model) == 2


def test_use_model_when_unavailable(monkeypatch):
    monkeypatch.setattr(emb_mod, "_do_load", lambda: None)
    monkeypatch.setattr(emb_mod, "_model", None)
    monkeypatch.setattr(emb_mod, "_in_use", 0)
    with emb_mod._use_model() as (model, processor):
        assert model is None and processor is None
    assert emb_mod._in_use == 0
