"""In-memory token bucket rate limiter middleware."""
from __future__ import annotations

import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class RateLimiter(BaseHTTPMiddleware):
    """Token bucket rate limiter for API endpoints.

    Args:
        app: ASGI application
        rate: Requests per second (tokens added per second)
        burst: Maximum bucket size (max burst)
        paths: Optional list of path prefixes to rate-limit (default: /api/)
    """

    def __init__(self, app, rate: float = 10, burst: int = 30, paths: list[str] | None = None, exclude: list[str] | None = None):
        super().__init__(app)
        self.rate = rate
        self.burst = burst
        self.paths = paths or ["/api/"]
        self.exclude = exclude or ["/api/download/", "/rest/"]
        self._buckets: dict[str, tuple[float, float]] = defaultdict(lambda: (burst, time.monotonic()))

    def _get_key(self, request: Request) -> str:
        """Rate limit key — by client IP."""
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _should_limit(self, path: str) -> bool:
        """Check if this path should be rate-limited."""
        if any(path.startswith(p) for p in self.exclude):
            return False
        return any(path.startswith(p) for p in self.paths)

    def _consume(self, key: str) -> bool:
        """Try to consume a token. Returns True if allowed, False if rate-limited."""
        tokens, last_time = self._buckets[key]
        now = time.monotonic()
        elapsed = now - last_time

        # Add tokens based on elapsed time
        tokens = min(self.burst, tokens + elapsed * self.rate)

        if tokens >= 1:
            self._buckets[key] = (tokens - 1, now)
            return True

        self._buckets[key] = (tokens, now)
        return False

    async def dispatch(self, request: Request, call_next):
        # Skip non-API paths and WebSocket
        if not self._should_limit(request.url.path):
            return await call_next(request)

        # Skip WebSocket upgrades
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)

        key = self._get_key(request)
        if not self._consume(key):
            return JSONResponse(
                status_code=429,
                content={"error": "Rate limit exceeded. Please slow down."},
                headers={"Retry-After": str(int(1 / self.rate))},
            )

        return await call_next(request)
