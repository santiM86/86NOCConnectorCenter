"""
Origin Verification Middleware (CSRF Protection).
Verifica l'header Origin/Referer su operazioni mutanti (POST/PUT/DELETE/PATCH).
Rifiuta richieste da origini sconosciute su endpoint sensibili.
"""
import os
import re
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("origin_verify")

MUTATING_METHODS = {"POST", "PUT", "DELETE", "PATCH"}

SAFE_PATHS = frozenset({
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/refresh",
    "/api/health",
    "/api/",
})

CONNECTOR_PREFIX = "/api/connector/"
INGESTION_PREFIX = "/api/ingestion/"

ALLOWED_ORIGIN_RE = re.compile(
    r"^https?://(localhost(:\d+)?|.*\.emergentagent\.com|.*\.86bit\.it)$"
)


class OriginVerifyMiddleware(BaseHTTPMiddleware):
    """Verifica Origin su operazioni sensibili (CSRF-like)."""

    async def dispatch(self, request: Request, call_next):
        if request.method not in MUTATING_METHODS:
            return await call_next(request)

        path = request.url.path

        if path.startswith(CONNECTOR_PREFIX) or path.startswith(INGESTION_PREFIX):
            return await call_next(request)

        if path in SAFE_PATHS:
            return await call_next(request)

        origin = request.headers.get("origin") or request.headers.get("referer", "")

        if not origin:
            return await call_next(request)

        if origin and not ALLOWED_ORIGIN_RE.match(origin):
            client_ip = request.client.host if request.client else "unknown"
            logger.warning(
                f"Origin non autorizzato: {origin} da {client_ip} su {request.method} {path}"
            )
            try:
                from deps import audit_logger
                from audit import AuditAction
                await audit_logger.log(
                    AuditAction.SUSPICIOUS_ACTIVITY,
                    ip_address=client_ip,
                    details={"reason": "invalid_origin", "origin": origin, "path": path, "method": request.method},
                    severity="warning",
                )
            except Exception:
                pass

            return Response(
                content='{"detail":"Origine non autorizzata."}',
                status_code=403,
                media_type="application/json",
            )

        return await call_next(request)
