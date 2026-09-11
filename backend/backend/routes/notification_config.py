"""Notification Configuration - Multi-channel notification templates with escalation."""
import logging
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from database import db
from deps import get_current_user

logger = logging.getLogger("notification_config")
router = APIRouter(prefix="/api/notifications", tags=["notifications"])


DEFAULT_CHANNELS = [
    {"type": "email", "label": "Email", "enabled": False, "config": {}},
    {"type": "sms", "label": "SMS", "enabled": False, "config": {}},
    {"type": "push", "label": "Push", "enabled": False, "config": {}},
    {"type": "webhook", "label": "Webhook HTTP", "enabled": False, "config": {"url": "", "method": "POST"}},
    {"type": "teams", "label": "Microsoft Teams", "enabled": False, "config": {"webhook_url": ""}},
]


@router.get("/templates")
async def get_notification_templates(current_user: dict = Depends(get_current_user)):
    """Get all notification templates."""
    templates = await db.notification_templates.find({}, {"_id": 0}).to_list(100)
    if not templates:
        defaults = [
            {
                "id": str(uuid.uuid4()),
                "name": "Alert Critico",
                "severity_filter": ["critical"],
                "channels": DEFAULT_CHANNELS.copy(),
                "escalation_enabled": True,
                "escalation_minutes": 5,
                "escalation_to": "",
                "message_template": "CRITICO: {alert_title} su {device_name} ({device_ip}) - {client_name}",
                "enabled": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            {
                "id": str(uuid.uuid4()),
                "name": "Alert Alto",
                "severity_filter": ["high"],
                "channels": DEFAULT_CHANNELS.copy(),
                "escalation_enabled": False,
                "escalation_minutes": 15,
                "escalation_to": "",
                "message_template": "ALTO: {alert_title} su {device_name} ({device_ip})",
                "enabled": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            {
                "id": str(uuid.uuid4()),
                "name": "Tutti gli Alert",
                "severity_filter": ["critical", "high", "medium", "low"],
                "channels": DEFAULT_CHANNELS.copy(),
                "escalation_enabled": False,
                "escalation_minutes": 30,
                "escalation_to": "",
                "message_template": "{severity}: {alert_title} - {device_name}",
                "enabled": False,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        ]
        for t in defaults:
            await db.notification_templates.insert_one({**t})
        templates = defaults

    return templates


@router.post("/templates")
async def create_template(body: dict, current_user: dict = Depends(get_current_user)):
    """Create a new notification template."""
    now = datetime.now(timezone.utc).isoformat()
    template = {
        "id": str(uuid.uuid4()),
        "name": body.get("name", "Nuovo Template"),
        "severity_filter": body.get("severity_filter", ["critical", "high"]),
        "channels": body.get("channels", DEFAULT_CHANNELS.copy()),
        "escalation_enabled": body.get("escalation_enabled", False),
        "escalation_minutes": body.get("escalation_minutes", 15),
        "escalation_to": body.get("escalation_to", ""),
        "message_template": body.get("message_template", "{severity}: {alert_title} - {device_name}"),
        "enabled": body.get("enabled", True),
        "created_at": now,
    }
    await db.notification_templates.insert_one({**template})
    template.pop("_id", None)
    return template


@router.put("/templates/{template_id}")
async def update_template(template_id: str, body: dict, current_user: dict = Depends(get_current_user)):
    """Update a notification template."""
    existing = await db.notification_templates.find_one({"id": template_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Template non trovato")

    allowed = ["name", "severity_filter", "channels", "escalation_enabled",
               "escalation_minutes", "escalation_to", "message_template", "enabled"]
    update = {k: v for k, v in body.items() if k in allowed}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()

    await db.notification_templates.update_one(
        {"id": template_id}, {"$set": update}
    )
    updated = await db.notification_templates.find_one({"id": template_id}, {"_id": 0})
    return updated


@router.delete("/templates/{template_id}")
async def delete_template(template_id: str, current_user: dict = Depends(get_current_user)):
    """Delete a notification template."""
    result = await db.notification_templates.delete_one({"id": template_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Template non trovato")
    return {"status": "ok"}


@router.post("/test")
async def test_notification(body: dict, current_user: dict = Depends(get_current_user)):
    """Send a test notification through specified channels."""
    channel_type = body.get("channel_type", "email")
    config = body.get("config", {})
    message = body.get("message", "Test di notifica dal NOC 86BIT")

    logger.info(f"Test notification: channel={channel_type}, message={message}")

    return {
        "status": "ok",
        "channel": channel_type,
        "message": f"Notifica di test inviata via {channel_type}",
        "note": "Integrazione reale richiede configurazione API key per il canale selezionato"
    }


@router.get("/escalation-rules")
async def get_escalation_rules(current_user: dict = Depends(get_current_user)):
    """Get escalation rules."""
    rules = await db.escalation_rules.find({}, {"_id": 0}).to_list(50)
    if not rules:
        defaults = [
            {
                "id": str(uuid.uuid4()),
                "name": "Escalation Critico",
                "trigger": "no_ack",
                "minutes": 5,
                "severity": ["critical"],
                "action": "notify_escalation",
                "notify_to": "",
                "enabled": True,
            },
            {
                "id": str(uuid.uuid4()),
                "name": "Escalation Alto",
                "trigger": "no_ack",
                "minutes": 15,
                "severity": ["high"],
                "action": "notify_escalation",
                "notify_to": "",
                "enabled": True,
            },
        ]
        for r in defaults:
            await db.escalation_rules.insert_one({**r})
        rules = defaults
    return rules
