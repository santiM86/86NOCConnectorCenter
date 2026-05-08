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
    limiter, manager, redfish_poller,
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
    """Add enterprise security headers to all responses.

    Exception: /api/web-proxy/live/* (Web Console iframe) needs to be embeddable
    inside the ARGUS app iframe, so X-Frame-Options and CSP frame-ancestors are
    explicitly relaxed for these paths only.
    """
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path or ""
        is_web_console_live = path.startswith("/api/web-proxy/live/")

        # X-Frame-Options: DENY bloccherebbe l'iframe Web Console.
        # Per il proxy LIVE permettiamo SAMEORIGIN (iframe dentro argus.86bit.it).
        response.headers["X-Frame-Options"] = "SAMEORIGIN" if is_web_console_live else "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"

        if is_web_console_live:
            # CSP rilassata per iframe: permette script/style inline del device remoto,
            # frame-ancestors 'self' (solo dentro ARGUS). NIENTE upgrade-insecure-requests
            # perche' il content proxato passa gia' via HTTPS.
            response.headers["Content-Security-Policy"] = (
                "default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob:; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob:; "
                "style-src 'self' 'unsafe-inline' data:; "
                "img-src 'self' data: blob: https: http:; "
                "font-src 'self' data: https: http:; "
                "connect-src 'self' https: http: wss: ws:; "
                "frame-src 'self' data: blob:; "
                "frame-ancestors 'self';"
            )
        else:
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
        if is_web_console_live:
            # La Web Console LIVE imposta gia' i propri header Cache-Control nella route.
            # Non sovrascriverli qui.
            pass
        elif request.url.path.startswith("/api/auth") or request.url.path.startswith("/api/admin"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
            response.headers["Pragma"] = "no-cache"
        elif request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "private, max-age=0"
        return response


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
from routes.web_console_live import router as web_console_live_router
from routes.web_console_enterprise import router as web_console_enterprise_router
from routes.cmdb import router as cmdb_router
from routes.runbooks import router as runbooks_router
from routes.sla import router as sla_router
from routes.customer_portal import router as customer_portal_router
from routes.itsm import router as itsm_router
from routes.topology import router as topology_router
from routes.metrics import router as metrics_router
from routes.reports import router as reports_router
from routes.inventory import router as inventory_router
from routes.incidents import router as incidents_router
from routes.port_monitor import router as port_monitor_router
from routes.public_dashboard import router as public_dashboard_router
from routes.notification_config import router as notification_config_router
from routes.printers import router as printers_router
from routes.printer_discovery import router as printer_discovery_router
from routes.tv_dashboard import router as tv_dashboard_router
from routes.vulnerability import router as vulnerability_router
from routes.advanced_features import router as advanced_features_router
from routes.backup import router as backup_router
from routes.soc_ai import router as soc_ai_router
from routes.security_status import router as security_status_router
from routes.security_advanced import router as security_advanced_router
from routes.external_monitor import router as external_monitor_router
from routes.push import router as push_router
from routes.oncall import router as oncall_router
from routes.escalation import router as escalation_router
from routes.app_version import router as app_version_router
from routes.overview import router as overview_router
from routes.remediation import router as remediation_router
from routes.lifecycle import router as lifecycle_router
from routes.intelligence import router as intelligence_router
from routes.auto_dispatch import router as auto_dispatch_router
from routes.firmware_catalog import router as firmware_catalog_router
from routes.web_console_v4 import router as web_console_v4_router
from routes.device_profiles import router as device_profiles_router
from routes.connector_settings import router as connector_settings_router
from routes.hornetsecurity_backup import router as hornetsecurity_backup_router
from routes.hornetsecurity_vmbackup import router as hornetsecurity_vmbackup_router
from routes.datto_rmm import router as datto_rmm_router
from routes.security_admin import router as security_admin_router
from routes.agent_ws import router as agent_ws_router  # 86NocAgent v4 WS+control plane

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
app.include_router(agent_ws_router)  # 86NocAgent v4
app.include_router(discovery_router)
app.include_router(web_proxy_router)
app.include_router(web_console_live_router)
app.include_router(web_console_enterprise_router)
app.include_router(cmdb_router)
app.include_router(runbooks_router)
app.include_router(sla_router)
app.include_router(customer_portal_router)
app.include_router(itsm_router)
app.include_router(topology_router)
app.include_router(metrics_router)
app.include_router(reports_router)
app.include_router(inventory_router)
app.include_router(incidents_router)
app.include_router(port_monitor_router)
app.include_router(public_dashboard_router)
app.include_router(notification_config_router)
app.include_router(printers_router)
app.include_router(printer_discovery_router)
app.include_router(tv_dashboard_router)
app.include_router(vulnerability_router)
app.include_router(advanced_features_router)
app.include_router(backup_router)
app.include_router(soc_ai_router)
app.include_router(security_status_router)
app.include_router(security_advanced_router)
app.include_router(external_monitor_router)
app.include_router(push_router)
app.include_router(oncall_router)
app.include_router(escalation_router)
app.include_router(app_version_router)
app.include_router(overview_router)
app.include_router(remediation_router)
app.include_router(lifecycle_router)
app.include_router(intelligence_router)
app.include_router(auto_dispatch_router)
app.include_router(firmware_catalog_router)
app.include_router(web_console_v4_router)
app.include_router(device_profiles_router)
app.include_router(connector_settings_router)
app.include_router(hornetsecurity_backup_router)
app.include_router(hornetsecurity_vmbackup_router)
app.include_router(datto_rmm_router)
app.include_router(security_admin_router)
from routes.security_admin import audit_router as audit_dashboard_router
app.include_router(audit_dashboard_router)
from routes.device_probe import router as device_probe_router
app.include_router(device_probe_router)
from routes.console_rmt import router as console_rmt_router
app.include_router(console_rmt_router)
from routes.console_rmt_http import router as console_rmt_http_router
app.include_router(console_rmt_http_router)
from routes.console_rmt_v2 import router as console_rmt_v2_router
app.include_router(console_rmt_v2_router)
from routes.security_allowlist import router as security_allowlist_router, IPAllowlistMiddleware
app.include_router(security_allowlist_router)
from routes.wireguard import router as wireguard_router
app.include_router(wireguard_router)
from routes.system_admin import router as system_admin_router
app.include_router(system_admin_router)# IP Allowlist middleware: blocca admin endpoints da IP non autorizzati.
# Posizionato dopo il routing setup in modo da intercettare ogni request.
app.add_middleware(IPAllowlistMiddleware)
from routes.metric_history import router as metric_history_router, ensure_index as ensure_metric_idx
app.include_router(metric_history_router)
from routes.syslog_trap import router as syslog_trap_router, _ensure_indexes as ensure_syslog_idx
app.include_router(syslog_trap_router)
from routes.device_info_card import router as device_info_card_router
app.include_router(device_info_card_router)
from routes.admin_integrations import router as admin_integrations_router
app.include_router(admin_integrations_router)
from routes.arp_cache import router as arp_cache_router, ensure_arp_idx
app.include_router(arp_cache_router)

# Include enterprise routes
from enterprise_routes import create_enterprise_router
from deps import get_current_user, audit_logger
enterprise_router = create_enterprise_router(db, get_current_user, audit_logger)
app.include_router(enterprise_router)


# ==================== MIDDLEWARE (order matters: bottom-up in Starlette) ====================

from middleware.global_rate_limiter import GlobalRateLimitMiddleware
from middleware.request_timeout import RequestTimeoutMiddleware
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
# v3.8.21: GlobalRateLimitMiddleware DISABILITATO. Causava 429 a cascata in produzione
# perche' dietro proxy (Emergent ingress / nginx) request.client.host punta all'IP del
# proxy stesso, non al client reale: tutte le request finiscono nello stesso bucket
# e dopo ~600 req/min totali (UI admin + connector heartbeat + device-report + web-proxy
# long-poll + network-discovery + ecc.) tutti i client vengono rate-limited insieme.
# L'utente aveva gia' richiesto la rimozione il 10/02/2026 (vedi PRD.md).
# app.add_middleware(GlobalRateLimitMiddleware)
app.add_middleware(RequestTimeoutMiddleware)
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(OriginVerifyMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=500)  # Comprimi risposte >500 bytes


# ==================== LOGGING ====================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# SECURITY: silenzia logger di librerie HTTP che stampano URL completi con
# query string (api_key, userId, token in chiaro). Livello WARNING cattura
# solo errori reali, non le request di routine.
for _noisy in ("httpx", "httpcore", "httpcore.http11", "httpcore.connection",
               "httpx._client", "urllib3.connectionpool"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


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

        # Time-series + syslog/trap TTL indexes
        await ensure_metric_idx()
        await ensure_syslog_idx()
        await ensure_arp_idx()

        await db.network_changes.create_index([("client_id", 1), ("timestamp", -1)])

        await db.incidents.create_index([("client_id", 1), ("status", 1)])
        await db.incidents.create_index([("status", 1), ("priority", 1)])
        await db.incidents.create_index([("created_at", -1)])

        # v3.8.1: chiave composita su (client_id, hostname, mode) per supportare:
        # - 1 master + N scanner su VLAN diverse (hostname differenti)
        # - Master + Scanner sulla STESSA macchina (stesso hostname, mode diverso)
        # Drop+recreate per upgrade in-place.
        try:
            existing_idx = await db.connector_status.list_indexes().to_list(20)
            for idx in existing_idx:
                name = idx.get("name", "")
                if (name == "client_id_1" and idx.get("unique")) or name == "client_hostname_unique":
                    await db.connector_status.drop_index(name)
        except Exception:
            pass
        await db.connector_status.create_index(
            [("client_id", 1), ("hostname", 1), ("mode", 1)],
            unique=True,
            name="client_hostname_mode_unique",
        )
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

        # Notification delivery log indexes (admin audit)
        await db.notification_delivery_log.create_index([("alert_id", 1), ("created_at_ts", 1)])
        await db.notification_delivery_log.create_index(
            "created_at_ts", expireAfterSeconds=86400 * 90
        )  # TTL 90 giorni

        # === Enterprise performance indexes (push, quiet hours, on-call, escalation) ===
        # push_subscriptions: lookup by user_id on every alert
        await db.push_subscriptions.create_index("user_id")
        await db.push_subscriptions.create_index("subscription.endpoint")
        # user_notification_prefs: lookup by user_id on every notification
        await db.user_notification_prefs.create_index("user_id", unique=True)
        # users.role: used in send_to_roles + oncall/users
        await db.users.create_index("role")
        # users.id: not unique (legacy docs may have null id in some deploys)
        await db.users.create_index("id")
        # web_proxy_requests: long-poll query + lookup by request_id
        await db.web_proxy_requests.create_index([("client_id", 1), ("status", 1)])
        await db.web_proxy_requests.create_index("request_id")
        # Web Console Enterprise B: metrics + session cookie jar
        await db.web_proxy_metrics.create_index([("client_id", 1), ("timestamp", -1)])
        await db.web_proxy_metrics.create_index("timestamp", expireAfterSeconds=86400 * 30)  # TTL 30gg
        await db.web_proxy_sessions.create_index(
            [("session_id", 1), ("client_id", 1), ("device_ip", 1)], unique=True
        )
        await db.web_proxy_sessions.create_index("created_at", expireAfterSeconds=3600 * 8)  # TTL 8h
        # Web Console LIVE token (capability) — TTL 8h
        await db.web_console_tokens.create_index("session_id", unique=True)
        await db.web_console_tokens.create_index("expires_at", expireAfterSeconds=0)
        # Web Console ENTERPRISE
        await db.web_console_history.create_index([("user_email", 1), ("started_at", -1)])
        await db.web_console_history.create_index([("device_ip", 1), ("started_at", -1)])
        await db.web_console_history.create_index("session_id")
        # History TTL 90 giorni
        await db.web_console_history.create_index("started_at", expireAfterSeconds=86400 * 90)
        await db.web_console_favorites.create_index([("user_email", 1), ("device_ip", 1)], unique=True)
        await db.web_console_shares.create_index("share_token", unique=True)
        await db.web_console_shares.create_index("expires_at", expireAfterSeconds=0)

        # iLO Telemetry time-series (enterprise real-time stats)
        await db.ilo_telemetry.create_index([("device_ip", 1), ("timestamp", -1)])
        # TTL 7 giorni (grafici short-term)
        await db.ilo_telemetry.create_index("timestamp", expireAfterSeconds=86400 * 7)

        # INOC-like ITIL collections
        await db.cmdb_assets.create_index("device_ip", unique=True)
        await db.cmdb_assets.create_index("client_id")
        await db.cmdb_assets.create_index("warranty_end")
        await db.runbooks.create_index("id", unique=True)
        await db.runbooks.create_index("device_types")
        await db.sla_targets.create_index("client_id", unique=True)
        await db.customer_users.create_index("email", unique=True)
        await db.customer_users.create_index("client_id")
        await db.changes.create_index("id", unique=True)
        await db.changes.create_index([("status", 1), ("created_at", -1)])
        await db.problems.create_index("id", unique=True)
        await db.problems.create_index("status")

        # Remediation Engine + Hardware Lifecycle + Intelligence (2026-02)
        try:
            from routes.remediation import init_indexes as _rem_idx
            from routes.lifecycle import init_indexes as _lc_idx
            from routes.intelligence import init_indexes as _intel_idx
            from routes.firmware_catalog import init_indexes as _fw_idx
            await _rem_idx()
            await _lc_idx()
            await _intel_idx()
            await _fw_idx()
        except Exception as _ix_err:
            logging.getLogger(__name__).warning(f"remediation/lifecycle/intelligence indexes: {_ix_err}")
        # alerts: escalation scan (active + severity + ack + time)
        await db.alerts.create_index(
            [("status", 1), ("severity", 1), ("escalated", 1), ("created_at", 1)]
        )
        # alerts.id: not unique (legacy docs with null id)
        await db.alerts.create_index("id")

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

        # === SCALE-UP indexes (v3.6.17) — pronti per migliaia di device ===
        # vmbackup_jobs (18k+ docs in deploy reali): upsert key + aggregations
        try:
            await db.vmbackup_jobs.create_index(
                [("customer_name", 1), ("host_name", 1), ("vm_id", 1)],
                unique=True, name="vm_upsert_key",
            )
        except Exception:
            pass
        await db.vmbackup_jobs.create_index([("source", 1), ("customer_name", 1)])
        await db.vmbackup_jobs.create_index([("client_id", 1), ("alert_reason", 1)])
        await db.vmbackup_jobs.create_index([("customer_name", 1), ("host_name", 1)])

        # backup_job_status (4k+ docs)
        await db.backup_job_status.create_index([("client_id", 1), ("workload_name", 1)])
        await db.backup_job_status.create_index([("client_id", 1), ("alert_reason", 1)])
        await db.backup_job_status.create_index([("device_ip", 1), ("timestamp", -1)])

        # switch_ports: query principale by local_ip + sort idx (topology.py)
        await db.switch_ports.create_index([("local_ip", 1), ("idx", 1)])

        # discovered_endpoints: aggiunti switch_ip e mac (per topology + cleanup binding)
        await db.discovered_endpoints.create_index([("switch_ip", 1)])
        await db.discovered_endpoints.create_index([("mac", 1)])

        # network_discovery: scan recente per remote_port_cache
        await db.network_discovery.create_index([("client_id", 1), ("updated_at", -1)])

        # mac_device_bindings (v3.6.16) — UNIQUE per evitare duplicati
        try:
            await db.mac_device_bindings.create_index([("mac", 1)], unique=True)
        except Exception:
            pass
        await db.mac_device_bindings.create_index([("client_id", 1)])

        # bmc_candidates (v3.6.14)
        try:
            await db.bmc_candidates.create_index([("client_id", 1), ("ip", 1)], unique=True)
        except Exception:
            pass
        await db.bmc_candidates.create_index([("dismissed", 1), ("last_seen", -1)])

        # port_flap_events (sparkline 24h query)
        await db.port_flap_events.create_index([("local_ip", 1), ("idx", 1), ("ts", -1)])
        await db.port_flap_events.create_index("ts", expireAfterSeconds=86400 * 30)  # TTL 30gg

        # devices (manual+ created via discovery)
        await db.devices.create_index([("client_id", 1), ("ip_address", 1)])
        await db.devices.create_index([("id", 1)], unique=True)

        # lldp_neighbors: il codice topology.py usa "local_ip" non "local_device_ip"
        await db.lldp_neighbors.create_index([("local_ip", 1)])

        # auto_dispatch_history: TTL 30gg + lookup
        await db.auto_dispatch_history.create_index("timestamp", expireAfterSeconds=86400 * 30)

        # v3.6.21: device_port_history per movement anomaly detection
        await db.device_port_history.create_index([("client_id", 1), ("mac", 1)], unique=True)
        await db.device_port_history.create_index([("client_id", 1), ("last_seen", -1)])
        await db.alerts.create_index([("client_id", 1), ("kind", 1), ("mac", 1), ("status", 1)])

        logger.info("MongoDB indexes created/verified successfully")

    except Exception as e:
        logger.warning(f"Index creation warning (non-fatal): {e}")

    # === AUTO-SEED: Create default admin users if they don't exist ===
    try:
        from security import security_manager
        import uuid as _uuid

        seed_users = [
            {"email": "admin@86bit.it", "name": "Admin", "role": "admin", "password": "password"},
            {"email": "info@86bit.it", "name": "Marco Santinelli", "role": "admin", "password": "password"},
            {"email": "tv@86bit.it", "name": "TV Monitor", "role": "viewer", "password": "Tv86bit!2026"},
            {"email": "tvdash@86bit.it", "name": "TV Dashboard Test", "role": "viewer", "password": "Tv86bit!2026"},
        ]
        for su in seed_users:
            existing = await db.users.find_one({"email": su["email"]})
            if not existing:
                from datetime import datetime as _dt, timezone as _tz
                user_doc = {
                    "id": str(_uuid.uuid4()),
                    "email": su["email"],
                    "name": su["name"],
                    "password_hash": security_manager.hash_password(su["password"]),
                    "role": su["role"],
                    "two_factor_enabled": False,
                    "totp_secret": None,
                    "is_active": True,
                    "created_at": _dt.now(_tz.utc).isoformat(),
                }
                await db.users.insert_one(user_doc)
                logger.info(f"Seed user created: {su['email']} ({su['role']})")
    except Exception as e:
        logger.warning(f"Seed users warning (non-fatal): {e}")

    # === UNBAN whitelisted IPs (legacy cleanup) ===
    try:
        await db.banned_ips.drop()
        await db.honeypot_bans.drop()
        await db.blocked_ips.drop()
        logger.info("IP ban collections removed (feature disabled)")
    except Exception:
        pass

    # === Connector security: nonce TTL index ===
    try:
        from middleware.connector_security import setup_nonce_ttl_index
        await setup_nonce_ttl_index()
        logger.info("Connector nonce TTL index created")
    except Exception as e:
        logger.warning(f"Nonce TTL index warning: {e}")

    try:
        setting = await db.settings.find_one({"key": "redfish_poll_interval"})
        # Default 1 minuto (era 5 min originale, 10 in DB). Per real-time stats
        # forziamo cap max a 5min: valori >= 5 vengono normalizzati a 1 per default.
        current = setting.get("value", 1) if setting else 1
        try:
            current = int(current)
        except Exception:
            current = 1
        if current < 1 or current > 5:
            # Migrazione: valori stale (es. 10min) -> forziamo 1min real-time
            await db.settings.update_one(
                {"key": "redfish_poll_interval"},
                {"$set": {"key": "redfish_poll_interval", "value": 1, "migrated_at": datetime.utcnow().isoformat()}},
                upsert=True
            )
            current = 1
            logger.info("Redfish poll interval migrated to 1min (real-time stats)")
        interval = current
        await redfish_poller.start_scheduler(interval_minutes=interval)
        logger.info(f"Redfish polling scheduler started (interval: {interval} min)")
    except Exception as e:
        logger.error(f"Failed to start Redfish scheduler: {e}")

    # === Connector watchdog: alert when connectors stop heartbeating ===
    try:
        from connector_watchdog import ConnectorWatchdog
        from deps import notification_service
        global connector_watchdog
        connector_watchdog = ConnectorWatchdog(db, notification_service=notification_service)
        await connector_watchdog.start(interval_seconds=60)
        logger.info("Connector watchdog started")
    except Exception as e:
        logger.error(f"Failed to start connector watchdog: {e}")

    # === Escalation scheduler: re-push alerts not ACKed within N min ===
    try:
        from escalation import EscalationScheduler
        global escalation_scheduler
        escalation_scheduler = EscalationScheduler(db)
        escalation_scheduler.start()
        logger.info("Escalation scheduler started")
    except Exception as e:
        logger.error(f"Failed to start escalation scheduler: {e}")

    # === Connectivity correlation scheduler (LAN/WiFi inference per device) ===
    # v3.8.23: chiama periodicamente correlate_connectivity per ogni cliente,
    # popolando connection_type su tutti i managed_devices senza richiedere
    # il click manuale dall'utente. Usa CAM table + LLDP + euristica device_type.
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.interval import IntervalTrigger

        async def _correlate_connectivity_tick():
            try:
                # Importa lazy per evitare cicli
                from routes.devices import correlate_connectivity
                clients = await db.clients.find({}, {"_id": 0, "id": 1}).to_list(500)
                fake_user = {"id": "system-scheduler", "email": "scheduler@argus", "role": "admin", "_request_ip": "127.0.0.1"}
                ok = 0
                for c in clients:
                    cid = c.get("id")
                    if not cid:
                        continue
                    try:
                        await correlate_connectivity(client_id=cid, current_user=fake_user)
                        ok += 1
                    except Exception as ce:
                        logger.warning(f"correlate_connectivity client_id={cid} failed: {ce}")
                logger.info(f"[connectivity-scheduler] correlated {ok}/{len(clients)} clients")
            except Exception as e:
                logger.error(f"connectivity scheduler tick failed: {e}")

        global connectivity_scheduler
        connectivity_scheduler = AsyncIOScheduler()
        connectivity_scheduler.add_job(
            _correlate_connectivity_tick,
            trigger=IntervalTrigger(minutes=10),
            id="correlate_connectivity_tick",
            next_run_time=datetime.now(timezone.utc) + timedelta(minutes=2),  # First run 2 min after startup
            max_instances=1,
            coalesce=True,
        )
        connectivity_scheduler.start()
        logger.info("Connectivity correlation scheduler started (tick: 10min)")
    except Exception as e:
        logger.error(f"Failed to start connectivity scheduler: {e}")

    # === Auto-Dispatch cron (hardware risk + predictive failure → incident) ===
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.interval import IntervalTrigger
        from routes.auto_dispatch import run_auto_dispatch
        global auto_dispatch_scheduler
        auto_dispatch_scheduler = AsyncIOScheduler()
        auto_dispatch_scheduler.add_job(
            run_auto_dispatch,
            trigger=IntervalTrigger(hours=6),
            id="auto_dispatch_scan",
            next_run_time=datetime.now(timezone.utc) + timedelta(minutes=10),  # First run 10 min after startup
        )
        auto_dispatch_scheduler.start()
        logger.info("Auto-dispatch scheduler started (interval: 6h)")
    except Exception as e:
        logger.error(f"Failed to start auto-dispatch scheduler: {e}")

    # === Hornetsecurity 365 Total Backup polling scheduler ===
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.interval import IntervalTrigger
        from services.hornetsecurity_poller import hornetsecurity_polling_tick
        global hornetsecurity_scheduler
        hornetsecurity_scheduler = AsyncIOScheduler()
        hornetsecurity_scheduler.add_job(
            hornetsecurity_polling_tick,
            trigger=IntervalTrigger(minutes=1),
            id="hornetsecurity_polling_tick",
            next_run_time=datetime.now(timezone.utc) + timedelta(seconds=30),
            max_instances=1,
            coalesce=True,
        )
        hornetsecurity_scheduler.start()
        logger.info("Hornetsecurity 365 backup polling scheduler started (tick: 1min)")
    except Exception as e:
        logger.error(f"Failed to start Hornetsecurity scheduler: {e}")

    # === Hornetsecurity VM Backup (Altaro) polling scheduler ===
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler as _VMSched
        from apscheduler.triggers.interval import IntervalTrigger as _VMTrig
        from services.hornetsecurity_vmbackup_poller import vmbackup_polling_tick
        global hornetsecurity_vm_scheduler
        hornetsecurity_vm_scheduler = _VMSched()
        hornetsecurity_vm_scheduler.add_job(
            vmbackup_polling_tick,
            trigger=_VMTrig(minutes=1),
            id="hornetsecurity_vmbackup_polling_tick",
            next_run_time=datetime.now(timezone.utc) + timedelta(seconds=45),
            max_instances=1,
            coalesce=True,
        )
        hornetsecurity_vm_scheduler.start()
        logger.info("Hornetsecurity VM backup polling scheduler started (tick: 1min)")
    except Exception as e:
        logger.error(f"Failed to start Hornetsecurity VM backup scheduler: {e}")

    # === Datto RMM auto-sync scheduler (v3.6.20) ===
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler as _DattoSched
        from apscheduler.triggers.interval import IntervalTrigger as _DattoTrig
        from routes.datto_rmm import _refresh_sites_cache as _datto_tick

        async def _datto_tick_safe():
            """Ignora gracefully se la config non e' settata (no auth/nessun setup)."""
            try:
                cfg = await db.datto_settings.find_one({"id": "global"}, {"_id": 0, "id": 1})
                if not cfg:
                    return  # Datto non configurato, skip silenzioso
                result = await _datto_tick()
                logger.info(f"[datto-auto-sync] {result}")
            except Exception as ex:
                logger.warning(f"[datto-auto-sync] failed: {ex}")

        global datto_scheduler
        datto_scheduler = _DattoSched()
        datto_scheduler.add_job(
            _datto_tick_safe,
            trigger=_DattoTrig(hours=6),
            id="datto_rmm_auto_sync",
            next_run_time=datetime.now(timezone.utc) + timedelta(minutes=2),
            max_instances=1,
            coalesce=True,
        )
        datto_scheduler.start()
        logger.info("Datto RMM auto-sync scheduler started (tick: 6h)")
    except Exception as e:
        logger.error(f"Failed to start Datto RMM scheduler: {e}")

    # ----- Embedded WireGuard runtime (POC, opt-in via env WG_EMBEDDED_ENABLED) -----
    if os.environ.get("WG_EMBEDDED_ENABLED", "").lower() in ("1", "true", "yes"):
        try:
            from wireguard_embedded import wg_manager
            await wg_manager.start()
            st = wg_manager.status()
            if st.get("running"):
                logger.info(
                    f"WG embedded runtime started: pid={st['pid']} iface={st['interface']} "
                    f"port={st['listen_port']}"
                )
            else:
                logger.warning(
                    f"WG embedded runtime NOT started (host requirements unmet): "
                    f"{st.get('last_error') or st['environment'].get('missing_prerequisites')}"
                )
        except Exception as e:
            logger.error(f"WG embedded runtime startup error: {e}")
    else:
        logger.info("WG embedded runtime disabled (set WG_EMBEDDED_ENABLED=true to opt-in)")

@app.on_event("shutdown")
async def shutdown_db_client():
    redfish_poller.stop_scheduler()
    try:
        if 'connector_watchdog' in globals() and connector_watchdog:
            connector_watchdog.stop()
    except Exception:
        pass
    try:
        if 'escalation_scheduler' in globals() and escalation_scheduler:
            await escalation_scheduler.stop()
    except Exception:
        pass
    # Stop embedded WG runtime if running
    try:
        from wireguard_embedded import wg_manager
        if wg_manager.process is not None:
            await wg_manager.stop()
    except Exception:
        pass
    mongo_client.close()
