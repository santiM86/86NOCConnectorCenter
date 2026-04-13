"""
Sliding Window Rate Limiter - Protezione globale su tutti gli endpoint /api/.
Max 600 richieste/minuto per IP (10/sec).
Pulizia automatica delle finestre scadute ogni 2 minuti.
"""
import time
import asyncio
import logging
from collections import defaultdict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("rate_limiter")

GLOBAL_MAX_REQUESTS = 600
WINDOW_SECONDS = 60
CLEANUP_INTERVAL = 120


class SlidingWindowEntry:
    __slots__ = ("timestamps",)

    def __init__(self):
        self.timestamps: list[float] = []

    def hit(self, now: float, window: int, max_req: int) -> bool:
        cutoff = now - window
        self.timestamps = [t for t in self.timestamps if t > cutoff]
        if len(self.timestamps) >= max_req:
            return False
        self.timestamps.append(now)
        return True

    def is_stale(self, now: float, window: int) -> bool:
        return not self.timestamps or self.timestamps[-1] < (now - window * 2)


class GlobalRateLimiter:
    def __init__(self, max_requests: int = GLOBAL_MAX_REQUESTS, window: int = WINDOW_SECONDS):
        self.max_requests = max_requests
        self.window = window
        self._buckets: dict[str, SlidingWindowEntry] = defaultdict(SlidingWindowEntry)
        self._cleanup_task = None

    def start_cleanup(self):
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self):
        while True:
            await asyncio.sleep(CLEANUP_INTERVAL)
            now = time.time()
            stale = [ip for ip, e in self._buckets.items() if e.is_stale(now, self.window)]
            for ip in stale:
                del self._buckets[ip]
            if stale:
                logger.debug(f"Rate limiter cleanup: rimossi {len(stale)} IP scaduti")

    def is_allowed(self, ip: str) -> bool:
        return self._buckets[ip].hit(time.time(), self.window, self.max_requests)

    def get_remaining(self, ip: str) -> int:
        now = time.time()
        entry = self._buckets.get(ip)
        if not entry:
            return self.max_requests
        cutoff = now - self.window
        active = [t for t in entry.timestamps if t > cutoff]
        return max(0, self.max_requests - len(active))


_global_limiter = GlobalRateLimiter()


class GlobalRateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding Window Rate Limiter su tutti gli endpoint /api/."""

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/api"):
            return await call_next(request)

        # Avvia cleanup task al primo request
        _global_limiter.start_cleanup()

        client_ip = request.client.host if request.client else "unknown"

        if not _global_limiter.is_allowed(client_ip):
            remaining = _global_limiter.get_remaining(client_ip)
            logger.warning(f"Global rate limit superato per IP {client_ip}")
            return Response(
                content='{"detail":"Troppe richieste. Riprova tra qualche secondo."}',
                status_code=429,
                media_type="application/json",
                headers={
                    "Retry-After": "60",
                    "X-RateLimit-Limit": str(GLOBAL_MAX_REQUESTS),
                    "X-RateLimit-Remaining": str(remaining),
                },
            )

        response = await call_next(request)
        remaining = _global_limiter.get_remaining(client_ip)
        response.headers["X-RateLimit-Limit"] = str(GLOBAL_MAX_REQUESTS)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
