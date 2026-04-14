"""
NOC Alert Command Center - Main Server
Enterprise-grade security with AES-256-GCM, Argon2id, 2FA, Rate Limiting, and Audit Logging

Refactored: Routes are now in /app/backend/routes/
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Response
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
import os
import logging
import jwt
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Load .env BEFORE local imports (security.py needs ENCRYPTION_KEY)
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Core dependencies
from database import db, mongo_client
from deps import (
    limiter, manager, redfish_poller, is_ip_blocked,
    JWT_SECRET, JWT_ALGORITHM
)

# Create the main app
app = FastAPI(
    title="NOC Alert Command Center API",
    description="Enterprise-grade alert management system with military-grade security",
    version="2.0.0"
)

# Add rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ==================== SECURITY HEADERS MIDDLEWARE ====================

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add enterprise security headers to all responses."""
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        # Security headers
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob: https:; "
            "font-src 'self' data: https:; "
            "connect-src 'self' wss: ws: https:; "
            "frame-ancestors 'none';"
        )
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
        # Cache Control differenziato
        if request.url.path.startswith("/api/auth") or request.url.path.startswith("/api/admin"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
            response.headers["Pragma"] = "no-cache"
        elif request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "private, max-age=0"
        return response


class IPBlockMiddleware(BaseHTTPMiddleware):
    """Middleware to block requests from banned IPs."""
    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host if request.client else None
        if client_ip and await is_ip_blocked(client_ip):
            return Response(
                content='{"detail":"IP address blocked. Contact administrator."}',
                status_code=403, media_type="application/json"
            )
        return await call_next(request)


# ==================== WEBSOCKET ====================

@app.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    token = websocket.query_params.get("token")
    if token:
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            if payload.get("requires_2fa"):
                await websocket.close(code=4001, reason="2FA required")
                return
        except jwt.InvalidTokenError:
            await websocket.close(code=4001, reason="Invalid token")
            return
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# ==================== ROOT ROUTES ====================

@app.get("/api/")
async def root():
    return {
        "message": "NOC Alert Command Center API",
        "version": "2.0.0",
        "security": "Enterprise-grade (AES-256-GCM, Argon2id, 2FA)"
    }

@app.get("/api/health")
async def health():
    return {"status": "healthy"}


@app.get("/api/health/detailed")
async def health_detailed():
    """Health check avanzato con metriche sistema per monitoring infrastruttura."""
    import psutil
    import time

    start = time.monotonic()

    # MongoDB check
    mongo_ok = False
    mongo_latency = None
    try:
        t0 = time.monotonic()
        await db.command("ping")
        mongo_latency = round((time.monotonic() - t0) * 1000, 1)
        mongo_ok = True
    except Exception:
        pass

    # System metrics
    cpu_pct = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")

    # Collection stats
    try:
        col_count = len(await db.list_collection_names())
    except Exception:
        col_count = 0

    # Worker info
    import os
    worker_pid = os.getpid()

    elapsed = round((time.monotonic() - start) * 1000, 1)

    return {
        "status": "healthy" if mongo_ok else "degraded",
        "response_ms": elapsed,
        "mongodb": {
            "connected": mongo_ok,
            "latency_ms": mongo_latency,
            "collections": col_count,
        },
        "system": {
            "cpu_percent": cpu_pct,
            "memory_used_mb": round(mem.used / 1024 / 1024),
            "memory_total_mb": round(mem.total / 1024 / 1024),
            "memory_percent": mem.percent,
            "disk_used_gb": round(disk.used / 1024 / 1024 / 1024, 1),
            "disk_total_gb": round(disk.total / 1024 / 1024 / 1024, 1),
            "disk_percent": round(disk.percent, 1),
        },
        "worker": {
            "pid": worker_pid,
        },
    }


# ==================== INCLUDE ALL ROUTE MODULES ====================

from routes.auth import router as auth_router
from routes.admin import router as admin_router
from routes.clients import router as clients_router
from routes.devices import router as devices_router
from routes.alerts import router as alerts_router
from routes.audit_routes import router as audit_router
from routes.vault import router as vault_router
from routes.redfish_routes import router as redfish_router
from routes.settings import router as settings_router
from routes.ingestion import router as ingestion_router
from routes.connector import router as connector_router
from routes.discovery import router as discovery_router
from routes.web_proxy import router as web_proxy_router
from routes.topology import router as topology_router
from routes.metrics import router as metrics_router
from routes.reports import router as reports_router
from routes.inventory import router as inventory_router
from routes.incidents import router as incidents_router
from routes.port_monitor import router as port_monitor_router
from routes.public_dashboard import router as public_dashboard_router
from routes.notification_config import router as notification_config_router
from routes.printers import router as printers_router
from routes.tv_dashboard import router as tv_dashboard_router
from routes.vulnerability import router as vulnerability_router
from routes.advanced_features import router as advanced_features_router
from routes.backup import router as backup_router
from routes.soc_ai import router as soc_ai_router
from routes.security_status import router as security_status_router
from routes.security_advanced import router as security_advanced_router
from routes.external_monitor import router as external_monitor_router

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(clients_router)
app.include_router(devices_router)
app.include_router(alerts_router)
app.include_router(audit_router)
app.include_router(vault_router)
app.include_router(redfish_router)
app.include_router(settings_router)
app.include_router(ingestion_router)
app.include_router(connector_router)
app.include_router(discovery_router)
app.include_router(web_proxy_router)
app.include_router(topology_router)
app.include_router(metrics_router)
app.include_router(reports_router)
app.include_router(inventory_router)
app.include_router(incidents_router)
app.include_router(port_monitor_router)
app.include_router(public_dashboard_router)
app.include_router(notification_config_router)
app.include_router(printers_router)
app.include_router(tv_dashboard_router)
app.include_router(vulnerability_router)
app.include_router(advanced_features_router)
app.include_router(backup_router)
app.include_router(soc_ai_router)
app.include_router(security_status_router)
app.include_router(security_advanced_router)
app.include_router(external_monitor_router)

# Include enterprise routes
from enterprise_routes import create_enterprise_router
from deps import get_current_user, audit_logger
enterprise_router = create_enterprise_router(db, get_current_user, audit_logger)
app.include_router(enterprise_router)


# ==================== MIDDLEWARE (order matters: bottom-up in Starlette) ====================

from middleware.global_rate_limiter import GlobalRateLimitMiddleware
from middleware.request_timeout import RequestTimeoutMiddleware
from middleware.honeypot import HoneypotMiddleware
from middleware.body_size_limit import BodySizeLimitMiddleware
from middleware.origin_verify import OriginVerifyMiddleware

# Build CORS origins - mai wildcard quando credentials=True
_cors_raw = os.environ.get('CORS_ORIGINS', '')
_cors_origins = [o.strip() for o in _cors_raw.split(',') if o.strip()]
if not _cors_origins:
    _cors_origins = ["https://*.emergentagent.com", "http://localhost:3000"]

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=_cors_origins,
    allow_origin_regex=r"https://.*\.emergentagent\.com",
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-CSRF-Token"],
    expose_headers=["X-CSRF-Token", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
    max_age=600,
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(GlobalRateLimitMiddleware)
app.add_middleware(RequestTimeoutMiddleware)
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(OriginVerifyMiddleware)
app.add_middleware(HoneypotMiddleware)
app.add_middleware(IPBlockMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=500)  # Comprimi risposte >500 bytes


# ==================== LOGGING ====================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ==================== LIFECYCLE ====================

@app.on_event("startup")
async def startup_event():
    """Start background services and ensure DB indexes on application startup."""
    # Create MongoDB indexes for performance
    try:
        await db.alerts.create_index([("client_id", 1), ("created_at", -1)])
        await db.alerts.create_index([("client_id", 1), ("status", 1)])
        await db.alerts.create_index([("device_ip", 1)])

        await db.device_poll_status.create_index([("client_id", 1)])
        await db.device_poll_status.create_index([("client_id", 1), ("device_ip", 1)], unique=True)

        await db.managed_devices.create_index([("client_id", 1)])
        await db.managed_devices.create_index([("client_id", 1), ("ip", 1)], unique=True)

        await db.metrics_history.create_index([("client_id", 1), ("timestamp", -1)])
        await db.metrics_history.create_index([("client_id", 1), ("device_ip", 1), ("timestamp", -1)])
        await db.metrics_history.create_index([("device_ip", 1), ("timestamp", -1)])

        await db.device_metrics_history.create_index([("client_id", 1), ("device_ip", 1), ("timestamp", -1)])

        await db.network_changes.create_index([("client_id", 1), ("timestamp", -1)])

        await db.incidents.create_index([("client_id", 1), ("status", 1)])
        await db.incidents.create_index([("status", 1), ("priority", 1)])
        await db.incidents.create_index([("created_at", -1)])

        await db.connector_status.create_index([("client_id", 1)], unique=True)
        await db.connector_status.create_index([("hostname", 1)])

        await db.discovered_endpoints.create_index([("client_id", 1)])
        await db.discovered_endpoints.create_index([("client_id", 1), ("ip", 1)])

        await db.lldp_neighbors.create_index([("client_id", 1), ("local_device_ip", 1)])
        await db.mac_connections.create_index([("client_id", 1), ("switch_ip", 1)])
        await db.port_speeds.create_index([("client_id", 1), ("device_ip", 1)])

        await db.port_monitors.create_index([("client_id", 1)])
        await db.deleted_devices.create_index([("client_id", 1), ("device_ip", 1)], unique=True)
        await db.notification_templates.create_index([("id", 1)], unique=True)
        await db.public_dashboards.create_index([("token", 1)], unique=True)
        await db.public_dashboards.create_index([("client_id", 1)], unique=True)

        # Printer indexes
        await db.printer_status.create_index([("client_id", 1)])
        await db.printer_status.create_index([("client_id", 1), ("device_ip", 1)], unique=True)
        await db.printer_history.create_index([("client_id", 1), ("device_ip", 1), ("timestamp", -1)])
        await db.printer_history.create_index("timestamp", expireAfterSeconds=86400 * 90)  # TTL 90 giorni

        # Vulnerability Assessment indexes
        await db.vulnerability_scans.create_index([("client_id", 1), ("timestamp", -1)])
        await db.vulnerability_scans.create_index("timestamp", expireAfterSeconds=86400 * 365)  # TTL 1 anno

        await db.audit_logs.create_index([("timestamp", -1)])
        await db.audit_logs.create_index([("user", 1), ("timestamp", -1)])

        await db.users.create_index([("email", 1)], unique=True)
        await db.clients.create_index([("id", 1)], unique=True)

        # TTL indexes for auto-cleanup
        from pymongo import ASCENDING
        await db.refresh_tokens.create_index("created_at", expireAfterSeconds=86400 * 30)
        await db.web_proxy_requests.create_index("created_at", expireAfterSeconds=300)

        # === NEW: Missing indexes for performance ===

        # WAN monitoring indexes + TTL
        await db.wan_targets.create_index([("client_id", 1)])
        await db.wan_probe_results.create_index([("target_id", 1)], unique=True)
        await db.wan_probe_results.create_index([("client_id", 1)])
        await db.wan_probe_history.create_index([("target_id", 1), ("timestamp", -1)])
        await db.wan_probe_history.create_index([("client_id", 1), ("timestamp", -1)])
        await db.wan_probe_history.create_index("timestamp", expireAfterSeconds=86400 * 7)  # TTL 7 giorni
        await db.wan_client_diagnosis.create_index([("client_id", 1)], unique=True)

        # Security indexes
        await db.login_attempts.create_index([("ip_address", 1), ("timestamp", -1)])
        await db.login_attempts.create_index([("email", 1), ("timestamp", -1)])
        await db.login_attempts.create_index("timestamp", expireAfterSeconds=86400 * 7)  # TTL 7 giorni
        await db.blocked_ips.create_index([("ip", 1)])
        await db.blocked_ips.create_index([("expires_at", 1)])

        # Session / Token indexes
        await db.refresh_tokens.create_index([("user_id", 1)])
        await db.sessions.create_index([("user_id", 1)])
        await db.sessions.create_index("last_activity", expireAfterSeconds=86400)  # TTL 1 giorno

        # Operational indexes
        await db.bandwidth_history.create_index([("device_ip", 1), ("timestamp", -1)])
        await db.bandwidth_history.create_index("timestamp", expireAfterSeconds=86400 * 30)  # TTL 30 giorni
        await db.maintenance_windows.create_index([("client_id", 1), ("end_time", -1)])
        await db.settings.create_index([("key", 1)], unique=True)
        await db.pending_commands.create_index([("client_id", 1), ("status", 1)])
        await db.connector_updates.create_index([("version", 1)])
        await db.escalation_rules.create_index([("client_id", 1)])
        await db.notification_logs.create_index("timestamp", expireAfterSeconds=86400 * 30)  # TTL 30 giorni

        # Audit logs TTL (auto-cleanup via MongoDB instead of manual delete)
        await db.audit_logs.create_index("timestamp", expireAfterSeconds=86400 * 90)  # TTL 90 giorni

        # Device metrics TTL
        await db.device_metrics_history.create_index("timestamp", expireAfterSeconds=86400 * 90)  # TTL 90 giorni
        await db.metrics_history.create_index("timestamp", expireAfterSeconds=86400 * 90)  # TTL 90 giorni

        logger.info("MongoDB indexes created/verified successfully")

    except Exception as e:
        logger.warning(f"Index creation warning (non-fatal): {e}")

    try:
        setting = await db.settings.find_one({"key": "redfish_poll_interval"})
        interval = setting.get("value", 5) if setting else 5
        await redfish_poller.start_scheduler(interval_minutes=interval)
        logger.info("Redfish polling scheduler started")
    except Exception as e:
        logger.error(f"Failed to start Redfish scheduler: {e}")

@app.on_event("shutdown")
async def shutdown_db_client():
    redfish_poller.stop_scheduler()
    mongo_client.close()
