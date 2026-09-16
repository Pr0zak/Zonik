"""Claude API pricing table and cost estimation.

IMPORTANT — these rates are a point-in-time snapshot (see ``PRICING_AS_OF``), not a
live feed. Anthropic can change published pricing at any time, and this module will
happily keep quoting stale numbers until someone edits it.

That is why ``ai_usage`` stores the raw token counts (input / output / cache read /
cache write) alongside ``cost_usd``: cost is always recomputable from the tokens, so
a wrong or outdated rate is a reporting bug, never lost data.

To correct or add a rate without touching code, set ``model_pricing`` under
``[assistant]`` in ``zonik.toml``::

    [assistant.model_pricing]
    "claude-sonnet-4-20250514" = [3.00, 15.00]   # [input, output] USD per 1M tokens

Config entries are consulted before ``DEFAULT_PRICING`` and win outright.

Unknown models never raise — they fall back to ``FALLBACK_RATES`` so a cost estimate
is approximately right rather than silently zero, and ``is_known_model()`` returns
False so the UI can flag the row as guessed.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

#: The date these rates were last verified against Anthropic's published pricing.
PRICING_AS_OF: str = "2026-06-24"

#: model id -> (input $/1M tokens, output $/1M tokens)
DEFAULT_PRICING: dict[str, tuple[float, float]] = {
    # Current families
    "claude-fable-5": (10.00, 50.00),
    "claude-mythos-5": (10.00, 50.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-opus-4-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    # Deprecated / retired families — kept so historical ai_usage rows still price
    # correctly rather than silently dropping to the fallback estimate.
    "claude-opus-4-1": (15.00, 75.00),
    "claude-opus-4-0": (15.00, 75.00),
    "claude-sonnet-4-0": (3.00, 15.00),
    "claude-3-haiku": (0.25, 1.25),
}

#: Used when a model id isn't recognised. Mid-tier rates, so the estimate lands in the
#: right order of magnitude instead of reading as free.
FALLBACK_RATES: tuple[float, float] = DEFAULT_PRICING["claude-sonnet-4-6"]

#: Cache reads bill at 10% of the input rate; 5-minute cache writes at 125%.
CACHE_READ_MULTIPLIER: float = 0.10
CACHE_WRITE_MULTIPLIER: float = 1.25

_DATE_SUFFIX_RE = re.compile(r"-\d{8}$")

#: Bare family ids that Anthropic later re-spelled with an explicit point release.
_ALIASES: dict[str, str] = {
    "claude-opus-4": "claude-opus-4-0",
    "claude-sonnet-4": "claude-sonnet-4-0",
}


def normalize_model(model: str) -> str:
    """Reduce a raw API model id to the alias used as a pricing key.

    Strips a trailing ``-YYYYMMDD`` snapshot suffix and maps the bare ``-4`` family
    names onto their ``-4-0`` spelling::

        claude-sonnet-4-20250514   -> claude-sonnet-4 -> claude-sonnet-4-0
        claude-haiku-4-5-20251001  -> claude-haiku-4-5
        claude-3-haiku-20240307    -> claude-3-haiku
    """
    if not model:
        return ""
    name = _DATE_SUFFIX_RE.sub("", str(model).strip().lower())
    return _ALIASES.get(name, name)


def _config_pricing() -> dict[str, tuple[float, float]]:
    """model_pricing overrides from zonik.toml, normalized. Never raises."""
    try:
        from backend.config import get_settings

        raw = get_settings().assistant.model_pricing or {}
    except Exception:  # settings unavailable (import cycle, no config file, bad TOML)
        return {}

    out: dict[str, tuple[float, float]] = {}
    for key, rates in raw.items():
        try:
            if rates is None or len(rates) < 2:
                continue
            out[normalize_model(key)] = (float(rates[0]), float(rates[1]))
        except Exception:
            log.warning("Ignoring malformed assistant.model_pricing entry for %r", key)
    return out


def is_known_model(model: str) -> bool:
    """True when we have real rates for this model (config override or built-in)."""
    key = normalize_model(model)
    if not key:
        return False
    return key in _config_pricing() or key in DEFAULT_PRICING


def get_rates(model: str) -> tuple[float, float]:
    """(input $/1M, output $/1M) for a model. Unknown models get FALLBACK_RATES."""
    key = normalize_model(model)
    override = _config_pricing().get(key)
    if override is not None:
        return override
    return DEFAULT_PRICING.get(key, FALLBACK_RATES)


def estimate_cost(
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """Estimated USD cost of one call. Never raises — returns 0.0 on garbage input.

    Zonik's default model is ``claude-sonnet-4-20250514`` (3.00 / 15.00), so
    ``estimate_cost("claude-sonnet-4-20250514", 10_000, 2_000)`` == 0.06.
    """
    try:
        rate_in, rate_out = get_rates(model)
        tokens_in = max(int(input_tokens or 0), 0)
        tokens_out = max(int(output_tokens or 0), 0)
        tokens_cache_read = max(int(cache_read_tokens or 0), 0)
        tokens_cache_write = max(int(cache_write_tokens or 0), 0)
    except Exception:
        return 0.0

    total = (
        tokens_in * rate_in
        + tokens_out * rate_out
        + tokens_cache_read * rate_in * CACHE_READ_MULTIPLIER
        + tokens_cache_write * rate_in * CACHE_WRITE_MULTIPLIER
    ) / 1_000_000.0
    # 10dp, not 2 — a single Haiku call costs a small fraction of a cent and would
    # otherwise round away to nothing before it ever reaches a sum.
    return round(total, 10)
