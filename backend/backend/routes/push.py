"""Web Push (VAPID) subscription + test endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Any, Dict
from datetime import datetime, timezone
import logging

from database import db
from deps import get_current_user
import webpush as webpush_service

logger = logging.getLogger("push_routes")

router = APIRouter(prefix="/api/push", tags=["push"])


class PushSubscriptionPayload(BaseModel):
    subscription: Dict[str, Any]
    user_agent: str | None = None


@router.get("/vapid-public-key")
async def get_vapid_public_key():
    """Return the VAPID public key for browser subscription."""
    if not webpush_service.is_configured():
        raise HTTPException(503, "Web Push non configurato")
    return {"public_key": webpush_service.VAPID_PUBLIC_KEY}


@router.post("/subscribe")
async def subscribe(payload: PushSubscriptionPayload, current_user: dict = Depends(get_current_user)):
    """Register a browser push subscription for the current user."""
    sub = payload.subscription or {}
    endpoint = sub.get("endpoint")
    if not endpoint or not sub.get("keys"):
        raise HTTPException(400, "Subscription invalida: serve endpoint + keys")

    # Upsert: one record per (user_id, endpoint)
    await db.push_subscriptions.update_one(
        {"user_id": current_user["id"], "subscription.endpoint": endpoint},
        {
            "$set": {
                "user_id": current_user["id"],
                "user_email": current_user.get("email"),
                "subscription": sub,
                "user_agent": payload.user_agent or "",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            "$setOnInsert": {
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        },
        upsert=True,
    )
    return {"success": True}


class UnsubscribePayload(BaseModel):
    endpoint: str


@router.post("/unsubscribe")
async def unsubscribe(payload: UnsubscribePayload, current_user: dict = Depends(get_current_user)):
    """Remove a subscription identified by its endpoint."""
    result = await db.push_subscriptions.delete_one(
        {"user_id": current_user["id"], "subscription.endpoint": payload.endpoint}
    )
    return {"success": True, "deleted": result.deleted_count}


@router.get("/status")
async def push_status(current_user: dict = Depends(get_current_user)):
    """Return subscription count for current user."""
    count = await db.push_subscriptions.count_documents({"user_id": current_user["id"]})
    return {
        "configured": webpush_service.is_configured(),
        "active_subscriptions": count,
    }


@router.post("/test")
async def send_test(current_user: dict = Depends(get_current_user)):
    """Send a test push to all subscriptions of the current user.
    This endpoint bypasses Quiet Hours for testing purposes."""
    if not webpush_service.is_configured():
        raise HTTPException(503, "Web Push non configurato")

    # For a test we manually loop to skip the quiet_hours check
    subs = await db.push_subscriptions.find(
        {"user_id": current_user["id"]}, {"_id": 0}
    ).to_list(length=50)
    if not subs:
        return {"success": True, "sent": 0}

    payload = {
        "title": "🔔 Test Notifica ARGUS",
        "body": f"Notifica di prova inviata a {current_user.get('email','utente')}",
        "icon": "/icon-192.png",
        "tag": "noc-test",
        "severity": "low",
        "data": {"url": "/"},
    }
    sent = 0
    for s in subs:
        res = await webpush_service._send_one(s["subscription"], payload)
        if res.get("success"):
            sent += 1
    return {"success": True, "sent": sent}


class NotificationPrefs(BaseModel):
    quiet_hours_enabled: bool = False
    quiet_start: str = "22:00"
    quiet_end: str = "07:00"
    quiet_timezone: str = "Europe/Rome"
    quiet_exclude_critical: bool = True


@router.get("/preferences")
async def get_preferences(current_user: dict = Depends(get_current_user)):
    """Return the current user's notification preferences (Quiet Hours)."""
    return await webpush_service.get_user_prefs(db, current_user["id"])


@router.put("/preferences")
async def update_preferences(prefs: NotificationPrefs, current_user: dict = Depends(get_current_user)):
    """Update the current user's notification preferences (Quiet Hours)."""
    # Basic HH:MM validation
    for field in ("quiet_start", "quiet_end"):
        val = getattr(prefs, field)
        try:
            h, m = val.split(":")
            h_i, m_i = int(h), int(m)
            if not (0 <= h_i <= 23 and 0 <= m_i <= 59):
                raise ValueError
        except Exception:
            raise HTTPException(400, f"{field} deve essere in formato HH:MM (es. 22:00)")

    await db.user_notification_prefs.update_one(
        {"user_id": current_user["id"]},
        {
            "$set": {
                "user_id": current_user["id"],
                "user_email": current_user.get("email"),
                **prefs.model_dump(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        },
        upsert=True,
    )
    return {"success": True, "prefs": prefs.model_dump()}
