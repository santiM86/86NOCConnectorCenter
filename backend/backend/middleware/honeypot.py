"""
Honeypot Endpoints - Endpoint fake che bannano automaticamente gli IP.
Percorsi comuni usati dagli scanner automatici (WordPress, phpMyAdmin, ecc.).
Qualsiasi hit su questi endpoint banna immediatamente l'IP.
"""
import logging
from datetime import datetime, timezone, timedelta
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("honeypot")

HONEYPOT_PATHS = frozenset({
    "/wp-admin", "/wp-login.php", "/wp-login", "/wp-content",
    "/administrator", "/admin.php", "/admin/login",
    "/phpmyadmin", "/pma", "/myadmin", "/mysql",
    "/.env", "/.git/config", "/.aws/credentials",
    "/xmlrpc.php", "/wp-cron.php",
    "/api/wp-admin", "/api/phpmyadmin", "/api/admin.php",
    "/shell", "/cmd", "/command", "/exec",
    "/cgi-bin/", "/config.php", "/setup.php",
    "/vendor/phpunit", "/.well-known/security.txt",
})


class HoneypotMiddleware(BaseHTTPMiddleware):
    """Auto-banna IP che colpiscono endpoint honeypot."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path.lower().rstrip("/")

        if path in HONEYPOT_PATHS or any(path.startswith(hp) for hp in HONEYPOT_PATHS if hp.endswith("/")):
            client_ip = request.client.host if request.client else "unknown"
            logger.critical(f"HONEYPOT HIT: {client_ip} -> {request.url.path}")

            try:
                from database import db
                from deps import audit_logger, _blocked_ips_cache
                from audit import AuditAction

                expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
                await db.blocked_ips.update_one(
                    {"ip": client_ip, "unblocked": {"$ne": True}},
                    {"$set": {
                        "ip": client_ip,
                        "reason": f"Honeypot: accesso a {request.url.path}",
                        "blocked_at": datetime.now(timezone.utc).isoformat(),
                        "expires_at": expires_at,
                        "permanent": False,
                        "unblocked": False,
                        "blocked_by": "honeypot",
                    }},
                    upsert=True,
                )
                _blocked_ips_cache["ips"].add(client_ip)

                await audit_logger.log(
                    AuditAction.IP_BLOCKED,
                    ip_address=client_ip,
                    details={
                        "reason": "honeypot_hit",
                        "path": request.url.path,
                        "method": request.method,
                    },
                    severity="critical",
                )
            except Exception as e:
                logger.error(f"Honeypot ban fallito: {e}")

            return Response(
                content="",
                status_code=404,
                media_type="text/plain",
            )

        return await call_next(request)
