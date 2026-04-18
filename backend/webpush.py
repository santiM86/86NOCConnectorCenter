"""
Web Push (VAPID) service for NOC alerts.
Delivers real push notifications to subscribed browsers / installed PWAs.
"""
import os
import json
import logging
from datetime import datetime, time as dtime
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


async def send_to_user(db, user_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Send web push to all active subscriptions of a user.
    Automatically deletes expired/invalid subscriptions (404/410).
    Respects the user's Quiet Hours preferences."""
    if not is_configured():
        return {"success": False, "reason": "vapid_not_configured"}

    # Quiet hours check
    prefs = await get_user_prefs(db, user_id)
    severity = (payload.get("severity") or "").lower()
    if is_in_quiet_hours(prefs, severity):
        return {"success": True, "sent": 0, "skipped": "quiet_hours"}

    subs = await db.push_subscriptions.find({"user_id": user_id}, {"_id": 0}).to_list(length=50)
    if not subs:
        return {"success": True, "sent": 0}

    sent = 0
    expired_endpoints: List[str] = []
    for s in subs:
        result = await _send_one(s["subscription"], payload)
        if result.get("success"):
            sent += 1
        elif result.get("expired"):
            expired_endpoints.append(s["subscription"].get("endpoint"))

    if expired_endpoints:
        await db.push_subscriptions.delete_many({"subscription.endpoint": {"$in": expired_endpoints}})
        logger.info(f"[webpush] Pruned {len(expired_endpoints)} expired subscriptions for user {user_id}")

    return {"success": True, "sent": sent, "pruned": len(expired_endpoints)}


async def send_to_roles(db, roles: List[str], payload: Dict[str, Any]) -> Dict[str, Any]:
    """Send web push to all users with any of the given roles."""
    if not is_configured():
        return {"success": False, "reason": "vapid_not_configured"}

    users = await db.users.find({"role": {"$in": roles}}, {"_id": 0, "id": 1}).to_list(length=500)
    total_sent = 0
    total_pruned = 0
    for u in users:
        res = await send_to_user(db, u["id"], payload)
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

        # On-call rotation: if a schedule is active, only notify those users
        try:
            import oncall as _oncall
            oncall_user_ids = await _oncall.get_on_call_user_ids(db)
        except Exception:
            oncall_user_ids = []

        if oncall_user_ids:
            for uid in oncall_user_ids:
                await send_to_user(db, uid, payload)
            return

        # Fallback: all admins + operators
        await send_to_roles(db, ["admin", "operator"], payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[webpush] notify_new_alert failed: {exc}")
