from __future__ import annotations

import os
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

SENSITIVE_PATHS = {"/api/admin/auth/login", "/api/admin/auth/password-reset/start", "/api/admin/broadcast"}


class SimpleRateLimiter:
    def __init__(self):
        self.ip_buckets: dict[str, deque[float]] = defaultdict(deque)
        self.user_buckets: dict[str, deque[float]] = defaultdict(deque)
        self.ip_limit = int(os.getenv("RATE_LIMIT_IP_PER_MINUTE", "120"))
        self.user_limit = int(os.getenv("RATE_LIMIT_USER_PER_MINUTE", "180"))

    def _consume(self, bucket: deque[float], limit: int, window_s: int = 60) -> bool:
        now = time.time()
        while bucket and now - bucket[0] > window_s:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True

    def check(self, ip: str, user_id: str | None = None) -> bool:
        if not self._consume(self.ip_buckets[ip], self.ip_limit):
            return False
        if user_id and not self._consume(self.user_buckets[user_id], self.user_limit):
            return False
        return True


rate_limiter = SimpleRateLimiter()


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        ip = request.client.host if request.client else "unknown"
        user_id = request.headers.get("x-user-id")

        if not rate_limiter.check(ip, user_id):
            return JSONResponse(status_code=429, content={"detail": "rate_limit_exceeded"})

        if request.url.path in SENSITIVE_PATHS:
            failures = int(request.headers.get("x-failed-attempts", "0"))
            threshold = int(os.getenv("CAPTCHA_THRESHOLD", "3"))
            if failures >= threshold and not request.headers.get("x-captcha-token"):
                return JSONResponse(status_code=400, content={"detail": "captcha_required"})

        return await call_next(request)


def validate_json_only(request: Request):
    content_type = request.headers.get("content-type", "")
    if request.method in {"POST", "PUT", "PATCH"} and "application/json" not in content_type:
        raise HTTPException(status_code=415, detail="json_only")
