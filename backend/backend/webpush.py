"""
Web Push (VAPID) service for NOC alerts.
Delivers real push notifications to subscribed browsers / installed PWAs.
"""
import os
import json
import logging
from datetime import datetime, time as dtime, timezone
from typing import Optional, Dict, List, Any

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

from pywebpush import webpush, WebPushException

logger = logging.getLogger("webpush")

VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:info@86bit.it")

VAPID_CLAIMS = {"sub": VAPID_SUBJECT}

DEFAULT_PREFS = {
    "quiet_hours_enabled": False,
    "quiet_start": "22:00",
    "quiet_end": "07:00",
    "quiet_timezone": "Europe/Rome",
    "quiet_exclude_critical": True,
}


def is_configured() -> bool:
    return bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY)


def _parse_hhmm(s: str) -> Optional[dtime]:
    try:
        h, m = s.split(":")
        return dtime(int(h), int(m))
    except Exception:
        return None


def is_in_quiet_hours(prefs: Dict[str, Any], severity: str, now: Optional[datetime] = None) -> bool:
    """Return True if notifications should be suppressed for this user right now."""
    if not prefs or not prefs.get("quiet_hours_enabled"):
        return False
    if prefs.get("quiet_exclude_critical", True) and (severity or "").lower() == "critical":
        return False

    start = _parse_hhmm(prefs.get("quiet_start", "22:00"))
    end = _parse_hhmm(prefs.get("quiet_end", "07:00"))
    if not start or not end:
        return False

    tz_name = prefs.get("quiet_timezone") or "Europe/Rome"
    try:
        tz = ZoneInfo(tz_name) if ZoneInfo else None
    except Exception:
        tz = None

    ref = now or datetime.now(tz) if tz else datetime.now()
    current = ref.time().replace(second=0, microsecond=0)

    if start <= end:
        # same-day window, e.g. 13:00 -> 17:00
        return start <= current < end
    # overnight window, e.g. 22:00 -> 07:00
    return current >= start or current < end


async def get_user_prefs(db, user_id: str) -> Dict[str, Any]:
    doc = await db.user_notification_prefs.find_one({"user_id": user_id}, {"_id": 0})
    prefs = dict(DEFAULT_PREFS)
    if doc:
        for k in DEFAULT_PREFS:
            if k in doc:
                prefs[k] = doc[k]
    return prefs


async def _send_one(subscription: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    """Send a single web push to a subscription."""
    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps(payload),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims=dict(VAPID_CLAIMS),
        )
        return {"success": True, "endpoint": subscription.get("endpoint", "")[:60]}
    except WebPushException as exc:
        status = getattr(exc.response, "status_code", 0) if exc.response is not None else 0
        return {
            "success": False,
            "status": status,
            "error": str(exc),
            "expired": status in (404, 410),
            "endpoint": subscription.get("endpoint", "")[:60],
        }
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc), "expired": False}


async def send_to_user(
    db,
    user_id: str,
    payload: Dict[str, Any],
    log_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Send web push to all active subscriptions of a user.
    Automatically deletes expired/invalid subscriptions (404/410).
    Respects the user's Quiet Hours preferences.
    Writes per-delivery rows in `notification_delivery_log` when log_context is given
    (expected keys: alert_id, type in {initial|escalation}).
    """
    if not is_configured():
        await _log_delivery(db, log_context, user_id, None, "vapid_not_configured")
        return {"success": False, "reason": "vapid_not_configured"}

    # Quiet hours check
    prefs = await get_user_prefs(db, user_id)
    severity = (payload.get("severity") or "").lower()
    if is_in_quiet_hours(prefs, severity):
        await _log_delivery(db, log_context, user_id, None, "skipped_quiet_hours")
        return {"success": True, "sent": 0, "skipped": "quiet_hours"}

    subs = await db.push_subscriptions.find({"user_id": user_id}, {"_id": 0}).to_list(length=50)
    if not subs:
        await _log_delivery(db, log_context, user_id, None, "no_subscriptions")
        return {"success": True, "sent": 0}

    sent = 0
    expired_endpoints: List[str] = []
    for s in subs:
        endpoint = s["subscription"].get("endpoint", "")
        result = await _send_one(s["subscription"], payload)
        if result.get("success"):
            sent += 1
            await _log_delivery(db, log_context, user_id, endpoint, "delivered")
        elif result.get("expired"):
            expired_endpoints.append(endpoint)
            await _log_delivery(db, log_context, user_id, endpoint, "expired", error=result.get("error"))
        else:
            await _log_delivery(db, log_context, user_id, endpoint, "failed", error=result.get("error"))

    if expired_endpoints:
        await db.push_subscriptions.delete_many({"subscription.endpoint": {"$in": expired_endpoints}})
        logger.info(f"[webpush] Pruned {len(expired_endpoints)} expired subscriptions for user {user_id}")

    return {"success": True, "sent": sent, "pruned": len(expired_endpoints)}


async def _log_delivery(
    db,
    log_context: Optional[Dict[str, Any]],
    user_id: str,
    endpoint: Optional[str],
    outcome: str,
    error: Optional[str] = None,
) -> None:
    """Write a row to notification_delivery_log (best-effort).
    Usa cache in-memory con TTL 60s per evitare N+1 sulle users (batch-friendly)."""
    if not log_context or not log_context.get("alert_id"):
        return
    try:
        user_email, user_name = await _get_user_cached(db, user_id)
        now = datetime.now(timezone.utc)
        await db.notification_delivery_log.insert_one(
            {
                "alert_id": log_context.get("alert_id"),
                "type": log_context.get("type", "initial"),
                "user_id": user_id,
                "user_email": user_email,
                "user_name": user_name,
                "channel": "web_push",
                "endpoint": (endpoint[-40:] if endpoint else ""),
                "outcome": outcome,
                "error": (error or "")[:300],
                "created_at": now.isoformat(),
                "created_at_ts": now,  # BSON Date for TTL index
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[webpush] _log_delivery failed: {exc}")


# Cache utenti (user_id -> (email, name, cached_at)) con TTL 60s per evitare N+1
_USER_CACHE: Dict[str, tuple] = {}
_USER_CACHE_TTL = 60.0


async def _get_user_cached(db, user_id: str) -> tuple:
    """Return (email, name) per user_id con cache in-memory."""
    import time
    now = time.monotonic()
    cached = _USER_CACHE.get(user_id)
    if cached and (now - cached[2]) < _USER_CACHE_TTL:
        return cached[0], cached[1]
    doc = await db.users.find_one({"id": user_id}, {"_id": 0, "email": 1, "name": 1})
    email = (doc or {}).get("email", "")
    name = (doc or {}).get("name", "")
    _USER_CACHE[user_id] = (email, name, now)
    # Limite cache a 500 entry per evitare crescita infinita
    if len(_USER_CACHE) > 500:
        # Rimuove le 100 più vecchie
        oldest = sorted(_USER_CACHE.items(), key=lambda kv: kv[1][2])[:100]
        for k, _ in oldest:
            _USER_CACHE.pop(k, None)
    return email, name


async def send_to_roles(db, roles: List[str], payload: Dict[str, Any], log_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Send web push to all users with any of the given roles."""
    if not is_configured():
        return {"success": False, "reason": "vapid_not_configured"}

    users = await db.users.find({"role": {"$in": roles}}, {"_id": 0, "id": 1}).to_list(length=500)
    total_sent = 0
    total_pruned = 0
    for u in users:
        res = await send_to_user(db, u["id"], payload, log_context=log_context)
        total_sent += res.get("sent", 0)
        total_pruned += res.get("pruned", 0)

    return {"success": True, "users": len(users), "sent": total_sent, "pruned": total_pruned}


def build_alert_payload(alert: Dict[str, Any]) -> Dict[str, Any]:
    """Build web push payload from alert doc."""
    severity = (alert.get("severity") or "medium").lower()
    title_prefix = {
        "critical": "🚨 CRITICO",
        "high": "⚠️ ALTO",
        "medium": "ℹ️ MEDIO",
        "low": "✅ BASSO",
    }.get(severity, "ALERT")

    device_name = alert.get("device_name") or alert.get("device_ip") or ""
    body_parts = []
    if device_name:
        body_parts.append(device_name)
    if alert.get("client_name"):
        body_parts.append(alert["client_name"])
    body = " · ".join(body_parts) if body_parts else (alert.get("message") or "")

    return {
        "title": f"{title_prefix} · {alert.get('title') or 'Alert'}",
        "body": body or alert.get("title", ""),
        "icon": "/icon-192.png",
        "tag": f"alert-{alert.get('id','')}",
        "severity": severity,
        "data": {
            "alert_id": alert.get("id"),
            "url": f"/alerts/{alert.get('id','')}" if alert.get("id") else "/alerts",
            "client_id": alert.get("client_id"),
        },
    }


async def notify_new_alert(db, alert_doc: Dict[str, Any]) -> None:
    """Fire-and-forget: notify on-call operator(s) OR all admins+operators about a new alert.
    Respects per-severity notification rules and on-call rotation if enabled.
    Errors are swallowed (logged) to avoid blocking alert ingestion."""
    try:
        if not is_configured():
            return

        # Load severity rule
        severity = (alert_doc.get("severity") or "medium").lower()
        rule = await db.notification_rules.find_one(
            {"severity": severity}, {"_id": 0}
        )
        # Default: critical + high -> push; others silent
        default_enabled = severity in ("critical", "high")
        enabled = rule.get("push_enabled", default_enabled) if rule else default_enabled
        if not enabled:
            return

        payload = build_alert_payload(alert_doc)
        log_ctx = {"alert_id": alert_doc.get("id"), "type": "initial"}

        # On-call rotation: if a schedule is active, only notify those users
        try:
            import oncall as _oncall
            oncall_user_ids = await _oncall.get_on_call_user_ids(db)
        except Exception:
            oncall_user_ids = []

        if oncall_user_ids:
            for uid in oncall_user_ids:
                await send_to_user(db, uid, payload, log_context=log_ctx)
            return

        # Fallback: all admins + operators
        await send_to_roles(db, ["admin", "operator"], payload, log_context=log_ctx)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[webpush] notify_new_alert failed: {exc}")
