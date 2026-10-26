"""Settings routes (notifications, redfish)."""
from fastapi import APIRouter, Depends

from database import db
from models import NotificationSettingsUpdate
from deps import get_current_user

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings/notifications")
async def get_notification_settings(current_user: dict = Depends(get_current_user)):
    settings = await db.settings.find({"key": {"$regex": "^(email_|push_|webhook_)"}}, {"_id": 0}).to_list(100)
    return {s["key"]: s["value"] for s in settings}


@router.post("/settings/notifications")
async def update_notification_settings(settings: NotificationSettingsUpdate, current_user: dict = Depends(get_current_user)):
    updates = [
        {"key": "email_enabled", "value": settings.email_enabled},
        {"key": "push_enabled", "value": settings.push_enabled},
    ]
    if settings.webhook_teams: updates.append({"key": "webhook_teams", "value": settings.webhook_teams})
    if settings.webhook_slack: updates.append({"key": "webhook_slack", "value": settings.webhook_slack})
    if settings.webhook_telegram: updates.append({"key": "webhook_telegram", "value": settings.webhook_telegram})
    if settings.webhook_generic: updates.append({"key": "webhook_generic", "value": settings.webhook_generic})
    for update in updates:
        await db.settings.update_one({"key": update["key"]}, {"$set": update}, upsert=True)
    return {"message": "Settings updated"}


@router.get("/settings/redfish")
async def get_redfish_settings(current_user: dict = Depends(get_current_user)):
    setting = await db.settings.find_one({"key": "redfish_poll_interval"}, {"_id": 0})
    return {"poll_interval_minutes": setting.get("value", 5) if setting else 5, "enabled": True}


@router.post("/settings/redfish")
async def update_redfish_settings(poll_interval: int = 5, current_user: dict = Depends(get_current_user)):
    await db.settings.update_one(
        {"key": "redfish_poll_interval"},
        {"$set": {"key": "redfish_poll_interval", "value": poll_interval}},
        upsert=True
    )
    return {"message": "Redfish settings updated"}
