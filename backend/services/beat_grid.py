"""Beat grids for the TV visualizer: where the bars fall in a track, and where it drops.

The analysis job stores only a tempo, which tells the TV how far apart beats are but not where
they land. This works out a constant-tempo grid from Essentia's beat ticks, fitted to the whole
track, so the TV can line its beat clock up with the playback position instead of guessing the
phase from onsets:

- `downbeat_s`: the first bar's first beat (estimated: the beat phase whose low-band energy is
  highest, which is right for most dance and rock music and a guess for anything else),
- `confidence`: the share of Essentia's ticks within 50 ms of the fitted grid. Below
  MIN_CONFIDENCE (live recordings, tempo changes) no grid is served at all,
- `bar_energy`: loudness per bar, 0..1, for the visualizer to see a build-up coming,
- `drops`: bars where the energy jumps after a quieter stretch (estimated, same caveat).

Computed on demand, the first time a TV asks for a track, in a process pool of its own (one
worker, low priority) so it never queues behind or resets the library analysis job's pool, and
cached in `track_beat_grids`, failures included.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import subprocess
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

log = logging.getLogger(__name__)

SAMPLE_RATE = 44100  # what RhythmExtractor2013 requires
BEATS_PER_BAR = 4
MIN_CONFIDENCE = 0.6
GRID_TOLERANCE_S = 0.05
MAX_DURATION_S = 15 * 60
TIMEOUT_S = 180
# Bump when the computation changes, so cached grids are recomputed on their next request.
VERSION = 1

_pool: ProcessPoolExecutor | None = None
_in_flight: dict[str, asyncio.Task] = {}


def _nice():
    os.nice(15)


def _get_pool() -> ProcessPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ProcessPoolExecutor(max_workers=1, initializer=_nice)
    return _pool


def _reset_pool():
    global _pool
    pool, _pool = _pool, None
    if pool is None:
        return
    for pid in list((getattr(pool, "_processes", None) or {}).keys()):
        try:
            os.kill(pid, 9)
        except OSError:
            pass
    pool.shutdown(wait=False, cancel_futures=True)


def _decode(abs_path: Path) -> "object":
    """The whole track as mono float32 at 44.1 kHz, through ffmpeg (every format, opus included)."""
    import numpy as np

    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-i", str(abs_path), "-t", str(MAX_DURATION_S),
         "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "-"],
        capture_output=True, timeout=120,
    )
    if out.returncode != 0:
        raise RuntimeError(f"ffmpeg: {out.stderr.decode(errors='replace')[-200:]}")
    return np.frombuffer(out.stdout, dtype=np.float32).copy()


def _line(xs: list[float], idx: list[int]) -> tuple[float, float]:
    """Least-squares x = origin + period * idx."""
    n = len(xs)
    mi = sum(idx) / n
    mx = sum(xs) / n
    var = sum((i - mi) ** 2 for i in idx)
    period = sum((i - mi) * (x - mx) for i, x in zip(idx, xs)) / var
    return mx - period * mi, period


def fit_grid(beats: list[float]) -> tuple[float, float, float] | None:
    """A constant-tempo grid through beat times: (period_s, origin_s, confidence).

    Essentia's ticks sit on an analysis-frame grid (about 11.6 ms), so the median interval is
    off by a few ms; numbering every tick from that drifts by half a beat within a minute and
    the fit collapses. Instead the fit starts from 16 ticks in the middle of the track (past
    any beatless intro), numbers them, fits a line, and doubles the window each round,
    renumbering with the better period, until it covers the whole track. Ticks more than a
    sixth of a beat off the line are left out of each fit (fills, missed or extra ticks).
    Confidence is the share of all ticks within GRID_TOLERANCE_S of the final grid.
    """
    b = sorted(beats)
    n = len(b)
    if n < 16:
        return None
    mid = n // 2
    lo, hi = mid - 8, mid + 8
    window = b[lo:hi]
    intervals = sorted(y - x for x, y in zip(window, window[1:]))
    period = intervals[len(intervals) // 2]
    if not 0.2 < period < 2.0:
        return None
    origin = b[mid]
    while True:
        xs = b[lo:hi]
        idx = [round((x - origin) / period) for x in xs]
        for _ in range(2):
            keep = [(x, i) for x, i in zip(xs, idx)
                    if abs(x - (origin + period * i)) <= period / 6]
            if len(keep) < 8 or len({i for _, i in keep}) < 2:
                return None
            origin, period = _line([x for x, _ in keep], [i for _, i in keep])
        if lo == 0 and hi == n:
            break
        span = hi - lo
        lo, hi = max(0, lo - span // 2), min(n, hi + span // 2)
    hits = sum(1 for x in b if abs((x - origin) / period - round((x - origin) / period)) * period <= GRID_TOLERANCE_S)
    return period, origin % period, hits / n


def find_drops(bar_energy: list[float]) -> list[int]:
    """Bars where the music jumps up: the bar itself much louder than the one before, the next
    four clearly louder than the four before, and loud overall. At most one per eight bars."""
    drops: list[int] = []
    top = max(bar_energy) if bar_energy else 0.0
    for i in range(4, len(bar_energy) - 3):
        before = sum(bar_energy[i - 4:i]) / 4
        after = sum(bar_energy[i:i + 4]) / 4
        jump = bar_energy[i] > 1.3 * max(bar_energy[i - 1], 1e-3)
        if jump and after > 0.6 * top and after > 1.4 * max(before, 1e-3) and (not drops or i - drops[-1] >= 8):
            drops.append(i)
    return drops


def compute_beat_grid(abs_path_str: str) -> dict:
    """Runs in the pool worker. Returns a dict for the cache row (status ready/none)."""
    import numpy as np
    import essentia.standard as es

    abs_path = Path(abs_path_str)
    audio = _decode(abs_path)
    duration = len(audio) / SAMPLE_RATE
    if duration < 20:
        return {"status": "none", "error": "too short"}

    bpm, beats, _conf, _, _ = es.RhythmExtractor2013(method="multifeature")(audio)
    fit = fit_grid([float(b) for b in beats])
    if fit is None:
        return {"status": "none", "error": "no steady beat", "bpm": float(bpm)}
    period, origin, confidence = fit
    if confidence < MIN_CONFIDENCE:
        return {"status": "none", "error": f"tempo not steady ({confidence:.2f})",
                "bpm": round(60 / period, 2), "confidence": round(confidence, 3)}

    # Low-band energy around every grid beat, to pick which of the four phases is beat one.
    n_beats = int((duration - origin) / period)
    win = 2048
    freqs = np.fft.rfftfreq(win, 1 / SAMPLE_RATE)
    low = (freqs >= 40) & (freqs <= 150)
    hann = np.hanning(win).astype(np.float32)
    phase_energy = [0.0] * BEATS_PER_BAR
    for k in range(n_beats):
        c = int((origin + k * period) * SAMPLE_RATE)
        seg = audio[max(0, c - win // 4):max(0, c - win // 4) + win]
        if len(seg) < win:
            continue
        spec = np.abs(np.fft.rfft(seg * hann))
        phase_energy[k % BEATS_PER_BAR] += float(spec[low].sum())
    phase = int(np.argmax(phase_energy))
    downbeat = origin + phase * period

    bar = period * BEATS_PER_BAR
    rms = []
    t = downbeat
    while t + bar <= duration:
        seg = audio[int(t * SAMPLE_RATE):int((t + bar) * SAMPLE_RATE)]
        rms.append(float(np.sqrt(np.mean(seg * seg))) if len(seg) else 0.0)
        t += bar
    top = max(rms) if rms else 0.0
    bar_energy = [round(r / top, 3) if top > 0 else 0.0 for r in rms]

    return {
        "status": "ready",
        "bpm": round(60 / period, 3),
        "downbeat_s": round(downbeat, 4),
        "beats_per_bar": BEATS_PER_BAR,
        "confidence": round(confidence, 3),
        "bar_energy": bar_energy,
        "drops": find_drops(bar_energy),
        "duration_s": round(duration, 2),
    }


async def compute_async(abs_path: Path) -> dict:
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(_get_pool(), compute_beat_grid, str(abs_path)), timeout=TIMEOUT_S,
        )
    except (BrokenProcessPool, asyncio.TimeoutError) as e:
        _reset_pool()
        return {"status": "failed", "error": type(e).__name__}
    except Exception as e:  # decoding or Essentia failed on this file
        return {"status": "failed", "error": str(e)[:300]}


def start(track_id: str, abs_path: Path, on_done) -> None:
    """Starts computing a track's grid unless it already is; [on_done] stores the result."""
    if track_id in _in_flight:
        return

    async def run():
        try:
            result = await compute_async(abs_path)
            await on_done(track_id, result)
        except Exception:
            log.exception("Beat grid for %s failed to store", track_id)
        finally:
            _in_flight.pop(track_id, None)

    _in_flight[track_id] = asyncio.get_running_loop().create_task(run())


def in_flight(track_id: str) -> bool:
    return track_id in _in_flight
