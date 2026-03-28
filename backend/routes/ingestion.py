"""Syslog and SNMP ingestion routes."""
from fastapi import APIRouter, HTTPException, Request
import uuid
import json
from datetime import datetime, timezone

from database import db
from models import SyslogMessage, SNMPTrap, AlertResponse
from notifications import NotificationChannel, NotificationPriority
from deps import (
    limiter, manager, notification_service,
    map_syslog_severity, map_snmp_severity
)

router = APIRouter(prefix="/api", tags=["ingestion"])


@router.post("/ingest/syslog")
@limiter.limit("100/minute")
async def ingest_syslog(request: Request, msg: SyslogMessage):
    client_data = None
    api_key = request.headers.get("X-API-Key")
    if api_key:
        client_data = await db.clients.find_one({"api_key": api_key}, {"_id": 0})
        if not client_data:
            raise HTTPException(status_code=401, detail="Invalid API key")
    else:
        body = await request.json()
        cid = body.get("client_id")
        if cid:
            client_data = await db.clients.find_one({"id": cid}, {"_id": 0})
    if not client_data:
        raise HTTPException(status_code=400, detail="Valid API key or client_id required")
    client_id = client_data["id"]
    device = await db.devices.find_one({"ip_address": msg.device_ip, "client_id": client_id}, {"_id": 0})
    if not device:
        device = {
            "id": str(uuid.uuid4()), "client_id": client_id,
            "name": f"Auto-{msg.device_ip}", "device_type": "unknown",
            "ip_address": msg.device_ip, "hostname": "", "location": "",
            "status": "active", "redfish_enabled": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.devices.insert_one(device)
    severity = map_syslog_severity(msg.severity_level)
    alert_doc = {
        "id": str(uuid.uuid4()), "client_id": client_id, "device_id": device["id"],
        "severity": severity, "source_type": "syslog",
        "title": f"Syslog: Facility {msg.facility} - Level {msg.severity_level}",
        "message": msg.message[:500],
        "raw_data": json.dumps({"facility": msg.facility, "severity_level": msg.severity_level, "message": msg.message, "timestamp": msg.timestamp or datetime.now(timezone.utc).isoformat()}, indent=2),
        "status": "active", "acknowledged_by": None, "acknowledged_at": None, "resolved_at": None,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.alerts.insert_one(alert_doc)
    client = await db.clients.find_one({"id": client_id}, {"_id": 0})
    response = AlertResponse(
        **alert_doc, client_name=client["name"] if client else "",
        device_name=device["name"], device_type=device["device_type"], ip_address=device["ip_address"]
    )
    await manager.broadcast({"type": "new_alert", "alert": response.model_dump()})
    if severity == "critical":
        await notification_service.send_notification(
            channels=[NotificationChannel.EMAIL, NotificationChannel.PUSH],
            title=alert_doc["title"], message=alert_doc["message"],
            priority=NotificationPriority.CRITICAL, alert_id=alert_doc["id"]
        )
    return {"status": "ok", "alert_id": alert_doc["id"]}


@router.post("/ingest/snmp")
@limiter.limit("100/minute")
async def ingest_snmp(request: Request, trap: SNMPTrap):
    client_data = None
    api_key = request.headers.get("X-API-Key")
    if api_key:
        client_data = await db.clients.find_one({"api_key": api_key}, {"_id": 0})
        if not client_data:
            raise HTTPException(status_code=401, detail="Invalid API key")
    else:
        body = await request.json()
        cid = body.get("client_id")
        if cid:
            client_data = await db.clients.find_one({"id": cid}, {"_id": 0})
    if not client_data:
        raise HTTPException(status_code=400, detail="Valid API key or client_id required")
    client_id = client_data["id"]
    device = await db.devices.find_one({"ip_address": trap.device_ip, "client_id": client_id}, {"_id": 0})
    if not device:
        device = {
            "id": str(uuid.uuid4()), "client_id": client_id,
            "name": trap.device_name if trap.device_name else f"Auto-{trap.device_ip}",
            "device_type": "switch", "ip_address": trap.device_ip,
            "hostname": "", "location": "", "status": "active", "redfish_enabled": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.devices.insert_one(device)
    severity = trap.severity if trap.severity else map_snmp_severity(trap.trap_type, trap.oid)
    title_map = {"linkDown": "Porta DOWN", "linkUp": "Porta UP (ripristinata)", "deviceDown": "Dispositivo NON RAGGIUNGIBILE", "deviceUp": "Dispositivo ONLINE"}
    title = title_map.get(trap.trap_type, f"SNMP: {trap.trap_type}")
    device_label = trap.device_name if trap.device_name else device["name"]
    alert_doc = {
        "id": str(uuid.uuid4()), "client_id": client_id, "device_id": device["id"],
        "severity": severity, "source_type": "snmp",
        "title": f"{title} - {device_label}", "message": trap.value,
        "raw_data": json.dumps({"oid": trap.oid, "value": trap.value, "trap_type": trap.trap_type, "device_ip": trap.device_ip, "timestamp": datetime.now(timezone.utc).isoformat()}, indent=2),
        "status": "active", "acknowledged_by": None, "acknowledged_at": None, "resolved_at": None,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.alerts.insert_one(alert_doc)
    client = await db.clients.find_one({"id": client_id}, {"_id": 0})
    response = AlertResponse(
        **alert_doc, client_name=client["name"] if client else "",
        device_name=device["name"], device_type=device["device_type"], ip_address=device["ip_address"]
    )
    await manager.broadcast({"type": "new_alert", "alert": response.model_dump()})
    if severity == "critical":
        await notification_service.send_notification(
            channels=[NotificationChannel.EMAIL, NotificationChannel.PUSH],
            title=alert_doc["title"], message=alert_doc["message"],
            priority=NotificationPriority.CRITICAL, alert_id=alert_doc["id"]
        )
    return {"status": "ok", "alert_id": alert_doc["id"]}
