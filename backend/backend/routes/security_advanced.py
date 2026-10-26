"""
Security Advanced Routes - Gestione avanzata sicurezza:
- IP Whitelist Admin UI
- Session Management (invalidazione remota)
- Password Policy config e enforcement
- API Key Rotation
- SIEM Log Export (JSON/CSV)
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
from typing import List, Optional
import io
import csv
import secrets

from database import db
from deps import get_current_user, require_admin, audit_logger, check_nosql_injection, sanitize_string
from audit import AuditAction
from security_hardening import SecurityHardening, PasswordPolicy
from middleware.session_cache import session_cache

router = APIRouter(prefix="/api/security", tags=["security-advanced"])

security_hardening = SecurityHardening(db)


# ==================== IP WHITELIST ADMIN ====================

class IPWhitelistPayload(BaseModel):
    ips: List[str]
    enabled: bool = True


@router.get("/ip-whitelist")
async def get_ip_whitelist(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    whitelist = await security_hardening.get_ip_whitelist()
    enabled = await security_hardening.is_ip_whitelist_enabled()
    return {"ips": whitelist, "enabled": enabled}


@router.post("/ip-whitelist")
async def update_ip_whitelist(request: Request, payload: IPWhitelistPayload, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    await security_hardening.set_ip_whitelist(payload.ips)
    await security_hardening.set_ip_whitelist_enabled(payload.enabled)
    await audit_logger.log(
        AuditAction.SUSPICIOUS_ACTIVITY,
        user_id=current_user["id"], user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        details={"action": "ip_whitelist_updated", "count": len(payload.ips), "enabled": payload.enabled},
        severity="info",
    )
    return {"status": "ok", "ips": payload.ips, "enabled": payload.enabled}


# ==================== SESSION MANAGEMENT ====================

@router.get("/sessions")
async def get_all_sessions(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    sessions = await db.sessions.find({"active": True}, {"_id": 0}).sort("last_activity", -1).to_list(200)
    # Enrich with user info
    user_ids = list({s["user_id"] for s in sessions})
    users = {}
    if user_ids:
        for u in await db.users.find({"id": {"$in": user_ids}}, {"_id": 0, "id": 1, "email": 1, "name": 1}).to_list(200):
            users[u["id"]] = u
    for s in sessions:
        u = users.get(s.get("user_id"), {})
        s["user_email"] = u.get("email", "?")
        s["user_name"] = u.get("name", "?")
    # Also add in-memory session cache stats
    cache_stats = session_cache.get_stats()
    return {"sessions": sessions, "cache_stats": cache_stats}


@router.delete("/sessions/{session_id}")
async def kill_session(session_id: str, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    await security_hardening.invalidate_session(session_id)
    session_cache.invalidate(session_id)
    await audit_logger.log(
        AuditAction.SUSPICIOUS_ACTIVITY,
        user_id=current_user["id"], user_email=current_user["email"],
        details={"action": "session_killed", "session_id": session_id},
        severity="warning",
    )
    return {"status": "ok", "message": "Sessione terminata"}


@router.delete("/sessions/user/{user_id}")
async def kill_all_user_sessions(user_id: str, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    await security_hardening.invalidate_all_sessions(user_id)
    killed = session_cache.invalidate_user(user_id)
    await db.refresh_tokens.update_many({"user_id": user_id, "revoked": False}, {"$set": {"revoked": True}})
    target_user = await db.users.find_one({"id": user_id}, {"_id": 0, "email": 1})
    await audit_logger.log(
        AuditAction.SUSPICIOUS_ACTIVITY,
        user_id=current_user["id"], user_email=current_user["email"],
        details={
            "action": "all_sessions_killed",
            "target_user_id": user_id,
            "target_email": target_user.get("email") if target_user else "?",
            "cache_sessions_killed": killed,
        },
        severity="critical",
    )
    return {"status": "ok", "message": "Tutte le sessioni dell'utente terminate"}


# ==================== PASSWORD POLICY ====================

@router.get("/password-policy")
async def get_password_policy(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    policy = await security_hardening.get_password_policy()
    return policy.model_dump()


@router.put("/password-policy")
async def update_password_policy(request: Request, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    body = await request.json()
    check_nosql_injection(body)
    policy = PasswordPolicy(
        min_length=max(8, min(128, int(body.get("min_length", 12)))),
        require_uppercase=body.get("require_uppercase", True),
        require_lowercase=body.get("require_lowercase", True),
        require_digit=body.get("require_digit", True),
        require_special=body.get("require_special", True),
        max_age_days=max(1, min(365, int(body.get("max_age_days", 90)))),
        password_history=max(0, min(20, int(body.get("password_history", 5)))),
        lockout_attempts=max(3, min(50, int(body.get("lockout_attempts", 10)))),
        lockout_duration_minutes=max(1, min(1440, int(body.get("lockout_duration_minutes", 5)))),
    )
    await security_hardening.set_password_policy(policy)
    await audit_logger.log(
        AuditAction.SUSPICIOUS_ACTIVITY,
        user_id=current_user["id"], user_email=current_user["email"],
        details={"action": "password_policy_updated", "policy": policy.model_dump()},
        severity="info",
    )
    return {"status": "ok", "policy": policy.model_dump()}


# ==================== API KEY ROTATION ====================

@router.get("/api-keys")
async def get_api_keys(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    clients = await db.clients.find(
        {"api_key": {"$exists": True}},
        {"_id": 0, "id": 1, "name": 1, "api_key": 1, "api_key_created_at": 1, "api_key_expires_at": 1}
    ).to_list(200)
    now = datetime.now(timezone.utc).isoformat()
    for c in clients:
        c["api_key_masked"] = c.get("api_key", "")[:8] + "..." if c.get("api_key") else None
        c.pop("api_key", None)
        expires = c.get("api_key_expires_at")
        c["expired"] = expires is not None and expires < now
    return {"api_keys": clients}


@router.post("/rotate-api-key/{client_id}")
async def rotate_api_key(client_id: str, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    client = await db.clients.find_one({"id": client_id}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client non trovato")
    new_key = f"noc_{secrets.token_hex(24)}"
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(days=90)).isoformat()
    await db.clients.update_one(
        {"id": client_id},
        {"$set": {
            "api_key": new_key,
            "api_key_created_at": now.isoformat(),
            "api_key_expires_at": expires_at,
            "api_key_previous": client.get("api_key"),
        }}
    )
    await audit_logger.log(
        AuditAction.API_KEY_GENERATED,
        user_id=current_user["id"], user_email=current_user["email"],
        resource_type="client", resource_id=client_id,
        details={"action": "api_key_rotated", "expires_at": expires_at},
        severity="warning",
    )
    return {"status": "ok", "new_key": new_key, "expires_at": expires_at}


# ==================== SIEM LOG EXPORT ====================

@router.get("/export/audit-logs")
async def export_audit_logs(
    format: str = "json",
    days: int = 30,
    current_user: dict = Depends(get_current_user),
):
    require_admin(current_user)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=min(days, 365))).isoformat()
    logs = await db.audit_logs.find(
        {"timestamp": {"$gte": cutoff}},
        {"_id": 0}
    ).sort("timestamp", -1).to_list(50000)

    await audit_logger.log(
        AuditAction.VIEW_ALERTS,
        user_id=current_user["id"], user_email=current_user["email"],
        details={"action": "siem_export", "format": format, "days": days, "count": len(logs)},
    )

    if format == "csv":
        output = io.StringIO()
        if logs:
            fields = ["timestamp", "action", "user_email", "ip_address", "severity", "success", "details"]
            writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for log in logs:
                log["details"] = str(log.get("details", ""))
                writer.writerow(log)
        content = output.getvalue().encode("utf-8")
        return StreamingResponse(
            io.BytesIO(content),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=audit_logs_{datetime.now().strftime('%Y%m%d')}.csv"}
        )
    else:
        import json
        content = json.dumps(logs, ensure_ascii=False, indent=2).encode("utf-8")
        return StreamingResponse(
            io.BytesIO(content),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=audit_logs_{datetime.now().strftime('%Y%m%d')}.json"}
        )


# ==================== LOGIN SOSPETTI - Known IPs ====================

@router.get("/known-ips/{user_id}")
async def get_user_known_ips(user_id: str, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    user = await db.users.find_one({"id": user_id}, {"_id": 0, "id": 1, "email": 1, "known_ips": 1})
    if not user:
        raise HTTPException(status_code=404, detail="Utente non trovato")
    return {"user_id": user_id, "email": user.get("email"), "known_ips": user.get("known_ips", [])}


@router.get("/suspicious-logins")
async def get_suspicious_logins(hours: int = 72, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    events = await db.audit_logs.find(
        {
            "action": "login_success",
            "timestamp": {"$gte": cutoff},
            "details.new_ip_detected": True,
        },
        {"_id": 0}
    ).sort("timestamp", -1).to_list(100)
    return {"suspicious_logins": events, "period_hours": hours}
