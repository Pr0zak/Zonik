"""The beat grid fit (backend/services/beat_grid.py) on synthetic ticks."""
import random

from backend.services.beat_grid import find_drops, fit_grid

HOP = 512 / 44100  # Essentia's analysis frame: ticks land on multiples of this


def _ticks(bpm: float, origin: float, seconds: float, jitter: float = 0.0, quantise: bool = True):
    period = 60 / bpm
    out, t = [], origin
    rng = random.Random(7)
    while t < seconds:
        x = t + rng.uniform(-jitter, jitter)
        out.append(round(x / HOP) * HOP if quantise else x)
        t += period
    return out


def test_steady_track_quantised_to_frames():
    # 128 BPM is 0.46875 s, which the frame grid rounds to 0.464 s or 0.476 s: numbering the
    # ticks from the median interval drifts by half a beat within a minute.
    fit = fit_grid(_ticks(128, 0.31, 240))
    assert fit is not None
    period, origin, confidence = fit
    assert abs(60 / period - 128) < 0.01
    assert abs(origin - 0.31) < 0.01
    assert confidence > 0.95


def test_missing_and_extra_ticks():
    ticks = _ticks(120, 1.0, 200, jitter=0.01)
    del ticks[50:58]  # a breakdown with no beat
    ticks += [33.21, 87.9, 140.05]  # off-beat false ticks
    period, _, confidence = fit_grid(sorted(ticks))
    assert abs(60 / period - 120) < 0.02
    assert confidence > 0.9


def test_drifting_tempo_has_low_confidence():
    ticks, t, period = [], 0.5, 0.5
    while t < 200:
        ticks.append(t)
        t += period
        period *= 1.0008  # a live drummer slowing down
    _, _, confidence = fit_grid(ticks)
    assert confidence < 0.6


def test_too_few_ticks():
    assert fit_grid([0.5, 1.0, 1.5]) is None


def test_drops_after_quiet_bars():
    energy = [0.3] * 16 + [1.0] * 16 + [0.2] * 8 + [0.95] * 16
    assert find_drops(energy) == [16, 40]
    assert find_drops([0.8] * 40) == []


# --- GET /api/analysis/track/{id}/beats -------------------------------------------------
import asyncio

import pytest

import backend.services.beat_grid as bg


@pytest.mark.asyncio
async def test_beats_endpoint_pending_then_cached(db_ready, tmp_path, monkeypatch):
    from backend.api.analysis import get_track_beats
    from backend.database import async_session
    from backend.models.analysis import TrackAnalysis
    from backend.models.track import Track

    song = tmp_path / "song.mp3"
    song.write_bytes(b"x")
    async with async_session() as s:
        s.add(Track(id="trk-b", title="Beat", file_path=str(song), format="mp3", bitrate=320))
        s.add(TrackAnalysis(track_id="trk-b", bpm=128.0, key="A", scale="minor", energy=0.8))
        s.add(Track(id="trk-n", title="Speech", file_path=str(song) + "2", format="mp3", bitrate=320))
        await s.commit()
    (tmp_path / "song.mp32").write_bytes(b"x")

    calls = []

    async def fake_compute(path):
        calls.append(path)
        if str(path).endswith("2"):
            return {"status": "none", "error": "no steady beat"}
        return {"status": "ready", "bpm": 128.0, "downbeat_s": 0.5, "beats_per_bar": 4,
                "confidence": 0.95, "bar_energy": [0.2, 1.0], "drops": [1]}

    monkeypatch.setattr(bg, "compute_async", fake_compute)

    async with async_session() as db:
        first = await get_track_beats("trk-b", db)
        again = await get_track_beats("trk-b", db)
    assert first == {"status": "pending"} and again == {"status": "pending"}
    await asyncio.gather(*list(bg._in_flight.values()))

    async with async_session() as db:
        ready = await get_track_beats("trk-b", db)
        assert await get_track_beats("trk-n", db) == {"status": "pending"}
    await asyncio.gather(*list(bg._in_flight.values()))
    async with async_session() as db:
        none = await get_track_beats("trk-n", db)
        unknown = await get_track_beats("nope", db)

    assert ready["status"] == "ready" and ready["downbeat_s"] == 0.5 and ready["drops"] == [1]
    assert ready["key"] == "A" and ready["energy"] == 0.8
    assert none == {"status": "none", "error": "no steady beat"}
    assert unknown["status"] == "failed"
    assert len(calls) == 2  # computed once per track, then served from the cache
