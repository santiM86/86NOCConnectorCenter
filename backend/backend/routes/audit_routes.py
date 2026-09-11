"""Audit logs, security dashboard, and IP blocking routes."""
from fastapi import APIRouter, Depends, HTTPException, Request
from datetime import datetime, timezone, timedelta

from database import db
from audit import AuditAction
from deps import (
    get_current_user, audit_logger, check_nosql_injection, sanitize_string,
    get_ip_block_config, _blocked_ips_cache, _ip_block_config_cache
)

router = APIRouter(prefix="/api", tags=["audit"])


@router.get("/audit/logs")
async def get_audit_logs(hours: int = 24, limit: int = 100, current_user: dict = Depends(get_current_user)):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    logs = await db.audit_logs.find({"timestamp": {"$gte": cutoff}}, {"_id": 0}).sort("timestamp", -1).to_list(limit)
    return logs


@router.get("/audit/security-events")
async def get_security_events(hours: int = 24, current_user: dict = Depends(get_current_user)):
    events = await audit_logger.get_security_events(hours=hours)
    return events


@router.get("/audit/security-dashboard")
async def get_security_dashboard(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["admin", "security_admin"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    now = datetime.now(timezone.utc)
    cutoff_24h = (now - timedelta(hours=24)).isoformat()
    cutoff_7d = (now - timedelta(days=7)).isoformat()
    failed_logins_24h = await db.audit_logs.find(
        {"action": "login_failed", "timestamp": {"$gte": cutoff_24h}}, {"_id": 0}
    ).sort("timestamp", -1).to_list(100)
    success_logins_24h = await db.audit_logs.count_documents(
        {"action": "login_success", "timestamp": {"$gte": cutoff_24h}}
    )
    locked_accounts = await db.users.find(
        {"locked": True}, {"_id": 0, "email": 1, "locked_at": 1, "unlock_at": 1}
    ).to_list(50)
    active_tokens = await db.refresh_tokens.count_documents({"revoked": False})
    revoked_tokens_24h = await db.refresh_tokens.count_documents(
        {"revoked": True, "created_at": {"$gte": cutoff_24h}}
    )
    ip_stats = {}
    for log in failed_logins_24h:
        ip = log.get("ip_address", "unknown")
        if ip not in ip_stats:
            ip_stats[ip] = {"count": 0, "last_attempt": "", "emails": set()}
        ip_stats[ip]["count"] += 1
        ip_stats[ip]["last_attempt"] = log.get("timestamp", "")
        if log.get("user_email"):
            ip_stats[ip]["emails"].add(log["user_email"])
    suspicious_ips = [
        {"ip": ip, "attempts": data["count"], "last_attempt": data["last_attempt"], "targeted_emails": list(data["emails"])}
        for ip, data in sorted(ip_stats.items(), key=lambda x: x[1]["count"], reverse=True)
    ][:20]
    security_actions = ["login_failed", "login_success", "logout", "2fa_verified", "2fa_failed", "rate_limit_exceeded", "suspicious_activity", "ip_blocked"]
    timeline_logs = await db.audit_logs.find(
        {"action": {"$in": security_actions}, "timestamp": {"$gte": cutoff_7d}},
        {"_id": 0, "timestamp": 1, "action": 1, "severity": 1}
    ).sort("timestamp", -1).to_list(5000)
    daily_counts = {}
    for log in timeline_logs:
        day = log["timestamp"][:10]
        if day not in daily_counts:
            daily_counts[day] = {"date": day, "failed": 0, "success": 0, "total": 0}
        daily_counts[day]["total"] += 1
        if log["action"] == "login_failed": daily_counts[day]["failed"] += 1
        elif log["action"] == "login_success": daily_counts[day]["success"] += 1
    timeline = sorted(daily_counts.values(), key=lambda x: x["date"])
    critical_events = await db.audit_logs.find(
        {"severity": {"$in": ["critical", "warning"]}, "timestamp": {"$gte": cutoff_24h}}, {"_id": 0}
    ).sort("timestamp", -1).to_list(50)
    twofa_enabled = await db.users.count_documents({"two_factor_enabled": True})
    twofa_total = await db.users.count_documents({})
    now_iso_check = datetime.now(timezone.utc).isoformat()
    blocked_ips_count = await db.blocked_ips.count_documents(
        {"unblocked": {"$ne": True}, "$or": [{"expires_at": {"$gt": now_iso_check}}, {"permanent": True}]}
    )
    return {
        "stats": {
            "failed_logins_24h": len(failed_logins_24h),
            "success_logins_24h": success_logins_24h,
            "locked_accounts": len(locked_accounts),
            "active_sessions": active_tokens,
            "revoked_tokens_24h": revoked_tokens_24h,
            "critical_events_24h": len([e for e in critical_events if e.get("severity") == "critical"]),
            "twofa_coverage": f"{twofa_enabled}/{twofa_total}",
            "blocked_ips": blocked_ips_count,
        },
        "failed_logins": failed_logins_24h[:30],
        "locked_accounts": locked_accounts,
        "suspicious_ips": suspicious_ips,
        "timeline": timeline,
        "critical_events": critical_events[:30],
    }


# ==================== IP BLOCKING MANAGEMENT ====================

@router.get("/security/blocked-ips")
async def get_blocked_ips(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["admin", "security_admin"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    now_iso = datetime.now(timezone.utc).isoformat()
    blocked = await db.blocked_ips.find(
        {"unblocked": {"$ne": True}, "$or": [{"expires_at": {"$gt": now_iso}}, {"permanent": True}]}, {"_id": 0}
    ).sort("blocked_at", -1).to_list(200)
    history = await db.blocked_ips.find(
        {"$or": [{"unblocked": True}, {"expires_at": {"$lte": now_iso}, "permanent": {"$ne": True}}]}, {"_id": 0}
    ).sort("blocked_at", -1).to_list(50)
    return {"active": blocked, "history": history}


@router.post("/security/block-ip")
async def block_ip(request: Request, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["admin", "security_admin"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    body = await request.json()
    check_nosql_injection(body)
    ip = sanitize_string(body.get("ip", ""), 45)
    reason = sanitize_string(body.get("reason", "Blocco manuale"), 500)
    duration_hours = body.get("duration_hours", 6)
    permanent = body.get("permanent", False)
    if not ip:
        raise HTTPException(status_code=400, detail="IP address required")
    whitelist_setting = await db.settings.find_one({"key": "ip_whitelist"}, {"_id": 0})
    whitelist = whitelist_setting.get("value", []) if whitelist_setting else []
    if ip in whitelist:
        raise HTTPException(status_code=400, detail="IP is in whitelist and cannot be blocked")
    expires_at = None if permanent else (datetime.now(timezone.utc) + timedelta(hours=duration_hours)).isoformat()
    await db.blocked_ips.update_one(
        {"ip": ip, "unblocked": {"$ne": True}},
        {"$set": {
            "ip": ip, "reason": reason,
            "blocked_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": expires_at, "permanent": permanent,
            "unblocked": False, "blocked_by": current_user.get("email", "admin")
        }},
        upsert=True
    )
    _blocked_ips_cache["ips"].add(ip)
    await audit_logger.log(
        AuditAction.IP_BLOCKED, user_id=current_user.get("id"), user_email=current_user.get("email"),
        ip_address=ip, details={"reason": reason, "permanent": permanent, "duration_hours": duration_hours},
        severity="critical"
    )
    return {"status": "ok", "message": f"IP {ip} bloccato"}


@router.post("/security/unblock-ip")
async def unblock_ip(request: Request, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["admin", "security_admin"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    body = await request.json()
    ip = body.get("ip", "")
    if not ip:
        raise HTTPException(status_code=400, detail="IP address required")
    result = await db.blocked_ips.update_many(
        {"ip": ip, "unblocked": {"$ne": True}},
        {"$set": {"unblocked": True, "unblocked_at": datetime.now(timezone.utc).isoformat(), "unblocked_by": current_user.get("email", "admin")}}
    )
    _blocked_ips_cache["ips"].discard(ip)
    await audit_logger.log(
        AuditAction.IP_BLOCKED, user_id=current_user.get("id"), user_email=current_user.get("email"),
        ip_address=ip, details={"action": "unblock"}, severity="info"
    )
    return {"status": "ok", "message": f"IP {ip} sbloccato", "modified": result.modified_count}


@router.get("/security/ip-block-config")
async def get_ip_block_config_endpoint(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["admin", "security_admin"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    config = await get_ip_block_config()
    whitelist_setting = await db.settings.find_one({"key": "ip_whitelist"}, {"_id": 0})
    whitelist = whitelist_setting.get("value", []) if whitelist_setting else []
    return {**config, "whitelist": whitelist}


@router.post("/security/ip-block-config")
async def update_ip_block_config(request: Request, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["admin", "security_admin"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    body = await request.json()
    check_nosql_injection(body)
    config = {
        "enabled": body.get("enabled", True),
        "max_attempts": max(1, min(100, int(body.get("max_attempts", 10)))),
        "window_minutes": max(1, min(1440, int(body.get("window_minutes", 30)))),
        "block_duration_hours": max(1, min(8760, int(body.get("block_duration_hours", 6)))),
        "auto_ban_enabled": body.get("auto_ban_enabled", True),
    }
    await db.settings.update_one({"key": "ip_block_config"}, {"$set": {"key": "ip_block_config", "value": config}}, upsert=True)
    if "whitelist" in body:
        whitelist = [sanitize_string(ip.strip(), 45) for ip in body["whitelist"] if ip.strip()]
        await db.settings.update_one({"key": "ip_whitelist"}, {"$set": {"key": "ip_whitelist", "value": whitelist}}, upsert=True)
        _blocked_ips_cache["whitelist"] = set(whitelist)
    _ip_block_config_cache["config"] = None
    _ip_block_config_cache["last_refresh"] = None
    await audit_logger.log(
        AuditAction.SUSPICIOUS_ACTIVITY, user_id=current_user.get("id"), user_email=current_user.get("email"),
        details={"action": "ip_block_config_updated", "config": config}, severity="info"
    )
    return {"status": "ok", "config": config}
