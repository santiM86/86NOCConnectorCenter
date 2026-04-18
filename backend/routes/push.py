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
    """Send a test push to all subscriptions of the current user."""
    if not webpush_service.is_configured():
        raise HTTPException(503, "Web Push non configurato")
    result = await webpush_service.send_to_user(
        db,
        current_user["id"],
        {
            "title": "🔔 Test Notifica ARGUS",
            "body": f"Notifica di prova inviata a {current_user.get('email','utente')}",
            "icon": "/icon-192.png",
            "tag": "noc-test",
            "severity": "low",
            "data": {"url": "/"},
        },
    )
    return result
