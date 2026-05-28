"""
Origin Verification Middleware (CSRF Protection).
Verifica l'header Origin/Referer su operazioni mutanti (POST/PUT/DELETE/PATCH).
Rifiuta richieste da origini sconosciute su endpoint sensibili.
"""
import os
import re
import logging
import fnmatch
from urllib.parse import urlparse
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
    r"^https?://(localhost(:\d+)?|.*\.emergentagent\.com|.*\.emergentcf\.cloud|.*\.86bit\.it)$"
)


def _is_origin_allowed(origin: str) -> bool:
    if not origin:
        return True

    # Estrae scheme://netloc per evitare che la parte di path (es. referer) infici il matching
    try:
        parsed = urlparse(origin)
        if parsed.scheme and parsed.netloc:
            origin_base = f"{parsed.scheme}://{parsed.netloc}"
        else:
            origin_base = origin
    except Exception:
        origin_base = origin

    # 1. Verifica regex predefinita
    if ALLOWED_ORIGIN_RE.match(origin_base):
        return True

    # 2. Verifica dinamica tramite CORS_ORIGINS caricato dall'ambiente
    cors_raw = os.environ.get('CORS_ORIGINS', '')
    cors_origins = [o.strip() for o in cors_raw.split(',') if o.strip()]

    origin_clean = origin_base.strip().lower()
    for pattern in cors_origins:
        pattern_clean = pattern.strip().lower()
        if fnmatch.fnmatch(origin_clean, pattern_clean):
            return True

    return False



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

        if not _is_origin_allowed(origin):
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
