"""Audio analysis service using Essentia for BPM, key, energy, danceability."""
from __future__ import annotations

import logging
import os
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

from backend.config import get_settings

log = logging.getLogger(__name__)


# Formats Essentia MonoLoader can decode (via FFmpeg/libav internally).
# .opus causes a segfault in Essentia's C++ AudioLoader — skip it entirely.
ESSENTIA_SUPPORTED_EXTENSIONS = {".mp3", ".flac", ".wav", ".ogg", ".m4a", ".aac", ".wma", ".aiff", ".alac"}

# ProcessPoolExecutor for CPU-bound Essentia work — true parallelism across cores.
# Workers = CPU count - 1 (leave one core for the event loop / HTTP serving).
_analysis_pool: ProcessPoolExecutor | None = None


def _lower_priority():
    """Set worker process to low CPU priority (nice 15)."""
    os.nice(15)


def get_analysis_pool() -> ProcessPoolExecutor:
    global _analysis_pool
    if _analysis_pool is None:
        workers = max(1, (os.cpu_count() or 2) - 1)
        _analysis_pool = ProcessPoolExecutor(max_workers=workers, initializer=_lower_priority)
        log.info(f"Analysis pool: {workers} worker(s), nice 15")
    return _analysis_pool


def _reset_analysis_pool():
    """Destroy broken pool and create a fresh one."""
    global _analysis_pool
    if _analysis_pool is not None:
        try:
            _analysis_pool.shutdown(wait=False)
        except Exception:
            pass
    _analysis_pool = None
    log.warning("Analysis pool reset after worker crash")
    return get_analysis_pool()


def _pre_validate(abs_path: Path) -> str | None:
    """Quick validation before sending to Essentia. Returns error string or None."""
    try:
        import mutagen
        f = mutagen.File(str(abs_path))
        if f is None:
            return "mutagen could not identify file"
        info = f.info
        channels = getattr(info, "channels", None)
        if channels is not None and channels > 2:
            return f"unsupported channel count: {channels}"
    except Exception:
        pass  # If mutagen fails, let Essentia try anyway
    return None


def analyze_track(file_path: str) -> dict | None:
    """Analyze an audio file with Essentia. Returns analysis dict or None.

    This runs in a process worker since Essentia is CPU-bound.
    """
    settings = get_settings()
    if not settings.analysis.enable_essentia:
        return None

    abs_path = Path(settings.library.music_dir) / file_path
    if not abs_path.exists():
        return None

    ext = abs_path.suffix.lower()
    if ext not in ESSENTIA_SUPPORTED_EXTENSIONS:
        return None

    # Pre-validate to catch known crash triggers before Essentia
    error = _pre_validate(abs_path)
    if error:
        logging.getLogger(__name__).warning(f"Skipping {file_path}: {error}")
        return None

    try:
        import essentia
        import essentia.standard as es

        audio = es.MonoLoader(filename=str(abs_path), sampleRate=44100)()

        # BPM
        rhythm_extractor = es.RhythmExtractor2013(method="multifeature")
        bpm, beats, beats_confidence, _, beats_intervals = rhythm_extractor(audio)

        # Key
        key_extractor = es.KeyExtractor()
        key, scale, key_strength = key_extractor(audio)

        # Energy
        energy = es.Energy()(audio)
        rms = es.RMS()(audio)
        energy_normalized = min(1.0, rms * 10)

        # Danceability
        danceability_extractor = es.Danceability()
        danceability, _ = danceability_extractor(audio)

        # Loudness (ReplayGain)
        replay_gain = es.ReplayGain()(audio)

        return {
            "bpm": round(bpm, 1),
            "key": key,
            "scale": scale,
            "energy": round(energy_normalized, 3),
            "danceability": round(danceability, 3),
            "loudness": round(replay_gain, 2),
        }

    except ImportError:
        return None
    except Exception as e:
        logging.getLogger(__name__).error(f"Analysis failed for {file_path}: {e}")
        return None


async def analyze_track_async(file_path: str) -> dict | None:
    """Async wrapper — runs Essentia in a separate process for true parallelism.

    If a worker process segfaults (BrokenProcessPool), recreates the pool
    and returns None for this track so the job can continue.
    """
    import asyncio
    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(get_analysis_pool(), analyze_track, file_path),
            timeout=120,
        )
    except BrokenProcessPool:
        log.error(f"Worker crashed analyzing {file_path} — resetting pool")
        _reset_analysis_pool()
        return None
    except asyncio.TimeoutError:
        log.warning(f"Analysis timed out (120s) for {file_path}")
        return None
    except Exception as e:
        log.warning(f"Analysis async error for {file_path}: {e}")
        # Check if pool is still usable
        try:
            get_analysis_pool().submit(lambda: None)
        except BrokenProcessPool:
            _reset_analysis_pool()
        return None
