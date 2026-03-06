"""Audio analysis service using Essentia for BPM, key, energy, danceability."""
from __future__ import annotations

import logging
import os
from concurrent.futures import ProcessPoolExecutor
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
    """Async wrapper — runs Essentia in a separate process for true parallelism."""
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(get_analysis_pool(), analyze_track, file_path)
