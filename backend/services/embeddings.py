"""CLAP vibe embedding generation and similarity search."""
from __future__ import annotations

import logging
import struct
from pathlib import Path

import numpy as np

from backend.config import get_settings

log = logging.getLogger(__name__)

_model = None
_processor = None


def _load_clap_model():
    """Lazy-load CLAP model."""
    global _model, _processor
    if _model is not None:
        return _model, _processor

    try:
        from transformers import ClapModel, ClapProcessor

        settings = get_settings()
        model_name = f"laion/larger_clap_music_and_speech"
        if settings.analysis.clap_model == "HTSAT-base":
            model_name = "laion/clap-htsat-unfused"

        log.info(f"Loading CLAP model: {model_name}")
        _processor = ClapProcessor.from_pretrained(model_name)
        _model = ClapModel.from_pretrained(model_name)
        _model.eval()

        if settings.analysis.use_gpu:
            try:
                import torch
                if torch.cuda.is_available():
                    _model = _model.cuda()
                    log.info("CLAP model loaded on GPU")
            except ImportError:
                pass

        log.info("CLAP model loaded successfully")
        return _model, _processor
    except ImportError:
        log.warning("transformers/torch not installed - CLAP disabled")
        return None, None
    except Exception as e:
        log.error(f"Failed to load CLAP model: {e}")
        return None, None


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
        import torch
        import librosa

        model, processor = _load_clap_model()
        if model is None:
            return None

        # Load audio (CLAP expects 48kHz)
        audio, sr = librosa.load(str(abs_path), sr=48000, duration=30)

        inputs = processor(audios=audio, sampling_rate=48000, return_tensors="pt")

        if settings.analysis.use_gpu and torch.cuda.is_available():
            inputs = {k: v.cuda() for k, v in inputs.items()}

        with torch.no_grad():
            outputs = model.get_audio_features(**inputs)

        embedding = outputs[0].cpu().numpy().astype(np.float32)
        # Normalize
        embedding = embedding / np.linalg.norm(embedding)

        return embedding.tobytes()

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

        model, processor = _load_clap_model()
        if model is None:
            return None

        inputs = processor(text=[text], return_tensors="pt", padding=True)
        settings = get_settings()
        if settings.analysis.use_gpu and torch.cuda.is_available():
            inputs = {k: v.cuda() for k, v in inputs.items()}

        with torch.no_grad():
            outputs = model.get_text_features(**inputs)

        embedding = outputs[0].cpu().numpy().astype(np.float32)
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
