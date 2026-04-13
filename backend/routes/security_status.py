"""
Security Status API - Endpoint per la dashboard di sicurezza frontend.
Espone lo stato di tutte le 11 protezioni attive.
"""
from fastapi import APIRouter, Depends
from datetime import datetime, timezone, timedelta
from database import db
from deps import get_current_user, require_admin
from middleware.session_cache import session_cache
from middleware.global_rate_limiter import _global_limiter, GLOBAL_MAX_REQUESTS, WINDOW_SECONDS

router = APIRouter(prefix="/api/security", tags=["security-status"])


@router.get("/status")
async def get_security_status(current_user: dict = Depends(get_current_user)):
    """Restituisce lo stato di tutte le protezioni di sicurezza attive."""
    require_admin(current_user)

    # Conta tentativi login falliti nelle ultime 24h
    cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    failed_logins_24h = await db.audit_logs.count_documents({
        "action": "login_failed",
        "timestamp": {"$gte": cutoff_24h}
    })

    # Conta IP bloccati attivi
    now_iso = datetime.now(timezone.utc).isoformat()
    blocked_ips_count = await db.blocked_ips.count_documents({
        "unblocked": {"$ne": True},
        "$or": [{"expires_at": {"$gt": now_iso}}, {"permanent": True}]
    })

    # Conta account bloccati
    locked_accounts = await db.users.count_documents({"locked": True})

    # Conta utenti con 2FA abilitato
    users_with_2fa = await db.users.count_documents({"two_factor_enabled": True})
    total_users = await db.users.count_documents({})

    # Rate limit exceeded nelle ultime 24h
    rate_limit_events = await db.audit_logs.count_documents({
        "action": "rate_limit_exceeded",
        "timestamp": {"$gte": cutoff_24h}
    })

    # Ultimi 10 eventi di sicurezza
    recent_events = await db.audit_logs.find(
        {
            "action": {"$in": [
                "login_failed", "login_success", "ip_blocked",
                "rate_limit_exceeded", "2fa_verified", "2fa_failed"
            ]},
            "timestamp": {"$gte": cutoff_24h}
        },
        {"_id": 0}
    ).sort("timestamp", -1).to_list(10)

    # Conta audit logs totali
    total_audit_logs = await db.audit_logs.count_documents({})

    # Session cache stats
    session_stats = session_cache.get_stats()

    protections = [
        {
            "id": "brute_force",
            "name": "Brute Force Protection",
            "description": "Max 10 tentativi in 5 min per IP → 429 + audit log severity: critical",
            "status": "active",
            "details": {
                "failed_logins_24h": failed_logins_24h,
                "locked_accounts": locked_accounts,
            }
        },
        {
            "id": "rate_limiting",
            "name": "Rate Limiting Globale",
            "description": f"Sliding Window: max {GLOBAL_MAX_REQUESTS} req/min per IP ({GLOBAL_MAX_REQUESTS // WINDOW_SECONDS}/sec)",
            "status": "active",
            "details": {
                "max_requests_per_minute": GLOBAL_MAX_REQUESTS,
                "window_seconds": WINDOW_SECONDS,
                "rate_limit_events_24h": rate_limit_events,
            }
        },
        {
            "id": "two_factor",
            "name": "Autenticazione a Due Fattori (2FA/TOTP)",
            "description": "TOTP con Google Authenticator/Authy, valid_window=1 (30s tolleranza)",
            "status": "active",
            "details": {
                "users_with_2fa": users_with_2fa,
                "total_users": total_users,
                "coverage_pct": round(users_with_2fa / max(total_users, 1) * 100, 1),
            }
        },
        {
            "id": "password_security",
            "name": "Password Security",
            "description": "Argon2id hashing (3 iterazioni, 64MB memoria, parallelismo 4)",
            "status": "active",
            "details": {
                "algorithm": "Argon2id",
                "time_cost": 3,
                "memory_cost_mb": 64,
                "parallelism": 4,
            }
        },
        {
            "id": "session_management",
            "name": "Session Management",
            "description": "Token crittografici (secrets.token_hex), TTL 5 min, max 500 sessioni",
            "status": "active",
            "details": session_stats,
        },
        {
            "id": "encryption",
            "name": "Crittografia Dati Sensibili",
            "description": "AES-256-GCM per credenziali a riposo in MongoDB",
            "status": "active",
            "details": {
                "algorithm": "AES-256-GCM",
                "key_derivation": "PBKDF2-SHA256 (100k iterazioni)",
                "nonce_bits": 96,
            }
        },
        {
            "id": "security_headers",
            "name": "Security Headers",
            "description": "HSTS, X-Frame-Options, CSP, XSS Protection, Permissions-Policy",
            "status": "active",
            "details": {
                "headers": [
                    "X-Content-Type-Options: nosniff",
                    "X-Frame-Options: DENY",
                    "X-XSS-Protection: 1; mode=block",
                    "Strict-Transport-Security: max-age=31536000",
                    "Referrer-Policy: strict-origin-when-cross-origin",
                    "Permissions-Policy: camera=(), microphone=(), geolocation=()",
                    "Content-Security-Policy (whitelist)",
                    "X-Permitted-Cross-Domain-Policies: none",
                ]
            }
        },
        {
            "id": "cors",
            "name": "CORS Configurato",
            "description": "Origin specifico (mai wildcard *), preflight cache 600s",
            "status": "active",
            "details": {
                "credentials": True,
                "preflight_cache": 600,
            }
        },
        {
            "id": "request_timeout",
            "name": "Request Timeout",
            "description": "20s standard, 45s connector, 120s AI, 180s sync → 504",
            "status": "active",
            "details": {
                "standard": "20s",
                "connector": "45s",
                "ai_soc": "120s",
                "sync_discovery": "180s",
            }
        },
        {
            "id": "audit_logging",
            "name": "Audit Logging",
            "description": "Log in MongoDB con pulizia automatica >90 giorni",
            "status": "active",
            "details": {
                "total_logs": total_audit_logs,
                "retention_days": 90,
            }
        },
        {
            "id": "cache_control",
            "name": "Cache Control Headers",
            "description": "no-store su auth, private max-age=0 su tutti gli altri",
            "status": "active",
            "details": {
                "auth_endpoints": "no-store, no-cache",
                "other_endpoints": "private, max-age=0",
            }
        },
    ]

    return {
        "protections": protections,
        "summary": {
            "total_protections": len(protections),
            "all_active": all(p["status"] == "active" for p in protections),
            "blocked_ips": blocked_ips_count,
            "failed_logins_24h": failed_logins_24h,
            "users_with_2fa": users_with_2fa,
        },
        "recent_events": recent_events,
    }


@router.get("/audit-logs")
async def get_audit_logs(
    page: int = 1,
    limit: int = 50,
    severity: str = None,
    action: str = None,
    current_user: dict = Depends(get_current_user),
):
    """Ottiene gli audit log con paginazione e filtri."""
    require_admin(current_user)

    query = {}
    if severity:
        query["severity"] = severity
    if action:
        query["action"] = action

    skip = (page - 1) * limit
    total = await db.audit_logs.count_documents(query)
    logs = await db.audit_logs.find(query, {"_id": 0}).sort("timestamp", -1).skip(skip).limit(limit).to_list(limit)

    return {
        "logs": logs,
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit,
    }


@router.get("/blocked-ips")
async def get_blocked_ips(current_user: dict = Depends(get_current_user)):
    """Ottiene la lista degli IP attualmente bloccati."""
    require_admin(current_user)

    now_iso = datetime.now(timezone.utc).isoformat()
    blocked = await db.blocked_ips.find(
        {"unblocked": {"$ne": True}, "$or": [{"expires_at": {"$gt": now_iso}}, {"permanent": True}]},
        {"_id": 0}
    ).sort("blocked_at", -1).to_list(100)

    return {"blocked_ips": blocked}


@router.post("/unblock-ip/{ip}")
async def unblock_ip(ip: str, current_user: dict = Depends(get_current_user)):
    """Sblocca manualmente un IP."""
    require_admin(current_user)

    result = await db.blocked_ips.update_many(
        {"ip": ip, "unblocked": {"$ne": True}},
        {"$set": {"unblocked": True, "unblocked_at": datetime.now(timezone.utc).isoformat(), "unblocked_by": current_user["email"]}}
    )

    return {"unblocked": result.modified_count > 0, "ip": ip}
