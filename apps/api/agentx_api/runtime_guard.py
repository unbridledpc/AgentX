from __future__ import annotations

import contextvars
import json
import logging
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from agentx_api.config import config

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("agentx_request_id", default="-")


class JsonFormatter(logging.Formatter):
    """Small JSON log formatter without adding a structlog dependency."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", request_id_var.get()),
        }
        for key in ("method", "path", "status_code", "duration_ms", "client_ip"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging() -> None:
    level_name = str(getattr(config, "log_level", "INFO") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    for handler in root.handlers:
        handler.setFormatter(JsonFormatter())
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)


@dataclass
class RateLimitDecision:
    allowed: bool
    retry_after_s: int = 0
    remaining: int = 0


class InMemorySlidingWindowRateLimiter:
    def __init__(self, limit: int, window_s: int) -> None:
        self.limit = max(1, int(limit))
        self.window_s = max(1, int(window_s))
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, now: float | None = None) -> RateLimitDecision:
        now = time.monotonic() if now is None else now
        bucket = self._hits[key]
        cutoff = now - self.window_s
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self.limit:
            retry_after = max(1, int(self.window_s - (now - bucket[0])))
            return RateLimitDecision(False, retry_after_s=retry_after, remaining=0)
        bucket.append(now)
        return RateLimitDecision(True, remaining=max(0, self.limit - len(bucket)))


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Adds request IDs, structured access logs, and optional local rate limiting."""

    def __init__(self, app, rate_limiter: InMemorySlidingWindowRateLimiter | None = None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.rate_limiter = rate_limiter
        self.logger = logging.getLogger("agentx_api.access")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:  # type: ignore[type-arg]
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = request_id_var.set(request_id)
        start = time.perf_counter()
        client_ip = request.client.host if request.client else "unknown"
        try:
            if self.rate_limiter is not None and not request.url.path.startswith("/v1/status"):
                decision = self.rate_limiter.check(client_ip)
                if not decision.allowed:
                    response = JSONResponse(
                        {"detail": "Rate limit exceeded.", "request_id": request_id, "retry_after_s": decision.retry_after_s},
                        status_code=429,
                    )
                    response.headers["Retry-After"] = str(decision.retry_after_s)
                    response.headers["X-Request-ID"] = request_id
                    return response

            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            status_code = locals().get("response").status_code if "response" in locals() else 500
            self.logger.info(
                "request complete",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                    "client_ip": client_ip,
                },
            )
            request_id_var.reset(token)


def build_rate_limiter() -> InMemorySlidingWindowRateLimiter | None:
    if not getattr(config, "rate_limit_enabled", False):
        return None
    return InMemorySlidingWindowRateLimiter(
        limit=getattr(config, "rate_limit_requests", 120),
        window_s=getattr(config, "rate_limit_window_s", 60),
    )
