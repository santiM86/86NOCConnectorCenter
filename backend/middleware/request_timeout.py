"""
Request Timeout Middleware - Previene attacchi slowloris / richieste appese.
Timeout differenziato per tipo di endpoint:
  - 20s standard
  - 45s Jira/connector
  - 120s AI/SOC
  - 180s sync/backup
"""
import asyncio
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("request_timeout")

TIMEOUT_RULES = [
    (("/api/soc/", "/api/vulnerability/report/pdf"), 120),
    (("/api/connector/", "/api/backup/"), 45),
    (("/api/discovery/run",), 180),
]
DEFAULT_TIMEOUT = 20


def _get_timeout(path: str) -> int:
    for prefixes, timeout in TIMEOUT_RULES:
        if any(path.startswith(p) for p in prefixes):
            return timeout
    return DEFAULT_TIMEOUT


class RequestTimeoutMiddleware(BaseHTTPMiddleware):
    """Applica timeout differenziati per tipo di endpoint → risposta 504."""

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/api"):
            return await call_next(request)

        timeout = _get_timeout(request.url.path)

        try:
            response = await asyncio.wait_for(call_next(request), timeout=timeout)
            return response
        except asyncio.TimeoutError:
            logger.warning(
                f"Request timeout ({timeout}s) per {request.method} {request.url.path} "
                f"da IP {request.client.host if request.client else 'unknown'}"
            )
            return Response(
                content='{"detail":"Timeout della richiesta. Riprova più tardi."}',
                status_code=504,
                media_type="application/json",
            )
