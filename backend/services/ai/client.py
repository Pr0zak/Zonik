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

# Concurrency limiter — max 2 simultaneous Claude requests
_semaphore = asyncio.Semaphore(2)

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


async def call_claude(
    prompt: str,
    *,
    system: str | None = None,
    max_tokens: int = 4096,
    model: str | None = None,
    temperature: float | None = None,
) -> dict:
    """Send a prompt to Claude with concurrency control and token tracking.

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

    async with _semaphore:
        client = _get_http_client()
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

            if resp.status_code != 200:
                error_body = resp.text[:500]
                log.error("Claude API error %d: %s", resp.status_code, error_body)
                await _track_usage(error=True)
                return {"error": f"Claude API returned {resp.status_code}"}

            data = resp.json()
            content = data.get("content", [])
            if not content:
                await _track_usage(error=True)
                return {"error": "Empty response from Claude"}

            text = content[0].get("text", "")
            usage = data.get("usage", {})
            input_tok = usage.get("input_tokens", 0)
            output_tok = usage.get("output_tokens", 0)

            await _track_usage(input_tokens=input_tok, output_tokens=output_tok)

            # Try to parse JSON from response
            parsed = _parse_json(text)

            return {
                "text": text,
                "parsed": parsed,
                "usage": {"input_tokens": input_tok, "output_tokens": output_tok},
            }

        except httpx.TimeoutException:
            await _track_usage(error=True)
            return {"error": "Claude API request timed out"}
        except Exception as e:
            log.error("Claude API error: %s", e)
            await _track_usage(error=True)
            return {"error": str(e)}


def _parse_json(text: str) -> dict | None:
    """Parse JSON from Claude's response, handling code blocks."""
    # Extract from code blocks
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start)
        text = text[start:end].strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Find JSON object in text
    for i, ch in enumerate(text):
        if ch == '{':
            depth = 0
            for j in range(i, len(text)):
                if text[j] == '{':
                    depth += 1
                elif text[j] == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[i:j + 1])
                        except json.JSONDecodeError:
                            break
            break

    return None
