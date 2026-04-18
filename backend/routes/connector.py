"""Connector endpoints: heartbeat, auto-update, device management.
Security: HMAC-SHA256, Anti-Replay, Obfuscated paths, TLS 1.2+
"""
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse
import uuid
import shutil
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone, timedelta

from database import db
from models import ConnectorHeartbeat, ManagedDevice
from security import security_manager
from audit import AuditAction
from deps import (
    get_current_user, validate_api_key, audit_logger,
    check_nosql_injection, sanitize_string, is_newer_version,
    CONNECTOR_STORAGE,
)
from middleware.connector_security import (
    verify_connector_request, rotate_api_key, CONNECTOR_PATH,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["connector"])

# Obfuscated base path for connector-only endpoints
C = CONNECTOR_PATH  # e.g. "c7x9"


# ==================== HEARTBEAT ====================

@router.post(f"/{C}/hb")
@router.post("/connector/heartbeat")
async def connector_heartbeat(request: Request, heartbeat: ConnectorHeartbeat):
    client_data = await verify_connector_request(request)
    existing = await db.connector_status.find_one({"client_id": client_data["id"]}, {"_id": 0})
    force_update = existing.get("force_update", False) if existing else False
    await db.connector_status.update_one(
        {"client_id": client_data["id"]},
        {"$set": {
            "client_id": client_data["id"], "client_name": client_data["name"],
            "connector_version": heartbeat.connector_version, "hostname": heartbeat.hostname,
            "connector_ip": request.client.host if request.client else "unknown",
            "uptime_seconds": heartbeat.uptime_seconds,
            "traps_received": heartbeat.traps_received, "syslogs_received": heartbeat.syslogs_received,
            "last_seen": datetime.now(timezone.utc).isoformat()
        }},
        upsert=True
    )
    if existing and existing.get("update_status"):
        update_info = await db.connector_updates.find_one({"active": True}, {"_id": 0})
        should_clear = False
        if update_info:
            if not is_newer_version(update_info["version"], heartbeat.connector_version):
                should_clear = True
        update_timestamp = existing.get("update_timestamp")
        if update_timestamp:
            try:
                ts = datetime.fromisoformat(update_timestamp.replace("Z", "+00:00"))
                elapsed = (datetime.now(timezone.utc) - ts).total_seconds()
                if elapsed > 300:
                    should_clear = True
                    logger.warning(f"Update status timeout for {client_data.get('name')}: {elapsed:.0f}s elapsed, clearing")
            except Exception:
                should_clear = True
        if should_clear:
            await db.connector_status.update_one(
                {"client_id": client_data["id"]},
                {"$unset": {"update_status": "", "force_update": "", "update_progress": "", "update_message": "", "update_timestamp": ""}}
            )
    response = {"status": "ok"}
    pending_cmds = await db.pending_commands.find({"client_id": client_data["id"], "status": "pending"}, {"_id": 0}).sort("created_at", 1).to_list(10)
    if pending_cmds:
        response["pending_commands"] = pending_cmds
        cmd_ids = [c["id"] for c in pending_cmds]
        await db.pending_commands.update_many(
            {"id": {"$in": cmd_ids}},
            {"$set": {"status": "dispatched", "dispatched_at": datetime.now(timezone.utc).isoformat()}}
        )
    if force_update:
        update_info = await db.connector_updates.find_one({"active": True}, {"_id": 0})
        if update_info and is_newer_version(update_info["version"], heartbeat.connector_version):
            response["force_update"] = True
            response["latest_version"] = update_info["version"]
            response["download_url"] = f"/api/connector/download/{update_info['filename']}"
            response["changelog"] = update_info.get("changelog", "")
            await db.connector_status.update_one(
                {"client_id": client_data["id"]}, {"$set": {"force_update": False}}
            )
    # Key rotation check
    if client_data.get("_key_rotation_needed"):
        rotated = await rotate_api_key(client_data["id"])
        response["key_rotation"] = rotated
    # Provide secure path info
    response["secure_path"] = C
    if client_data.get("_legacy_auth"):
        response["security_upgrade_available"] = True
    return response



@router.post(f"/{C}/md")
@router.post("/connector/managed-devices")
async def connector_managed_devices(request: Request):
    """Return the list of managed devices for this connector's client."""
    client_data = await verify_connector_request(request)
    devices = await db.managed_devices.find(
        {"client_id": client_data["id"]}, {"_id": 0}
    ).to_list(500)
    return {"devices": devices}



# ==================== VAULT CREDENTIALS FOR CONNECTOR ====================

@router.get(f"/{C}/vc")
@router.get("/connector/vault/credentials")
async def connector_get_vault_credentials(request: Request):
    client_data = await verify_connector_request(request)
    client_id = client_data["id"]
    # Return only credentials that belong to this client OR are global (no client_id)
    creds = await db.device_credentials.find(
        {"$or": [{"client_id": client_id}, {"client_id": None}, {"client_id": ""}, {"client_id": {"$exists": False}}]},
        {"_id": 0}
    ).to_list(500)
    result = []
    for c in creds:
        try:
            decrypted = {
                "device_ip": c.get("device_ip"), "device_name": c.get("device_name"),
                "credential_type": c.get("credential_type"),
                "username": security_manager.decrypt_credential(c["username_enc"]),
                "password": security_manager.decrypt_credential(c["password_enc"]),
                "url": c.get("url"), "port": c.get("port"),
            }
            result.append(decrypted)
        except Exception:
            continue
    await audit_logger.log(
        AuditAction.SUSPICIOUS_ACTIVITY,
        user_email=f"connector:{client_data.get('name', 'unknown')}",
        details={"action": "connector_vault_fetch", "client_id": client_id, "count": len(result)},
        severity="info"
    )
    return result


# ==================== STATUS ====================

@router.get("/connector/status")
async def get_connector_status(current_user: dict = Depends(get_current_user)):
    connectors = await db.connector_status.find({}, {"_id": 0}).to_list(100)
    return connectors


@router.delete("/connector/status/{hostname}")
async def delete_connector_status(hostname: str, current_user: dict = Depends(get_current_user)):
    result = await db.connector_status.delete_one({"hostname": hostname})
    if result.deleted_count == 0:
        result = await db.connector_status.delete_one({"client_name": hostname})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Connector not found")
    return {"status": "ok"}


@router.post("/connector/{client_id}/force-update")
async def force_connector_update(client_id: str, current_user: dict = Depends(get_current_user)):
    connector = await db.connector_status.find_one({"client_id": client_id}, {"_id": 0})
    if not connector:
        raise HTTPException(status_code=404, detail="Connector non trovato")
    update_info = await db.connector_updates.find_one({"active": True}, {"_id": 0})
    if not update_info:
        raise HTTPException(status_code=400, detail="Nessun aggiornamento disponibile")
    if not is_newer_version(update_info["version"], connector.get("connector_version", "0.0.0")):
        raise HTTPException(status_code=400, detail="Il connector e' gia' alla versione piu' recente")
    await db.connector_status.update_one({"client_id": client_id}, {"$set": {"force_update": True}})
    return {
        "status": "ok",
        "message": f"Aggiornamento forzato per {connector.get('hostname', client_id)}. Verra' applicato al prossimo heartbeat (~60s).",
        "target_version": update_info["version"]
    }


# ==================== AUTO-UPDATE ====================

@router.get(f"/{C}/uc")
@router.get("/connector/update-check")
async def connector_update_check(request: Request):
    api_key = request.headers.get("X-API-Key")
    client_data = None
    if api_key:
        client_data = await db.clients.find_one({"api_key": api_key}, {"_id": 0})
        if not client_data:
            raise HTTPException(status_code=401, detail="Invalid API key")
    update_info = await db.connector_updates.find_one({"active": True}, {"_id": 0})
    if not update_info:
        return {"update_available": False, "latest_version": "1.0.0"}
    current_version = "0.0.0"
    if client_data:
        connector = await db.connector_status.find_one({"client_id": client_data["id"]}, {"_id": 0})
        if connector:
            current_version = connector.get("connector_version", "0.0.0")
    published_version = update_info["version"]
    update_needed = is_newer_version(published_version, current_version)
    return {
        "update_available": update_needed, "latest_version": published_version,
        "download_url": f"/api/connector/download/{update_info['filename']}",
        "changelog": update_info.get("changelog", ""),
        "published_at": update_info.get("published_at", ""),
        "file_size": update_info.get("file_size", 0)
    }


@router.get("/connector/download/{filename}")
async def connector_download(filename: str, request: Request):
    try:
        client_data = await verify_connector_request(request)
    except Exception:
        client_data = None
        if not client_data:
            raise HTTPException(status_code=401, detail="Invalid API key")
    filepath = CONNECTOR_STORAGE / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=str(filepath), filename=filename, media_type="application/zip")


@router.post("/connector/upload-update")
async def upload_connector_update(request: Request, file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["admin", "security_admin"]:
        raise HTTPException(status_code=403, detail="Admin role required")
    if not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only ZIP files accepted")
    body = await request.form()
    version = body.get("version", "")
    changelog = body.get("changelog", "")
    if not version:
        raise HTTPException(status_code=400, detail="Version is required")
    safe_filename = f"86NocConnector_v{version}.zip"
    filepath = CONNECTOR_STORAGE / safe_filename
    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)
    await db.connector_updates.update_many({}, {"$set": {"active": False}})
    update_doc = {
        "version": version, "filename": safe_filename, "changelog": changelog,
        "file_size": len(content), "active": True,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "uploaded_by": current_user.get("name", "admin")
    }
    await db.connector_updates.insert_one(update_doc)
    public_path = Path("/app/frontend/public/86NocConnector.zip")
    shutil.copy2(filepath, public_path)
    return {
        "status": "ok", "version": version, "filename": safe_filename,
        "connectors_will_update": "I connettori si aggiorneranno automaticamente entro 6 ore"
    }


@router.get("/connector/update-info")
async def get_connector_update_info(current_user: dict = Depends(get_current_user)):
    update_info = await db.connector_updates.find_one({"active": True}, {"_id": 0})
    total_connectors = await db.connector_status.count_documents({})
    if update_info:
        all_connectors = await db.connector_status.find({}, {"_id": 0, "connector_version": 1}).to_list(500)
        updated = sum(1 for c in all_connectors if not is_newer_version(update_info["version"], c.get("connector_version", "0.0.0")))
        update_info["total_connectors"] = total_connectors
        update_info["updated_connectors"] = updated
        update_info["pending_connectors"] = total_connectors - updated
    return update_info or {"version": "1.0.0", "total_connectors": total_connectors, "updated_connectors": 0, "pending_connectors": 0}


@router.post(f"/{C}/up")
@router.post("/connector/update-progress")
async def connector_update_progress(request: Request):
    client_data = await verify_connector_request(request)
    body = await request.json()
    progress = body.get("progress", 0)
    status = body.get("status", "unknown")
    message = body.get("message", "")
    await db.connector_status.update_one(
        {"client_id": client_data["id"]},
        {"$set": {
            "update_progress": progress, "update_status": status,
            "update_message": message, "update_timestamp": datetime.now(timezone.utc).isoformat()
        }}
    )
    return {"status": "ok"}


@router.post("/connector/{connector_id}/reset-update-status")
async def reset_connector_update_status(connector_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ["admin"]:
        raise HTTPException(status_code=403, detail="Solo admin")
    result = await db.connector_status.update_one(
        {"client_id": connector_id},
        {"$unset": {"update_status": "", "force_update": "", "update_progress": "", "update_message": "", "update_timestamp": ""}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Connettore non trovato")
    return {"status": "ok", "message": "Stato aggiornamento resettato"}


# ==================== DEVICE MANAGEMENT ====================

@router.post(f"/{C}/dr")
async def _check_device_thresholds(client_id: str, dev: dict, prev_status: Optional[dict]):
    """Generate alerts for threshold crossings and state changes on a device."""
    device_ip = dev["device_ip"]
    device_name = dev.get("device_name") or device_ip
    device_type = dev.get("device_class") or "generic"
    now_iso = datetime.now(timezone.utc).isoformat()

    # Load client thresholds with defaults
    th = await db.alert_thresholds.find_one({"client_id": client_id}, {"_id": 0}) or {}
    cpu_crit = th.get("cpu_critical_pct", 95)
    cpu_warn = th.get("cpu_warning_pct", 80)
    mem_crit = th.get("memory_critical_pct", 95)
    mem_warn = th.get("memory_warning_pct", 85)
    offline_after_min = th.get("offline_alert_after_min", 5)

    alerts_to_create = []

    # --- Reachability / offline transition
    reachable = dev.get("reachable", True)
    prev_reachable = (prev_status or {}).get("reachable", True) if prev_status else True
    if not reachable and prev_reachable:
        # Use unreachable_since to debounce: only alert if down >= offline_after_min
        unreachable_since = (prev_status or {}).get("unreachable_since") or now_iso
        try:
            minutes_down = (datetime.now(timezone.utc) - datetime.fromisoformat(unreachable_since.replace("Z", "+00:00"))).total_seconds() / 60
        except Exception:
            minutes_down = offline_after_min
        if minutes_down >= offline_after_min or True:  # first transition: fire immediately
            alerts_to_create.append({
                "severity": "critical",
                "title": f"Dispositivo OFFLINE: {device_name}",
                "message": f"{device_name} ({device_ip}) non risponde al polling SNMP/Ping",
                "source_type": "connector_offline",
            })
    elif reachable and not prev_reachable:
        alerts_to_create.append({
            "severity": "low",
            "title": f"Dispositivo ONLINE (ripristinato): {device_name}",
            "message": f"{device_name} ({device_ip}) ha ripreso a rispondere",
            "source_type": "connector_recovery",
        })
        # Resolve previous offline alerts
        await db.alerts.update_many(
            {"client_id": client_id, "device_ip": device_ip, "source_type": "connector_offline", "status": "active"},
            {"$set": {"status": "resolved", "resolved_at": now_iso}}
        )

    # --- CPU
    cpu = dev.get("cpu_usage")
    if cpu is not None and isinstance(cpu, (int, float)):
        if cpu >= cpu_crit:
            alerts_to_create.append({
                "severity": "critical",
                "title": f"CPU critica ({int(cpu)}%): {device_name}",
                "message": f"Utilizzo CPU {cpu}% su {device_name} ({device_ip}) — soglia critica {cpu_crit}%",
                "source_type": "threshold_cpu",
            })
        elif cpu >= cpu_warn:
            alerts_to_create.append({
                "severity": "high",
                "title": f"CPU elevata ({int(cpu)}%): {device_name}",
                "message": f"Utilizzo CPU {cpu}% su {device_name} ({device_ip}) — soglia warning {cpu_warn}%",
                "source_type": "threshold_cpu",
            })

    # --- Memory
    mem = dev.get("memory_usage")
    if mem is not None and isinstance(mem, (int, float)):
        if mem >= mem_crit:
            alerts_to_create.append({
                "severity": "critical",
                "title": f"RAM critica ({int(mem)}%): {device_name}",
                "message": f"Utilizzo RAM {mem}% su {device_name} ({device_ip}) — soglia critica {mem_crit}%",
                "source_type": "threshold_memory",
            })
        elif mem >= mem_warn:
            alerts_to_create.append({
                "severity": "high",
                "title": f"RAM elevata ({int(mem)}%): {device_name}",
                "message": f"Utilizzo RAM {mem}% su {device_name} ({device_ip}) — soglia warning {mem_warn}%",
                "source_type": "threshold_memory",
            })

    # --- Temperature (generic SNMP temp, not Redfish)
    temp = dev.get("temperature")
    if temp is not None and isinstance(temp, (int, float)):
        if temp > 75:
            alerts_to_create.append({
                "severity": "critical",
                "title": f"Temperatura critica ({temp}°C): {device_name}",
                "message": f"Temperatura {temp}°C rilevata via SNMP su {device_name} ({device_ip})",
                "source_type": "threshold_temp",
            })

    # --- Port link DOWN (SNMP ifOperStatus)
    for p in (dev.get("ports") or []):
        # Only alert if previously up and now down
        if isinstance(p, dict) and p.get("oper_status") == "down" and p.get("admin_status") == "up":
            port_name = p.get("name") or p.get("index") or "?"
            alerts_to_create.append({
                "severity": "high",
                "title": f"Porta LAN DOWN: {port_name} ({device_name})",
                "message": f"Interfaccia {port_name} su {device_name} ({device_ip}) in stato operativo DOWN (admin UP)",
                "source_type": "threshold_port_down",
            })

    # Insert alerts (dedup by title + device + status=active)
    for a in alerts_to_create:
        existing = await db.alerts.find_one({
            "client_id": client_id,
            "device_ip": device_ip,
            "title": a["title"],
            "status": "active",
        })
        if existing:
            continue
        await db.alerts.insert_one({
            "id": str(uuid.uuid4()),
            "client_id": client_id,
            "device_ip": device_ip,
            "device_name": device_name,
            "device_type": device_type,
            "severity": a["severity"],
            "source_type": a["source_type"],
            "title": a["title"],
            "message": a["message"],
            "status": "active",
            "acknowledged_by": None, "acknowledged_at": None, "resolved_at": None,
            "created_at": now_iso,
        })


@router.post("/connector/device-report")
async def connector_device_report(request: Request):
    client_data = await verify_connector_request(request)
    body = await request.json()
    check_nosql_injection(body)
    client_id = client_data["id"]
    hostname = sanitize_string(body.get("hostname", "unknown"), 256)
    devices = body.get("devices", [])
    now_iso = datetime.now(timezone.utc).isoformat()
    for dev in devices:
        # Skip devices that were deleted by the user
        is_deleted = await db.deleted_devices.find_one({
            "client_id": client_id, "device_ip": dev["device_ip"]
        })
        if is_deleted:
            continue

        # Load prev status BEFORE update to detect state changes
        prev_status = await db.device_poll_status.find_one(
            {"client_id": client_id, "device_ip": dev["device_ip"]}, {"_id": 0}
        )

        doc = {
            "client_id": client_id, "connector_hostname": hostname,
            "device_ip": dev["device_ip"], "device_name": dev["device_name"],
            "reachable": dev["reachable"], "monitor_type": dev.get("monitor_type", "snmp"),
            "ports": dev.get("ports", []), "sys_descr": dev.get("sys_descr", ""),
            "sys_uptime": dev.get("sys_uptime", ""),
            "http_status": dev.get("http_status", None),
            "ping_ms": dev.get("ping_ms", None),
            "cpu_usage": dev.get("cpu_usage", None),
            "memory_usage": dev.get("memory_usage", None),
            "temperature": dev.get("temperature", None),
            "device_class": dev.get("device_class", "generic"),
            "hardware": dev.get("hardware", None),
            "firewall": dev.get("firewall", None),
            "redfish": dev.get("redfish", None),
            "ping_stats": dev.get("ping_stats", None),
            "open_ports": dev.get("open_ports", None),
            "http_details": dev.get("http_details", None),
            "last_poll": dev.get("poll_timestamp", now_iso),
            "updated_at": now_iso
        }
        # Track offline duration for debouncing offline alerts
        if not dev.get("reachable", True):
            # Only set unreachable_since the first time it goes down
            if prev_status and prev_status.get("reachable") and not prev_status.get("unreachable_since"):
                doc["unreachable_since"] = now_iso
            elif prev_status and prev_status.get("unreachable_since"):
                doc["unreachable_since"] = prev_status["unreachable_since"]
            else:
                doc["unreachable_since"] = now_iso
        else:
            doc["unreachable_since"] = None

        await db.device_poll_status.update_one(
            {"client_id": client_id, "device_ip": dev["device_ip"]},
            {"$set": doc}, upsert=True
        )

        # Generate alerts based on state transitions + thresholds
        try:
            await _check_device_thresholds(client_id, dev, prev_status)
        except Exception as e:
            logger.warning(f"Errore check soglie {dev.get('device_ip')}: {e}")

        if dev.get("cpu_usage") is not None or dev.get("temperature") is not None or dev.get("firewall") or dev.get("ping_stats"):
            metric_doc = {
                "client_id": client_id, "device_ip": dev["device_ip"], "timestamp": now_iso,
                "cpu_usage": dev.get("cpu_usage"), "memory_usage": dev.get("memory_usage"),
                "temperature": dev.get("temperature"),
                "active_sessions": dev.get("firewall", {}).get("active_sessions") if dev.get("firewall") else None,
                "vpn_throughput": dev.get("firewall", {}).get("vpn_throughput") if dev.get("firewall") else None,
                "ping_avg": dev.get("ping_stats", {}).get("avg") if dev.get("ping_stats") else dev.get("ping_ms"),
                "ping_jitter": dev.get("ping_stats", {}).get("jitter") if dev.get("ping_stats") else None,
                "packet_loss": dev.get("ping_stats", {}).get("packet_loss") if dev.get("ping_stats") else None,
            }
            await db.device_metrics_history.insert_one(metric_doc)
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            await db.device_metrics_history.delete_many({
                "client_id": client_id, "device_ip": dev["device_ip"], "timestamp": {"$lt": cutoff}
            })
    return {"status": "ok", "devices_updated": len(devices)}


@router.get("/connector/device-poll-status")
async def get_device_poll_status(current_user: dict = Depends(get_current_user)):
    statuses = await db.device_poll_status.find({}, {"_id": 0}).to_list(500)
    return statuses


@router.get("/connector/device-metrics/{device_ip}")
async def get_device_metrics_history(device_ip: str, current_user: dict = Depends(get_current_user)):
    metrics = await db.device_metrics_history.find(
        {"device_ip": device_ip},
        {"_id": 0, "timestamp": 1, "cpu_usage": 1, "memory_usage": 1, "temperature": 1, "active_sessions": 1, "vpn_throughput": 1, "ping_avg": 1, "ping_jitter": 1, "packet_loss": 1}
    ).sort("timestamp", 1).to_list(500)
    return metrics


@router.delete("/connector/device-poll-status/{device_ip}")
async def delete_device_poll_status(device_ip: str, current_user: dict = Depends(get_current_user)):
    # Get client_id before deleting
    poll_doc = await db.device_poll_status.find_one({"device_ip": device_ip})
    client_id = poll_doc.get("client_id") if poll_doc else None

    # Remove from ALL collections
    await db.device_poll_status.delete_many({"device_ip": device_ip})
    await db.managed_devices.delete_many({"ip": device_ip})
    await db.discovered_endpoints.delete_many({"ip": device_ip})
    await db.metrics_history.delete_many({"device_ip": device_ip})
    await db.device_metrics_history.delete_many({"device_ip": device_ip})
    await db.port_monitors.delete_many({"device_ip": device_ip})
    await db.lldp_neighbors.delete_many({"local_device_ip": device_ip})
    await db.mac_connections.delete_many({"switch_ip": device_ip})
    await db.port_speeds.delete_many({"device_ip": device_ip})

    # Mark as deleted so the connector won't re-sync it
    if client_id:
        await db.deleted_devices.update_one(
            {"client_id": client_id, "device_ip": device_ip},
            {"$set": {
                "client_id": client_id,
                "device_ip": device_ip,
                "deleted_at": datetime.now(timezone.utc).isoformat(),
                "deleted_by": current_user.get("email", "admin"),
            }},
            upsert=True,
        )

    logger.info(f"Device {device_ip} completely removed from all collections")
    return {"status": "ok"}


@router.put("/connector/device-poll-status/{device_ip}/monitor-type")
async def update_device_monitor_type(device_ip: str, request: Request, current_user: dict = Depends(get_current_user)):
    body = await request.json()
    monitor_type = body.get("monitor_type", "snmp")
    http_port = body.get("http_port", 80)
    await db.managed_devices.update_many(
        {"ip": device_ip},
        {"$set": {"monitor_type": monitor_type, "http_port": http_port, "community": "" if monitor_type != "snmp" else "public"}}
    )
    await db.device_poll_status.update_many({"device_ip": device_ip}, {"$set": {"monitor_type": monitor_type}})
    return {"status": "ok"}


@router.get("/connector/{client_id}/managed-devices")
async def get_managed_devices(client_id: str, request: Request):
    try:
        client_data = await verify_connector_request(request)
    except Exception:
        client_data = None
        if not client_data:
            raise HTTPException(status_code=401, detail="Invalid API key")
        client_id = client_data["id"]
    devices = await db.managed_devices.find({"client_id": client_id}, {"_id": 0}).to_list(200)

    # Filter out devices that were deleted from the web NOC
    deleted = await db.deleted_devices.find(
        {"client_id": client_id}, {"device_ip": 1, "_id": 0}
    ).to_list(500)
    deleted_ips = {d["device_ip"] for d in deleted}
    devices = [d for d in devices if d.get("ip") not in deleted_ips]

    return devices


@router.post("/connector/{client_id}/managed-devices")
async def add_managed_device(client_id: str, device: ManagedDevice, current_user: dict = Depends(get_current_user)):
    existing = await db.managed_devices.find_one({"client_id": client_id, "ip": device.ip})
    if existing:
        raise HTTPException(status_code=409, detail=f"Dispositivo {device.ip} gia' presente per questo cliente")
    doc = {
        "id": str(uuid.uuid4()), "client_id": client_id,
        "ip": device.ip, "community": device.community,
        "name": device.name, "monitor_type": device.monitor_type,
        "device_type": device.device_type,
        "http_port": device.http_port,
        "snmp_version": device.snmp_version,
        "snmpv3_username": device.snmpv3_username,
        "snmpv3_auth_protocol": device.snmpv3_auth_protocol,
        "snmpv3_auth_password": device.snmpv3_auth_password,
        "snmpv3_priv_protocol": device.snmpv3_priv_protocol,
        "snmpv3_priv_password": device.snmpv3_priv_password,
        "snmpv3_security_level": device.snmpv3_security_level,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": current_user.get("name", "admin")
    }
    await db.managed_devices.insert_one(doc)
    # Remove from blacklist if it was previously deleted
    await db.deleted_devices.delete_many({"client_id": client_id, "device_ip": device.ip})
    return {"status": "ok", "device": {k: v for k, v in doc.items() if k != "_id"}}


@router.delete("/connector/{client_id}/managed-devices/{device_id}")
async def remove_managed_device(client_id: str, device_id: str, current_user: dict = Depends(get_current_user)):
    result = await db.managed_devices.delete_one({"id": device_id, "client_id": client_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Device not found")
    await db.device_poll_status.delete_one({"client_id": client_id, "device_ip": device_id})
    return {"status": "ok"}


@router.put("/connector/{client_id}/managed-devices/{device_id}/snmp")
async def update_device_snmp_config(client_id: str, device_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    """Aggiorna la configurazione SNMP (v1/v2c/v3) di un dispositivo."""
    body = await request.json()
    check_nosql_injection(body)
    update = {}
    snmp_version = body.get("snmp_version", "v2c")
    update["snmp_version"] = snmp_version
    if snmp_version in ("v1", "v2c"):
        update["community"] = sanitize_string(body.get("community", "public"), 128)
        # Clear v3 fields
        for f in ("snmpv3_username", "snmpv3_auth_protocol", "snmpv3_auth_password", "snmpv3_priv_protocol", "snmpv3_priv_password", "snmpv3_security_level"):
            update[f] = None
    elif snmp_version == "v3":
        update["community"] = ""
        update["snmpv3_username"] = sanitize_string(body.get("snmpv3_username", ""), 128)
        update["snmpv3_auth_protocol"] = body.get("snmpv3_auth_protocol")  # MD5, SHA, SHA256
        update["snmpv3_auth_password"] = sanitize_string(body.get("snmpv3_auth_password", ""), 256)
        update["snmpv3_priv_protocol"] = body.get("snmpv3_priv_protocol")  # DES, AES, AES256
        update["snmpv3_priv_password"] = sanitize_string(body.get("snmpv3_priv_password", ""), 256)
        update["snmpv3_security_level"] = body.get("snmpv3_security_level", "authPriv")
    result = await db.managed_devices.update_one(
        {"id": device_id, "client_id": client_id},
        {"$set": update}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Device not found")
    await audit_logger.log(
        AuditAction.UPDATE_DEVICE,
        user_id=current_user["id"], user_email=current_user["email"],
        resource_type="device", resource_id=device_id,
        details={"action": "snmp_config_updated", "version": snmp_version},
    )
    return {"status": "ok", "snmp_version": snmp_version}



@router.get(f"/{C}/fd")
@router.get("/connector/fetch-devices")
async def connector_fetch_devices(request: Request):
    client_data = await verify_connector_request(request)
    devices = await db.managed_devices.find({"client_id": client_data["id"]}, {"_id": 0}).to_list(200)
    # Filter out devices that were deleted from the web NOC
    deleted = await db.deleted_devices.find(
        {"client_id": client_data["id"]}, {"device_ip": 1, "_id": 0}
    ).to_list(500)
    deleted_ips = {d["device_ip"] for d in deleted}
    devices = [d for d in devices if d.get("ip") not in deleted_ips]
    return [{
        "ip": d["ip"],
        "community": d.get("community", "public"),
        "name": d["name"],
        "monitor_type": d.get("monitor_type", "snmp"),
        "device_type": d.get("device_type", "network"),
        "http_port": d.get("http_port", 80),
        "snmp_version": d.get("snmp_version", "v2c"),
        "snmpv3_username": d.get("snmpv3_username"),
        "snmpv3_auth_protocol": d.get("snmpv3_auth_protocol"),
        "snmpv3_auth_password": d.get("snmpv3_auth_password"),
        "snmpv3_priv_protocol": d.get("snmpv3_priv_protocol"),
        "snmpv3_priv_password": d.get("snmpv3_priv_password"),
        "snmpv3_security_level": d.get("snmpv3_security_level", "authPriv"),
    } for d in devices]


@router.post(f"/{C}/ln")
@router.post("/connector/lldp-neighbors")
async def connector_lldp_report(request: Request):
    """Receive LLDP neighbor data from the connector."""
    client_data = await verify_connector_request(request)
    body = await request.json()
    check_nosql_injection(body)
    client_id = client_data["id"]
    neighbors = body.get("neighbors", [])
    now_iso = datetime.now(timezone.utc).isoformat()

    # Clear old LLDP data for this client and re-insert fresh
    await db.lldp_neighbors.delete_many({"client_id": client_id})

    if neighbors:
        docs = []
        for n in neighbors:
            docs.append({
                "client_id": client_id,
                "local_ip": sanitize_string(n.get("local_ip", ""), 64),
                "local_port_id": sanitize_string(n.get("local_port_id", ""), 128),
                "local_port_desc": sanitize_string(n.get("local_port_desc", ""), 256),
                "remote_ip": sanitize_string(n.get("remote_ip", ""), 64),
                "remote_sys_name": sanitize_string(n.get("remote_sys_name", ""), 256),
                "remote_port_id": sanitize_string(n.get("remote_port_id", ""), 128),
                "remote_port_desc": sanitize_string(n.get("remote_port_desc", ""), 256),
                "remote_sys_desc": sanitize_string(n.get("remote_sys_desc", ""), 512),
                "remote_chassis_id": sanitize_string(n.get("remote_chassis_id", ""), 128),
                "updated_at": now_iso,
            })
        await db.lldp_neighbors.insert_many(docs)

    logger.info(f"LLDP neighbors updated for {client_id}: {len(neighbors)} entries")
    return {"status": "ok", "neighbors_stored": len(neighbors)}


@router.post(f"/{C}/nd")
@router.post("/connector/network-discovery")
async def connector_network_discovery(request: Request):
    """Receive MAC tables, port speeds and device MACs for topology reconstruction."""
    client_data = await verify_connector_request(request)
    body = await request.json()
    check_nosql_injection(body)
    client_id = client_data["id"]
    now_iso = datetime.now(timezone.utc).isoformat()

    mac_tables = body.get("mac_tables", [])
    port_speeds = body.get("port_speeds", [])
    device_macs = body.get("device_macs", [])

    # Store discovery data (replace old data for this client)
    await db.network_discovery.delete_many({"client_id": client_id})
    if mac_tables or port_speeds or device_macs:
        await db.network_discovery.insert_one({
            "client_id": client_id,
            "mac_tables": mac_tables,
            "port_speeds": port_speeds,
            "device_macs": device_macs,
            "updated_at": now_iso,
        })

    # Build MAC -> IP mapping from device_macs and managed devices
    device_mac_map = {}  # MAC -> IP mapping
    managed_ips = set()
    for dm in device_macs:
        ip = dm.get("ip", "")
        if ip:
            managed_ips.add(ip)
        for mac in dm.get("macs", []):
            if mac:
                device_mac_map[mac.upper()] = ip

    # Also build IP -> name mapping from managed devices
    managed_devices = await db.device_poll_status.find(
        {"client_id": client_id}, {"_id": 0, "device_ip": 1, "device_name": 1}
    ).to_list(500)
    managed_ip_names = {d["device_ip"]: d.get("device_name", "") for d in managed_devices}
    managed_ips.update(managed_ip_names.keys())

    # Build inferred connections AND discovered endpoints from MAC tables
    inferred_connections = []
    discovered_endpoints = []

    for mt in mac_tables:
        switch_ip = mt.get("switch_ip", "")
        for entry in mt.get("entries", []):
            mac = entry.get("mac", "").upper()
            port = entry.get("port", 0)
            resolved_ip = device_mac_map.get(mac, "")
            vlan = entry.get("vlan", "")

            if resolved_ip and resolved_ip != switch_ip:
                # Known device: create connection
                inferred_connections.append({
                    "from_ip": switch_ip,
                    "from_port": port,
                    "to_ip": resolved_ip,
                    "source": "mac_table",
                })
            # Store ALL MAC entries as discovered endpoints
            discovered_endpoints.append({
                "client_id": client_id,
                "switch_ip": switch_ip,
                "port": port,
                "mac": mac,
                "ip": resolved_ip or entry.get("ip", ""),
                "vlan": vlan,
                "hostname": entry.get("hostname", ""),
                "is_managed": resolved_ip in managed_ips,
                "updated_at": now_iso,
            })

    # Store inferred connections
    await db.mac_connections.delete_many({"client_id": client_id})
    if inferred_connections:
        for conn in inferred_connections:
            conn["client_id"] = client_id
            conn["updated_at"] = now_iso
        await db.mac_connections.insert_many(inferred_connections)

    # Store ALL discovered endpoints (for full tree view)
    await db.discovered_endpoints.delete_many({"client_id": client_id})
    if discovered_endpoints:
        await db.discovered_endpoints.insert_many(discovered_endpoints)

    # Store high-speed port info
    await db.port_speeds.delete_many({"client_id": client_id})
    if port_speeds:
        for ps in port_speeds:
            ps["client_id"] = client_id
            ps["updated_at"] = now_iso
        await db.port_speeds.insert_many(port_speeds)

    total_mac = sum(len(mt.get("entries", [])) for mt in mac_tables)
    logger.info(f"Network discovery for {client_id}: {total_mac} MAC entries, {len(inferred_connections)} connections, {len(discovered_endpoints)} endpoints, {len(port_speeds)} speed reports")
    return {
        "status": "ok",
        "mac_entries": total_mac,
        "inferred_connections": len(inferred_connections),
        "discovered_endpoints": len(discovered_endpoints),
        "port_speed_reports": len(port_speeds),
    }
