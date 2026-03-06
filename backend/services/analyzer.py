"""Audio analysis service using Essentia for BPM, key, energy, danceability."""
from __future__ import annotations

import logging
from pathlib import Path

from backend.config import get_settings

log = logging.getLogger(__name__)


# Formats Essentia MonoLoader can decode (via FFmpeg/libav internally).
# .opus causes a segfault in Essentia's C++ AudioLoader — skip it entirely.
ESSENTIA_SUPPORTED_EXTENSIONS = {".mp3", ".flac", ".wav", ".ogg", ".m4a", ".aac", ".wma", ".aiff", ".alac"}


def analyze_track(file_path: str) -> dict | None:
    """Analyze an audio file with Essentia. Returns analysis dict or None.

    This runs in a thread/process worker since Essentia is CPU-bound.
    """
    settings = get_settings()
    if not settings.analysis.enable_essentia:
        return None

    abs_path = Path(settings.library.music_dir) / file_path
    if not abs_path.exists():
        log.warning(f"File not found for analysis: {abs_path}")
        return None

    ext = abs_path.suffix.lower()
    if ext not in ESSENTIA_SUPPORTED_EXTENSIONS:
        log.debug(f"Skipping unsupported format for analysis: {ext} ({file_path})")
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
        # Normalize to 0-1 range (rough approximation)
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
        log.warning("Essentia not installed - skipping analysis")
        return None
    except Exception as e:
        log.error(f"Analysis failed for {file_path}: {e}")
        return None


async def analyze_track_async(file_path: str) -> dict | None:
    """Async wrapper for analyze_track - runs in thread pool."""
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, analyze_track, file_path)
