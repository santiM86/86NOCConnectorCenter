"""
MongoDB-backed Rate Limiter - Funziona con multi-worker.
Sliding window counter persistito su MongoDB.
Fallback in-memory se MongoDB non disponibile.
"""
import time
import asyncio
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("rate_limiter")

GLOBAL_MAX_REQUESTS = 600
WINDOW_SECONDS = 60


class MongoRateLimiter:
    """Rate limiter che usa MongoDB come backend condiviso tra worker."""

    def __init__(self, max_requests: int = GLOBAL_MAX_REQUESTS, window: int = WINDOW_SECONDS):
        self.max_requests = max_requests
        self.window = window
        self._db = None
        self._fallback = {}  # in-memory fallback

    def _get_db(self):
        if self._db is None:
            try:
                from database import db
                self._db = db
            except Exception:
                pass
        return self._db

    async def is_allowed(self, ip: str) -> tuple:
        """Returns (allowed: bool, remaining: int)."""
        db = self._get_db()
        if db is None:
            return self._fallback_check(ip)

        now = time.time()
        cutoff = now - self.window
        collection = db.rate_limit_counters

        try:
            # Atomic increment: count requests in window
            result = await collection.find_one_and_update(
                {"ip": ip},
                {
                    "$push": {"hits": {"$each": [now], "$position": 0}},
                    "$set": {"updated_at": now},
                },
                upsert=True,
                return_document=True,
            )

            hits = result.get("hits", [])
            # Trim old hits
            active_hits = [h for h in hits if h > cutoff]
            if len(active_hits) != len(hits):
                await collection.update_one(
                    {"ip": ip},
                    {"$set": {"hits": active_hits}}
                )

            count = len(active_hits)
            remaining = max(0, self.max_requests - count)

            if count > self.max_requests:
                return False, 0
            return True, remaining

        except Exception as e:
            logger.debug(f"MongoDB rate limit fallback: {e}")
            return self._fallback_check(ip)

    def _fallback_check(self, ip: str) -> tuple:
        """Fallback in-memory per quando MongoDB non è disponibile."""
        now = time.time()
        cutoff = now - self.window
        if ip not in self._fallback:
            self._fallback[ip] = []
        self._fallback[ip] = [t for t in self._fallback[ip] if t > cutoff]
        self._fallback[ip].append(now)
        count = len(self._fallback[ip])
        remaining = max(0, self.max_requests - count)
        return count <= self.max_requests, remaining

    async def cleanup(self):
        """Pulizia periodica dei record scaduti."""
        db = self._get_db()
        if db is None:
            # Cleanup in-memory
            now = time.time()
            cutoff = now - self.window * 2
            stale = [ip for ip, hits in self._fallback.items() if not hits or hits[-1] < cutoff]
            for ip in stale:
                del self._fallback[ip]
            return

        try:
            cutoff = time.time() - self.window * 2
            await db.rate_limit_counters.delete_many({"updated_at": {"$lt": cutoff}})
        except Exception:
            pass


_limiter = MongoRateLimiter()


class GlobalRateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding Window Rate Limiter su tutti gli endpoint /api/."""

    _cleanup_started = False

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/api"):
            return await call_next(request)

        # Start cleanup task once
        if not GlobalRateLimitMiddleware._cleanup_started:
            GlobalRateLimitMiddleware._cleanup_started = True
            asyncio.create_task(self._cleanup_loop())

        client_ip = request.client.host if request.client else "unknown"

        allowed, remaining = await _limiter.is_allowed(client_ip)

        if not allowed:
            logger.warning(f"Global rate limit superato per IP {client_ip}")
            return Response(
                content='{"detail":"Troppe richieste. Riprova tra qualche secondo."}',
                status_code=429,
                media_type="application/json",
                headers={
                    "Retry-After": "60",
                    "X-RateLimit-Limit": str(GLOBAL_MAX_REQUESTS),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(GLOBAL_MAX_REQUESTS)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response

    async def _cleanup_loop(self):
        while True:
            await asyncio.sleep(120)
            await _limiter.cleanup()
