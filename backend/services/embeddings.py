"""CLAP vibe embedding generation and similarity search."""
from __future__ import annotations

import ctypes
import gc
import logging
import struct
import threading
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from backend.config import get_settings

log = logging.getLogger(__name__)

_model = None
_processor = None
# Guards _model/_processor and _in_use. Reentrant because _use_model loads under it.
_lock = threading.RLock()
# Number of embedding calls currently running inference; unload_clap_model() is skipped while
# it is non-zero so a short-lived user (the recommendation refresh) can't pull the model out
# from under a vibe-embedding job or a text search in the same process.
_in_use = 0


def clap_model_name() -> str:
    """The Hugging Face model id analysis.clap_model resolves to (also the preview cache key)."""
    if get_settings().analysis.clap_model == "HTSAT-base":
        return "laion/clap-htsat-unfused"
    return "laion/larger_clap_music_and_speech"


def _do_load():
    """Load the model into the module globals. Caller holds _lock."""
    global _model, _processor
    try:
        from transformers import ClapModel, ClapProcessor

        settings = get_settings()
        model_name = clap_model_name()

        log.info(f"Loading CLAP model: {model_name}")
        processor = ClapProcessor.from_pretrained(model_name)
        model = ClapModel.from_pretrained(model_name)
        model.eval()

        if settings.analysis.use_gpu:
            try:
                import torch
                if torch.cuda.is_available():
                    model = model.cuda()
                    log.info("CLAP model loaded on GPU")
            except ImportError:
                pass

        _model, _processor = model, processor
        log.info("CLAP model loaded successfully")
    except ImportError:
        log.warning("transformers/torch not installed - CLAP disabled")
    except Exception as e:
        log.error(f"Failed to load CLAP model: {e}")


def _load_clap_model():
    """Lazy-load the CLAP model (once per process, even with concurrent callers)."""
    with _lock:
        if _model is None:
            _do_load()
        return _model, _processor


@contextmanager
def _use_model():
    """Yield (model, processor), loading if needed, and count the caller as a user of the model
    for its duration so unload_clap_model() leaves it alone. Yields (None, None) when the model
    can't be loaded."""
    global _in_use
    with _lock:
        model, processor = _load_clap_model()
        if model is not None:
            _in_use += 1
    if model is None:
        yield None, None
        return
    try:
        yield model, processor
    finally:
        with _lock:
            _in_use -= 1


def clap_model_loaded() -> bool:
    """True when the CLAP model is already resident in this process."""
    return _model is not None


def clap_model_available() -> bool:
    """Load the CLAP model if needed; False when it can't be loaded (missing deps, bad weights)."""
    model, _ = _load_clap_model()
    return model is not None


def unload_clap_model() -> bool:
    """Drop this process's reference to the CLAP model so its memory can be reclaimed.

    Callers that only need the model briefly (the recommendation refresh) use this to avoid
    leaving ~1 GB resident. Skipped (returns False) while any embedding call is running; the
    next _load_clap_model() call reloads it. After collecting, malloc_trim hands the freed heap
    back to the OS, which gc.collect() alone usually doesn't."""
    global _model, _processor
    with _lock:
        if _in_use:
            log.info(f"CLAP model kept loaded: {_in_use} embedding call(s) in progress")
            return False
        if _model is None:
            return True
        _model = None
        _processor = None
        gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass
    log.info("CLAP model unloaded")
    return True


def _embed_audio(audio: np.ndarray) -> bytes:
    """Embed a mono 48 kHz float32 signal with CLAP. Returns the L2-normalised 512-dim vector as
    float32 bytes. Raises when the model is unavailable or inference fails."""
    import torch

    with _use_model() as (model, processor):
        if model is None:
            raise RuntimeError("CLAP model unavailable")
        settings = get_settings()

        inputs = processor(audio=audio, sampling_rate=48000, return_tensors="pt")

        if settings.analysis.use_gpu and torch.cuda.is_available():
            inputs = {k: v.cuda() for k, v in inputs.items()}

        with torch.no_grad():
            outputs = model.get_audio_features(**inputs)

    # Use pooler_output (512-dim) — outputs[0] is last_hidden_state (full feature map)
    pooled = outputs.pooler_output if hasattr(outputs, 'pooler_output') else outputs[0]
    embedding = pooled.squeeze(0).cpu().numpy().astype(np.float32)
    # Normalize
    embedding = embedding / np.linalg.norm(embedding)

    return embedding.tobytes()


def generate_embedding_for_path(abs_path: str, max_seconds: int = 30) -> bytes | None:
    """Embed an arbitrary audio file (absolute path, any container ffmpeg reads, e.g. the AAC
    .m4a iTunes previews). Decodes with ffmpeg to mono 48 kHz float32 so it doesn't depend on
    librosa's codec support. Returns None on any failure (logged at debug level: callers that
    loop over many files summarise failures themselves)."""
    import subprocess

    try:
        proc = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-i", abs_path, "-t", str(max_seconds),
             "-ac", "1", "-ar", "48000", "-f", "f32le", "pipe:1"],
            capture_output=True, timeout=60,
        )
        if proc.returncode != 0 or not proc.stdout:
            log.debug(f"ffmpeg decode failed for {abs_path}: {proc.stderr[-300:]!r}")
            return None
        audio = np.frombuffer(proc.stdout, dtype=np.float32)
        if audio.size < 48000:  # under a second of audio: not worth embedding
            return None
        return _embed_audio(audio.copy())
    except Exception as e:
        log.debug(f"Embedding failed for {abs_path}: {e}")
        return None


def generate_embedding(file_path: str) -> bytes | None:
    """Generate a 512-dim CLAP audio embedding. Returns bytes (float32 array) or None."""
    settings = get_settings()
    if not settings.analysis.enable_clap:
        return None

    abs_path = Path(settings.library.music_dir) / file_path
    if not abs_path.exists():
        log.warning(f"File not found for embedding: {abs_path}")
        return None

    try:
        import librosa

        model, _ = _load_clap_model()
        if model is None:
            return None

        # Load audio (CLAP expects 48kHz)
        audio, sr = librosa.load(str(abs_path), sr=48000, duration=30)
        return _embed_audio(audio)

    except ImportError:
        log.warning("CLAP dependencies not installed")
        return None
    except Exception as e:
        log.error(f"Embedding generation failed for {file_path}: {e}")
        return None


def generate_text_embedding(text: str) -> bytes | None:
    """Generate a CLAP text embedding for text-to-audio search."""
    try:
        import torch

        with _use_model() as (model, processor):
            if model is None:
                return None

            inputs = processor(text=[text], return_tensors="pt", padding=True)
            settings = get_settings()
            if settings.analysis.use_gpu and torch.cuda.is_available():
                inputs = {k: v.cuda() for k, v in inputs.items()}

            with torch.no_grad():
                outputs = model.get_text_features(**inputs)

        pooled = outputs.pooler_output if hasattr(outputs, 'pooler_output') else outputs[0]
        embedding = pooled.squeeze(0).cpu().numpy().astype(np.float32)
        embedding = embedding / np.linalg.norm(embedding)
        return embedding.tobytes()

    except Exception as e:
        log.error(f"Text embedding failed: {e}")
        return None


async def generate_embedding_async(file_path: str) -> bytes | None:
    """Async wrapper - runs in thread pool."""
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, generate_embedding, file_path)


def embedding_from_bytes(data: bytes) -> np.ndarray:
    """Convert stored bytes back to numpy array."""
    return np.frombuffer(data, dtype=np.float32)


def cosine_similarity(a: bytes, b: bytes) -> float:
    """Compute cosine similarity between two embeddings."""
    vec_a = embedding_from_bytes(a)
    vec_b = embedding_from_bytes(b)
    return float(np.dot(vec_a, vec_b))
