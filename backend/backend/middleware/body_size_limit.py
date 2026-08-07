"""
Request Body Size Limit Middleware.
Limita la dimensione del payload per prevenire attacchi DoS.
Default: 10MB per endpoint normali, 50MB per upload.
"""
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("body_size_limit")

DEFAULT_MAX_BODY = 10 * 1024 * 1024       # 10 MB
UPLOAD_MAX_BODY = 50 * 1024 * 1024         # 50 MB
UPLOAD_PATHS = ("/api/connector/upload", "/api/connector/update")


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Rifiuta richieste con payload troppo grande."""

    async def dispatch(self, request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH"):
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    size = int(content_length)
                    path = request.url.path.lower()
                    max_size = UPLOAD_MAX_BODY if any(path.startswith(p) for p in UPLOAD_PATHS) else DEFAULT_MAX_BODY

                    if size > max_size:
                        max_mb = max_size // (1024 * 1024)
                        logger.warning(
                            f"Body size limit superato: {size} bytes da "
                            f"{request.client.host if request.client else 'unknown'} "
                            f"su {path}"
                        )
                        return Response(
                            content=f'{{"detail":"Payload troppo grande. Max {max_mb}MB."}}',
                            status_code=413,
                            media_type="application/json",
                        )
                except ValueError:
                    pass

        return await call_next(request)
