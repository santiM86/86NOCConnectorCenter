"""Alert CRUD and trends routes."""
from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from collections import defaultdict
import uuid
import json
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("alerts")

from database import db
from models import AlertCreate, AlertResponse, AlertUpdate
from audit import AuditAction
from notifications import NotificationChannel, NotificationPriority
from deps import (
    get_current_user, audit_logger, notification_service,
    manager, correlation_manager, maintenance_manager
)

router = APIRouter(prefix="/api", tags=["alerts"])


@router.post("/alerts", response_model=AlertResponse)
async def create_alert(alert: AlertCreate, current_user: dict = Depends(get_current_user)):
    device = await db.devices.find_one({"id": alert.device_id}, {"_id": 0})
    client = await db.clients.find_one({"id": alert.client_id}, {"_id": 0})
    alert_doc = {
        "id": str(uuid.uuid4()), "client_id": alert.client_id,
        "device_id": alert.device_id, "severity": alert.severity,
        "source_type": alert.source_type, "title": alert.title,
        "message": alert.message, "raw_data": alert.raw_data or "",
        "status": "active", "acknowledged_by": None,
        "acknowledged_at": None, "resolved_at": None,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    in_maintenance, maint_window = await maintenance_manager.is_in_maintenance(
        alert.client_id, alert.device_id, alert.severity
    )
    if in_maintenance:
        alert_doc["suppressed_by_maintenance"] = True
        alert_doc["maintenance_window_id"] = maint_window["id"]
    alert_doc = await correlation_manager.prepare_alert_for_storage(alert_doc)
    is_duplicate, original_id = await correlation_manager.check_duplicate(alert_doc)
    if is_duplicate:
        # Override the id with original_id for duplicate alerts
        alert_doc_copy = dict(alert_doc)
        alert_doc_copy["id"] = original_id
        return AlertResponse(
            **alert_doc_copy,
            client_name=client["name"] if client else "",
            device_name=device["name"] if device else "",
            device_type=device["device_type"] if device else "",
            ip_address=device["ip_address"] if device else ""
        )
    is_storm, storm_count = await correlation_manager.check_alert_storm(alert.client_id, alert.device_id)
    if is_storm:
        alert_doc["in_storm"] = True
    await db.alerts.insert_one(alert_doc)
    try:
        import webpush as _wp
        await _wp.notify_new_alert(db, alert_doc)
    except Exception:
        pass
    correlation_id = await correlation_manager.correlate_alerts(alert_doc)
    if correlation_id:
        alert_doc["correlation_group_id"] = correlation_id
    response = AlertResponse(
        **alert_doc,
        client_name=client["name"] if client else "",
        device_name=device["name"] if device else "",
        device_type=device["device_type"] if device else "",
        ip_address=device["ip_address"] if device else ""
    )
    await manager.broadcast({"type": "new_alert", "alert": response.model_dump()})
    if alert.severity in ["critical", "high"] and not in_maintenance:
        await notification_service.send_notification(
            channels=[NotificationChannel.EMAIL, NotificationChannel.PUSH],
            title=alert.title, message=alert.message,
            priority=NotificationPriority.CRITICAL if alert.severity == "critical" else NotificationPriority.HIGH,
            alert_id=alert_doc["id"],
            data={"device": device["name"] if device else "", "client": client["name"] if client else ""}
        )
    await audit_logger.log(
        AuditAction.CREATE_ALERT, user_id=current_user["id"], user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        resource_type="alert", resource_id=alert_doc["id"],
        details={"severity": alert.severity, "title": alert.title}
    )
    return response


@router.get("/alerts", response_model=List[AlertResponse])
async def get_alerts(
    status: Optional[str] = None, severity: Optional[str] = None,
    client_id: Optional[str] = None, device_type: Optional[str] = None,
    limit: int = 100, current_user: dict = Depends(get_current_user)
):
    query = {}
    if status: query["status"] = status
    if severity: query["severity"] = severity
    if client_id: query["client_id"] = client_id
    alerts = await db.alerts.find(query, {"_id": 0}).sort("created_at", -1).to_list(limit)
    device_ids = list(set(a.get("device_id", "") for a in alerts if a.get("device_id")))
    client_ids = list(set(a.get("client_id", "") for a in alerts if a.get("client_id")))
    devices = await db.devices.find({"id": {"$in": device_ids}}, {"_id": 0}).to_list(1000)
    clients = await db.clients.find({"id": {"$in": client_ids}}, {"_id": 0}).to_list(1000)
    device_map = {d["id"]: d for d in devices}
    client_map = {c["id"]: c["name"] for c in clients}
    result = []
    for a in alerts:
        device = device_map.get(a.get("device_id", ""), {})
        if device_type and device.get("device_type") != device_type:
            continue
        a["client_name"] = client_map.get(a.get("client_id", ""), "")
        a["device_name"] = a.get("device_name") or device.get("name", "") or a.get("device_ip", "")
        a["device_type"] = a.get("device_type") or device.get("device_type", "")
        a["ip_address"] = device.get("ip_address", "") or a.get("device_ip", "")
        try:
            result.append(AlertResponse(**a))
        except Exception as e:
            logger.warning(f"Skip invalid alert {a.get('id','?')}: {e}")
            continue
    return result


@router.get("/alerts/{alert_id}", response_model=AlertResponse)
async def get_alert(alert_id: str, current_user: dict = Depends(get_current_user)):
    alert = await db.alerts.find_one({"id": alert_id}, {"_id": 0})
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    device = await db.devices.find_one({"id": alert.get("device_id", "")}, {"_id": 0})
    client = await db.clients.find_one({"id": alert.get("client_id", "")}, {"_id": 0})
    alert["client_name"] = client["name"] if client else ""
    alert["device_name"] = device["name"] if device else ""
    alert["device_type"] = device["device_type"] if device else ""
    alert["ip_address"] = device["ip_address"] if device else ""
    return AlertResponse(**alert)


@router.patch("/alerts/{alert_id}")
async def update_alert(alert_id: str, update: AlertUpdate, current_user: dict = Depends(get_current_user)):
    alert = await db.alerts.find_one({"id": alert_id}, {"_id": 0})
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    update_data = {}
    if update.status:
        update_data["status"] = update.status
        if update.status == "acknowledged":
            update_data["acknowledged_by"] = current_user["name"]
            update_data["acknowledged_at"] = datetime.now(timezone.utc).isoformat()
        elif update.status == "resolved":
            update_data["resolved_at"] = datetime.now(timezone.utc).isoformat()
    await db.alerts.update_one({"id": alert_id}, {"$set": update_data})
    updated_alert = await db.alerts.find_one({"id": alert_id}, {"_id": 0})
    await manager.broadcast({"type": "alert_updated", "alert": updated_alert})
    await audit_logger.log(
        AuditAction.UPDATE_ALERT, user_id=current_user["id"], user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        resource_type="alert", resource_id=alert_id,
        details={"new_status": update.status}
    )
    return {"message": "Alert updated"}


@router.get("/stats/summary")
async def get_stats_summary(current_user: dict = Depends(get_current_user)):
    pipeline = [{"$match": {"status": "active"}}, {"$group": {"_id": "$severity", "count": {"$sum": 1}}}]
    severity_counts = await db.alerts.aggregate(pipeline).to_list(10)
    counts = {s["_id"]: s["count"] for s in severity_counts}
    total_active = sum(counts.values())
    total_clients = await db.clients.count_documents({})
    total_devices = await db.devices.count_documents({})
    return {
        "critical": counts.get("critical", 0), "high": counts.get("high", 0),
        "medium": counts.get("medium", 0), "low": counts.get("low", 0),
        "total_active": total_active, "total_clients": total_clients, "total_devices": total_devices
    }


@router.get("/stats/trends")
async def get_alert_trends(hours: int = 24, current_user: dict = Depends(get_current_user)):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    alerts = await db.alerts.find(
        {"created_at": {"$gte": cutoff}}, {"_id": 0, "created_at": 1, "severity": 1}
    ).to_list(10000)
    hourly_data = defaultdict(lambda: {"critical": 0, "high": 0, "medium": 0, "low": 0})
    for alert in alerts:
        hour = alert["created_at"][:13] + ":00"
        hourly_data[hour][alert["severity"]] += 1
    sorted_hours = sorted(hourly_data.keys())
    return [{"hour": h, **hourly_data[h]} for h in sorted_hours]
