"""Shared Claude API client with concurrency control and token tracking."""
from __future__ import annotations

import asyncio
import json
import logging
import time

import httpx

from backend.config import get_settings

log = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

# Concurrency limiter — simultaneous Claude requests. 4 is comfortable for Haiku
# on a single-user box and keeps batch ops (duplicate resolve, recommendations)
# from serializing into multi-minute waits.
_semaphore = asyncio.Semaphore(4)

# Persistent HTTP client for connection reuse
_http_client: httpx.AsyncClient | None = None

# Token usage tracking (in-memory, resets on restart)
_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0, "requests": 0, "errors": 0}
_usage_lock = asyncio.Lock()


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=60,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=3),
        )
    return _http_client


async def _track_usage(input_tokens: int = 0, output_tokens: int = 0, error: bool = False) -> None:
    async with _usage_lock:
        _usage["input_tokens"] += input_tokens
        _usage["output_tokens"] += output_tokens
        _usage["requests"] += 1
        if error:
            _usage["errors"] += 1


async def get_usage() -> dict:
    """Return current session token usage stats."""
    async with _usage_lock:
        return {**_usage}


async def _record_usage(
    *,
    feature: str,
    model: str,
    started: float,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    success: bool = True,
    error: str | None = None,
) -> None:
    """Persist one ai_usage row for a finished Claude call.

    Every outcome (success, non-200, empty content, timeout, exception) gets a
    row — the silent failures are exactly the ones worth seeing on a chart.

    This is best-effort telemetry: any failure here is swallowed, because a
    bookkeeping problem must never turn into a failed AI feature. The model
    and pricing imports are deliberately lazy for the same reason.
    """
    try:
        settings = get_settings()
        if not getattr(settings.assistant, "track_ai_usage", True):
            return

        from backend.database import async_session
        from backend.models.ai_usage import AIUsage
        from backend.services.ai import pricing

        latency_ms = int((time.monotonic() - started) * 1000)
        cost = pricing.estimate_cost(
            model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
        )

        # Independent session: call_claude runs from API requests *and* ARQ
        # workers, so there is no request-scoped session to borrow.
        async with async_session() as session:
            session.add(
                AIUsage(
                    feature=feature or "unknown",
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_read_tokens=cache_read_tokens,
                    cache_write_tokens=cache_write_tokens,
                    cost_usd=cost,
                    latency_ms=latency_ms,
                    success=success,
                    error=error,
                )
            )
            await session.commit()
    except Exception as e:
        log.warning("Failed to record AI usage (%s/%s): %s", feature, model, e)


async def call_claude(
    prompt: str,
    *,
    system: str | None = None,
    max_tokens: int = 4096,
    model: str | None = None,
    temperature: float | None = None,
    feature: str = "unknown",
) -> dict:
    """Send a prompt to Claude with concurrency control and token tracking.

    `feature` labels the caller (e.g. "playlist_gen", "nl_search") and is stored
    on the ai_usage row so cost can be attributed per feature.

    Returns dict with keys:
      - "text": raw response text
      - "parsed": parsed JSON if response contains JSON, else None
      - "usage": {"input_tokens": int, "output_tokens": int}
      - "error": error message if request failed (other keys absent)
    """
    settings = get_settings()
    api_key = settings.assistant.claude_api_key
    if not api_key:
        return {"error": "No Claude API key configured"}

    use_model = model or settings.assistant.claude_model

    messages = [{"role": "user", "content": prompt}]
    body: dict = {
        "model": use_model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        body["system"] = system
    if temperature is not None:
        body["temperature"] = temperature

    # The semaphore guards *Claude* concurrency, so it wraps the HTTP call and
    # nothing else. Telemetry (an independent SQLite session that can sit on a
    # busy_timeout for up to 30s) is recorded after the slot is released —
    # otherwise bookkeeping contention would throttle real AI throughput.
    resp: httpx.Response | None = None
    failure: str | None = None       # ai_usage `error` value
    returned: dict | None = None     # early return for a transport failure

    async with _semaphore:
        client = _get_http_client()
        # Timer starts after the semaphore so queueing behind other calls
        # doesn't masquerade as Claude being slow.
        started = time.monotonic()
        try:
            resp = await client.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=body,
            )
        except httpx.TimeoutException:
            failure = "timeout"
            returned = {"error": "Claude API request timed out"}
        except Exception as e:
            log.error("Claude API error: %s", e)
            failure = type(e).__name__
            returned = {"error": str(e)}

    if returned is not None:
        await _track_usage(error=True)
        await _record_usage(
            feature=feature, model=use_model, started=started,
            success=False, error=failure,
        )
        return returned

    try:
        if resp.status_code != 200:
            error_body = resp.text[:500]
            log.error("Claude API error %d: %s", resp.status_code, error_body)
            await _track_usage(error=True)
            await _record_usage(
                feature=feature, model=use_model, started=started,
                success=False, error=f"http_{resp.status_code}",
            )
            return {"error": f"Claude API returned {resp.status_code}"}

        data = resp.json()
        usage = data.get("usage", {}) or {}
        input_tok = usage.get("input_tokens", 0) or 0
        output_tok = usage.get("output_tokens", 0) or 0
        cache_write_tok = usage.get("cache_creation_input_tokens", 0) or 0
        cache_read_tok = usage.get("cache_read_input_tokens", 0) or 0

        content = data.get("content", [])
        if not content:
            await _track_usage(error=True)
            # Tokens were still billed — record them with the failure.
            await _record_usage(
                feature=feature, model=use_model, started=started,
                input_tokens=input_tok, output_tokens=output_tok,
                cache_read_tokens=cache_read_tok,
                cache_write_tokens=cache_write_tok,
                success=False, error="empty_response",
            )
            return {"error": "Empty response from Claude"}

        text = content[0].get("text", "")

        await _track_usage(input_tokens=input_tok, output_tokens=output_tok)
        await _record_usage(
            feature=feature, model=use_model, started=started,
            input_tokens=input_tok, output_tokens=output_tok,
            cache_read_tokens=cache_read_tok,
            cache_write_tokens=cache_write_tok,
            success=True,
        )

        # Try to parse JSON from response
        parsed = _parse_json(text)

        return {
            "text": text,
            "parsed": parsed,
            "usage": {"input_tokens": input_tok, "output_tokens": output_tok},
        }

    except Exception as e:
        # Malformed body / decode failure after a successful transport.
        log.error("Claude API error: %s", e)
        await _track_usage(error=True)
        await _record_usage(
            feature=feature, model=use_model, started=started,
            success=False, error=type(e).__name__,
        )
        return {"error": str(e)}


def _parse_json(text: str) -> dict | list | None:
    """Parse JSON from Claude's response, handling code blocks."""
    # Extract from code blocks
    try:
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            text = text[start:end].strip()
        elif "```" in text:
            start = text.index("```") + 3
            end = text.index("```", start)
            text = text[start:end].strip()
    except ValueError:
        pass  # Unclosed code block — try parsing raw text

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Find JSON object or array in text
    for i, ch in enumerate(text):
        if ch in ('{', '['):
            open_ch, close_ch = ('{', '}') if ch == '{' else ('[', ']')
            depth = 0
            for j in range(i, len(text)):
                if text[j] == open_ch:
                    depth += 1
                elif text[j] == close_ch:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[i:j + 1])
                        except json.JSONDecodeError:
                            break
            break

    return None
