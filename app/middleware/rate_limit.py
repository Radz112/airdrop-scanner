from __future__ import annotations

import logging
import time
from collections import defaultdict

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger("middleware.rate_limit")


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int = 100):
        super().__init__(app)
        self._rpm = requests_per_minute
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._last_cleanup = time.time()
        self._cleanup_interval = 300.0  # full sweep every 5 minutes

    async def dispatch(self, request: Request, call_next) -> Response:
        # Only rate-limit POST scan endpoints
        if request.method != "POST":
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        window_start = now - 60.0

        # Periodic full sweep: remove IPs with no recent hits
        if now - self._last_cleanup > self._cleanup_interval:
            stale = [ip for ip, ts in self._hits.items() if not ts or ts[-1] <= window_start]
            for ip in stale:
                del self._hits[ip]
            self._last_cleanup = now

        # Prune old entries for current IP
        hits = self._hits[client_ip]
        self._hits[client_ip] = [t for t in hits if t > window_start]

        if len(self._hits[client_ip]) >= self._rpm:
            logger.warning(
                f"Rate limited: ip={client_ip}, "
                f"hits={len(self._hits[client_ip])}/{self._rpm}"
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "detail": f"Max {self._rpm} requests per minute",
                    "retry_after_seconds": 60,
                },
            )

        self._hits[client_ip].append(now)
        return await call_next(request)
