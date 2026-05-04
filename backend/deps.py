"""Shared dependencies for all route modules."""
import os
import re
import secrets
import jwt
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List

from fastapi import HTTPException, Depends, Request, WebSocket
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from slowapi import Limiter
from slowapi.util import get_remote_address

from database import db
from security import security_manager
from audit import AuditLogger, AuditAction
from notifications import NotificationService, NotificationChannel, NotificationPriority
from redfish import RedfishPoller
from correlation import AlertCorrelationManager
from maintenance import MaintenanceManager
from sla import SLAManager
from security_hardening import SecurityHardening

logger = logging.getLogger(__name__)

# JWT Config
JWT_SECRET = os.environ.get('JWT_SECRET', 'noc-alert-command-center-secret-key-2024')
JWT_ALGORITHM = "HS256"

# Rate Limiter
limiter = Limiter(key_func=get_remote_address)

# Security bearer
security = HTTPBearer()

# Initialize services
audit_logger = AuditLogger(db)
notification_service = NotificationService(db)
redfish_poller = RedfishPoller(db, notification_service)
redfish_poller.set_security_manager(security_manager)
correlation_manager = AlertCorrelationManager(db)
maintenance_manager = MaintenanceManager(db)
sla_manager = SLAManager(db, notification_service)
security_hardening = SecurityHardening(db)

# Connector storage path
CONNECTOR_STORAGE = Path(__file__).parent / "connector_updates"
CONNECTOR_STORAGE.mkdir(exist_ok=True)

# Refresh token config
REFRESH_TOKEN_EXPIRY_DAYS = 30


# ==================== WEBSOCKET MANAGER ====================

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()


# ==================== INPUT SANITIZATION ====================

NOSQL_INJECTION_PATTERNS = [
    re.compile(r'\$(?:gt|gte|lt|lte|ne|in|nin|and|or|not|nor|exists|type|regex|where|all|elemMatch|size|slice)\b', re.IGNORECASE),
    re.compile(r'\{.*\$.*\}'),
]

def sanitize_string(value: str, max_length: int = 10000) -> str:
    if not isinstance(value, str):
        return value
    value = value[:max_length]
    value = value.replace('\x00', '')
    return value

def check_nosql_injection(data, path=""):
    if isinstance(data, dict):
        for key, val in data.items():
            if isinstance(key, str) and key.startswith('$'):
                raise HTTPException(status_code=400, detail="Invalid input: operator keys not allowed")
            check_nosql_injection(val, f"{path}.{key}")
    elif isinstance(data, list):
        for item in data:
            check_nosql_injection(item, path)
    elif isinstance(data, str):
        for pattern in NOSQL_INJECTION_PATTERNS:
            if pattern.search(data):
                raise HTTPException(status_code=400, detail="Invalid input: suspicious pattern detected")


# ==================== VERSION COMPARISON ====================

def parse_version(version_str: str):
    try:
        parts = version_str.strip().lstrip("v").split(".")
        return tuple(int(p) for p in parts)
    except:
        return (0, 0, 0)

def is_newer_version(published: str, current: str) -> bool:
    return parse_version(published) > parse_version(current)


# ==================== AUTH HELPERS ====================

def create_token(user_id: str, email: str, requires_2fa: bool = False) -> str:
    payload = {
        "user_id": user_id,
        "email": email,
        "requires_2fa": requires_2fa,
        "exp": datetime.now(timezone.utc).timestamp() + 86400
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("requires_2fa"):
            raise HTTPException(status_code=403, detail="2FA verification required")
        user = await db.users.find_one({"id": payload["user_id"]}, {"_id": 0, "password_hash": 0, "totp_secret": 0})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        user["_request_ip"] = request.client.host if request.client else "unknown"
        user["_user_agent"] = request.headers.get("user-agent", "unknown")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def validate_api_key(request: Request) -> dict:
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        raise HTTPException(status_code=401, detail="X-API-Key header required")
    client = await db.clients.find_one({"api_key": api_key}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return client

def require_admin(current_user: dict):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Accesso riservato agli amministratori")


# ==================== REFRESH TOKEN ====================

def create_refresh_token(user_id: str) -> str:
    return secrets.token_urlsafe(48)

async def store_refresh_token(user_id: str, token: str, ip: str = "unknown"):
    doc = {
        "user_id": user_id,
        "token": token,
        "ip_address": ip,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRY_DAYS)).isoformat(),
        "revoked": False
    }
    await db.refresh_tokens.insert_one(doc)
    await db.refresh_tokens.delete_many({
        "expires_at": {"$lt": datetime.now(timezone.utc).isoformat()}
    })


# ==================== IP BLOCKING SYSTEM ====================

_blocked_ips_cache = {"ips": set(), "whitelist": set(), "last_refresh": None}
_ip_block_config_cache = {"config": None, "last_refresh": None}

async def get_ip_block_config():
    now = datetime.now(timezone.utc)
    if _ip_block_config_cache["config"] and _ip_block_config_cache["last_refresh"]:
        elapsed = (now - _ip_block_config_cache["last_refresh"]).total_seconds()
        if elapsed < 60:
            return _ip_block_config_cache["config"]
    setting = await db.settings.find_one({"key": "ip_block_config"}, {"_id": 0})
    config = setting.get("value", {}) if setting else {}
    defaults = {
        "enabled": True,
        "max_attempts": 10,
        "window_minutes": 30,
        "block_duration_hours": 6,
        "auto_ban_enabled": True,
    }
    merged = {**defaults, **config}
    _ip_block_config_cache["config"] = merged
    _ip_block_config_cache["last_refresh"] = now
    return merged

async def refresh_blocked_ips_cache():
    now_iso = datetime.now(timezone.utc).isoformat()
    blocked = await db.blocked_ips.find(
        {"unblocked": {"$ne": True}, "$or": [{"expires_at": {"$gt": now_iso}}, {"permanent": True}]},
        {"_id": 0, "ip": 1}
    ).to_list(10000)
    _blocked_ips_cache["ips"] = {b["ip"] for b in blocked}
    setting = await db.settings.find_one({"key": "ip_whitelist"}, {"_id": 0})
    _blocked_ips_cache["whitelist"] = set(setting.get("value", [])) if setting else set()
    _blocked_ips_cache["last_refresh"] = datetime.now(timezone.utc)

async def is_ip_blocked(ip: str) -> bool:
    if not ip:
        return False
    now = datetime.now(timezone.utc)
    if not _blocked_ips_cache["last_refresh"] or (now - _blocked_ips_cache["last_refresh"]).total_seconds() > 30:
        await refresh_blocked_ips_cache()
    if ip in _blocked_ips_cache["whitelist"]:
        return False
    return ip in _blocked_ips_cache["ips"]

async def auto_ban_check(ip: str):
    config = await get_ip_block_config()
    if not config.get("auto_ban_enabled") or not config.get("enabled"):
        return
    if ip in _blocked_ips_cache.get("whitelist", set()):
        return
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=config["window_minutes"])).isoformat()
    failed_count = await db.audit_logs.count_documents({
        "action": "login_failed",
        "ip_address": ip,
        "timestamp": {"$gte": cutoff}
    })
    if failed_count >= config["max_attempts"]:
        existing = await db.blocked_ips.find_one({"ip": ip, "unblocked": {"$ne": True}})
        if existing:
            return
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=config["block_duration_hours"])).isoformat()
        await db.blocked_ips.insert_one({
            "ip": ip,
            "reason": f"Auto-ban: {failed_count} tentativi falliti in {config['window_minutes']} min",
            "blocked_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": expires_at,
            "permanent": False,
            "unblocked": False,
            "blocked_by": "system"
        })
        _blocked_ips_cache["ips"].add(ip)
        await audit_logger.log(
            AuditAction.IP_BLOCKED,
            ip_address=ip,
            details={"reason": "auto_ban", "failed_attempts": failed_count, "duration_hours": config["block_duration_hours"]},
            severity="critical"
        )


# ==================== HELPER FUNCTIONS ====================

def map_syslog_severity(level: int) -> str:
    if level <= 2:
        return "critical"
    elif level <= 4:
        return "high"
    elif level <= 5:
        return "medium"
    return "low"

def map_snmp_severity(trap_type: str, oid: str) -> str:
    critical_oids = ["linkDown", "coldStart", "authenticationFailure"]
    if any(c in oid or c in trap_type for c in critical_oids):
        return "critical"
    elif "warning" in trap_type.lower() or "down" in oid.lower():
        return "high"
    return "medium"
