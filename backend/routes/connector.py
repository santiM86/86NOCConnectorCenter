"""Connector endpoints: heartbeat, auto-update, device management.
Security: HMAC-SHA256, Anti-Replay, Obfuscated paths, TLS 1.2+
"""
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse, Response
import uuid
import shutil
import logging
import re
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
from alert_filter import invalidate_silence_cache, insert_alert_if_emit
from device_classifier import classify_device_type

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["connector"])

# Obfuscated base path for connector-only endpoints
C = CONNECTOR_PATH  # e.g. "c7x9"


# ==================== AUTO-DETECT WEB UI ====================

# Porte che di sicuro ospitano una management UI, ordine di preferenza
# (porta, scheme, peso) — peso più alto = preferita
_WEB_UI_PORT_PREFERENCE = [
    (5001, "https", 110),   # Synology DSM HTTPS
    (8443, "https", 100),   # UniFi / vari HTTPS alternativo
    (4443, "https",  95),   # alt HTTPS
    (443,  "https",  90),   # HTTPS standard
    (8006, "https",  88),   # Proxmox
    (17990,"https",  85),   # iLO XMLssl
    (5000, "http",   80),   # Synology DSM HTTP
    (8088, "https",  78),   # QNAP secondary
    (8080, "http",   75),   # HTTP alt
    (8000, "http",   72),   # HTTP alt
    (10000,"https",  70),   # Webmin
    (8888, "http",   68),
    (9090, "http",   65),
    (81,   "http",   62),   # TrueNAS
    (80,   "http",   60),   # HTTP standard
    (3000, "http",   55),   # AdGuard / Grafana
    (19999,"http",   50),   # Netdata
    (17988,"http",   45),   # iLO XMLagent
]

_WEB_UI_PORT_WEIGHT = {p[0]: (p[1], p[2]) for p in _WEB_UI_PORT_PREFERENCE}


async def _auto_detect_web_ui(client_id: str, dev: dict) -> None:
    """Promote best open_ports/http_details to managed_devices.web_console_*
    when the device has NO explicit manual override and NO profile-based config.

    Priority chain (highest wins):
      1. managed_devices.web_console_port set BY USER (user_configured=true) — do not touch
      2. managed_devices.web_console_port set by profile — keep but overlay detected_port
      3. best port from open_ports with http_details.status 2xx/3xx — promote to web_console_*
    """
    device_ip = dev.get("device_ip")
    if not device_ip:
        return
    open_ports = dev.get("open_ports") or []
    http_details = dev.get("http_details") or {}
    if not open_ports:
        return

    # Compute best candidate port
    best_port = None
    best_scheme = None
    best_weight = -1
    best_title = ""
    status_code = 0
    try:
        http_status = int(http_details.get("status_code") or http_details.get("status") or 0)
        status_code = http_status
    except (ValueError, TypeError):
        http_status = 0
    http_title = (http_details.get("title") or "").strip()

    for entry in open_ports:
        if not isinstance(entry, dict):
            continue
        try:
            p = int(entry.get("port") or 0)
        except (ValueError, TypeError):
            continue
        if p <= 0:
            continue
        scheme, weight = _WEB_UI_PORT_WEIGHT.get(p, (None, 0))
        if not scheme:
            continue
        # Extra boost if this port responded HTTP 2xx/3xx
        if 200 <= http_status < 400 and http_title:
            # http_details refers to the port the connector actually probed (first open)
            weight += 20
        if weight > best_weight:
            best_weight = weight
            best_port = p
            best_scheme = scheme
            best_title = http_title if (200 <= http_status < 400) else ""

    if not best_port:
        return

    # Fetch current managed_devices to decide if we should overwrite
    existing = await db.managed_devices.find_one(
        {"ip": device_ip, "client_id": client_id},
        {"_id": 0, "web_console_port": 1, "web_console_user_configured": 1, "profile_key": 1},
    )
    if existing and existing.get("web_console_user_configured"):
        # Admin cliccò esplicitamente → non sovrascrivere, ma salva detected per UI
        await db.device_poll_status.update_one(
            {"client_id": client_id, "device_ip": device_ip},
            {"$set": {
                "detected_web_console_port": best_port,
                "detected_web_console_scheme": best_scheme,
                "detected_web_console_title": best_title,
                "detected_web_console_confidence": min(100, best_weight),
                "detected_at": datetime.now(timezone.utc).isoformat(),
            }}
        )
        return

    # Only write if different from existing (avoid unnecessary updates)
    patch = {
        "detected_web_console_port": best_port,
        "detected_web_console_scheme": best_scheme,
        "detected_web_console_title": best_title,
        "detected_at": datetime.now(timezone.utc).isoformat(),
    }
    # If no explicit managed record OR no explicit port set → promote
    has_strong_evidence = bool(status_code and 200 <= status_code < 400 and best_title)
    should_upsert = not existing and has_strong_evidence
    if not existing or not existing.get("web_console_port") or should_upsert:
        await db.managed_devices.update_one(
            {"ip": device_ip, "client_id": client_id},
            {"$set": {
                "ip": device_ip,
                "client_id": client_id,
                "name": dev.get("device_name") or device_ip,
                "web_console_port": best_port,
                "web_console_scheme": best_scheme,
                "web_console_url": f"{best_scheme}://{device_ip}:{best_port}/",
                "web_console_title": best_title or None,
                "web_console_status_code": status_code or None,
                "web_console_working": bool(status_code and 200 <= status_code < 400),
                "web_console_auto_detected": True,
                "web_console_last_tested": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )
        patch["promoted"] = True

    await db.device_poll_status.update_one(
        {"client_id": client_id, "device_ip": device_ip},
        {"$set": patch}
    )




@router.post(f"/{C}/hb")
@router.post("/connector/sync-active-devices")
async def connector_sync_active_devices(request: Request):
    """Sync inversa connector-auth: il connector invia via HMAC la lista dei device
    ATTUALMENTE configurati sul connector. Il Center rimuove quelli con source=connector
    non presenti nella lista. Chiamato automaticamente dal PowerShell ad ogni heartbeat
    (v3.5.27+) per tenere il Center allineato quando l'admin rimuove device dalla tray.

    Body: { active_ips: ["10.x.x.x", ...], dry_run: false, source: "connector_heartbeat" }
    Auth: HMAC connector (non user JWT)
    """
    client_data = await verify_connector_request(request)
    client_id = client_data["id"]
    body = await request.json()
    active_ips = body.get("active_ips") or []
    if not isinstance(active_ips, list):
        return {"ok": False, "error": "active_ips must be list"}
    active_set = {str(ip).strip() for ip in active_ips if ip}
    dry_run = bool(body.get("dry_run", False))

    if len(active_set) == 0:
        # Safety: rifiuta liste vuote per evitare wipe accidentale se il connector
        # manda devices=[] durante un bootstrap. L'admin puo` usare il pulsante UI manuale.
        return {"ok": False, "error": "empty_active_ips_rejected_for_safety"}

    to_remove = []
    ip_seen = set()

    async for d in db.managed_devices.find(
        {"client_id": client_id},
        {"_id": 0, "id": 1, "ip": 1, "name": 1, "source": 1, "alerts_silenced": 1},
    ):
        ip = d.get("ip")
        if not ip or ip in ip_seen:
            continue
        # Proteggi device manuali (source != connector) e silenziati
        if d.get("source") and d.get("source") != "connector":
            continue
        if d.get("alerts_silenced"):
            continue
        if ip not in active_set:
            to_remove.append({"id": d.get("id"), "ip": ip, "name": d.get("name")})
            ip_seen.add(ip)

    async for p in db.device_poll_status.find(
        {"client_id": client_id},
        {"_id": 0, "device_ip": 1, "device_name": 1},
    ):
        ip = p.get("device_ip")
        if not ip or ip in ip_seen:
            continue
        if ip not in active_set:
            to_remove.append({"id": None, "ip": ip, "name": p.get("device_name")})
            ip_seen.add(ip)

    if dry_run:
        return {"ok": True, "dry_run": True, "would_remove_count": len(to_remove), "would_remove": to_remove}

    deleted = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    for d in to_remove:
        ip = d["ip"]
        await db.managed_devices.delete_many({"client_id": client_id, "ip": ip, "source": {"$ne": "manual"}})
        await db.device_poll_status.delete_many({"client_id": client_id, "device_ip": ip})
        try:
            await db.alerts.update_many(
                {"client_id": client_id, "device_ip": ip, "status": {"$ne": "resolved"}},
                {"$set": {"status": "resolved", "resolved_at": now_iso,
                           "resolved_by_system": True,
                           "resolution_note": "Device rimosso dal connector (auto-sync)"}}
            )
        except Exception:
            pass
        deleted += 1

    return {"ok": True, "removed_count": deleted, "active_ips_received": len(active_set)}


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
            response["filename"] = update_info["filename"]  # v3.6.16 fix
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
    # Inject dynamic allowed ports (admin configurable via UI /connector/settings)
    try:
        settings_doc = await db.connector_settings.find_one({"key": "allowed_ports_extra"}, {"_id": 0})
        if settings_doc and isinstance(settings_doc.get("value"), list):
            ports_clean = []
            for p in settings_doc["value"]:
                try:
                    pi = int(p)
                    if 1 <= pi <= 65535:
                        ports_clean.append(pi)
                except (ValueError, TypeError):
                    continue
            response["allowed_ports_extra"] = ports_clean
    except Exception:
        pass
    # === "Applica ora" — refresh-requested flag ===
    # L'admin clicca "Applica ora" nel Device Edit Modal/altre azioni → setta
    # refresh_requested=true nella doc connector_status. Al prossimo heartbeat
    # (ogni 30s) restituiamo refresh_now=true al connector e resettiamo il flag.
    # Il connector al ricevimento di refresh_now esegue subito Fetch-DevicesFromNOC
    # invece di aspettare il normale ciclo (ogni 10 cicli di poll, ~10 min).
    if existing and existing.get("refresh_requested"):
        response["refresh_now"] = True
        await db.connector_status.update_one(
            {"client_id": client_data["id"]},
            {"$unset": {"refresh_requested": ""}, "$set": {"refresh_fulfilled_at": datetime.now(timezone.utc).isoformat()}}
        )
    return response


@router.post("/connector/{client_id}/request-refresh")
async def connector_request_refresh(client_id: str, current_user: dict = Depends(get_current_user)):
    """
    Forza il connector del cliente {client_id} a rifare subito il fetch-devices
    al prossimo heartbeat (max ~30 secondi di attesa invece di ~10 minuti).
    Usato quando l'admin cambia community/monitor-type/profilo e vuole che il
    connector applichi le modifiche immediatamente senza dover accedere al server.
    """
    # Verifica che il client esista
    client = await db.clients.find_one({"id": client_id}, {"_id": 0, "id": 1, "name": 1})
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    # Setta il flag nella doc connector_status (upsert se il connector non ha ancora
    # fatto il primo heartbeat — sarà consumato non appena si connette)
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.connector_status.update_one(
        {"client_id": client_id},
        {"$set": {
            "refresh_requested": True,
            "refresh_requested_at": now_iso,
            "refresh_requested_by": current_user.get("email"),
        }},
        upsert=True,
    )
    await audit_logger.log(
        AuditAction.UPDATE_CLIENT,
        user_id=current_user["id"], user_email=current_user["email"],
        resource_type="client", resource_id=client_id,
        details={"action": "request_refresh", "client_name": client.get("name")},
    )
    return {
        "status": "ok",
        "message": f"Richiesta refresh inviata al connector di '{client.get('name')}'. Sarà applicata entro 30 secondi.",
    }



@router.post(f"/{C}/md")
@router.post("/connector/managed-devices")
async def connector_managed_devices(request: Request):
    """Return the list of managed devices for this connector's client.
    Now enriched with `vendor_snmp_targets` — gli OID vendor-specific da pollare
    per device con profile_key (Synology, APC, Fortinet, ecc.).
    """
    client_data = await verify_connector_request(request)
    devices = await db.managed_devices.find(
        {"client_id": client_data["id"]}, {"_id": 0}
    ).to_list(500)
    # Enrich with vendor-specific OID targets (derivati dal profilo)
    try:
        from device_profiles import get_profile
        for d in devices:
            pk = d.get("profile_key")
            if not pk:
                continue
            profile = get_profile(pk)
            if not profile:
                continue
            oids = profile.get("oids") or {}
            # Separa scalari (singoli) da table-walks (prefix OIDs senza .0)
            scalars = {}
            tables = {}
            for name, oid in oids.items():
                if not oid or not isinstance(oid, str):
                    continue
                # Sistema OID: STANDARD MIB-II già letto dal connector base, skippa
                if name in {"sysDescr", "sysObjectID", "sysUpTime", "sysContact", "sysName", "sysLocation", "ifNumber", "ifDescr", "ifOperStatus", "ifInOctets", "ifOutOctets"}:
                    continue
                # Termina con .0 → scalare; altrimenti → table walk
                if oid.endswith(".0"):
                    scalars[name] = oid
                else:
                    tables[name] = oid
            if scalars or tables:
                d["vendor_snmp_targets"] = {
                    "profile_key": pk,
                    "vendor": profile.get("vendor"),
                    "scalars": scalars,
                    "tables": tables,
                    "poll_interval_seconds": profile.get("polling_interval_seconds", 120),
                }
                # Expose thresholds so connector can pre-filter (opzionale — il center ricalcola)
                d["profile_thresholds"] = profile.get("thresholds") or {}
    except Exception as e:
        logger.warning(f"Vendor OID enrichment failed: {e}")
    return {"devices": devices}


@router.post("/connector/web-ui-detected")
async def connector_web_ui_detected(request: Request):
    """Called by tray app when user clicks "Apri Web UI" and the device responds.
    Registers/updates the managed_device with web_console_* fields so the UI and
    the Web Console Enterprise can use the detected URL immediately.
    Simple X-API-Key auth (no HMAC) — action is user-initiated via tray.
    """
    client_data = await validate_api_key(request)
    client_id = client_data["id"]
    body = await request.json()
    check_nosql_injection(body)
    device_ip = sanitize_string(str(body.get("device_ip", "")).strip(), 64)
    port = int(body.get("port") or 0)
    scheme = sanitize_string(str(body.get("scheme", "http")).strip().lower(), 8)
    title = sanitize_string(str(body.get("title", "")).strip(), 256)
    status_code = int(body.get("status_code") or 0)
    url = sanitize_string(str(body.get("url", "")).strip(), 512)
    name_from_tray = sanitize_string(str(body.get("name", "")).strip(), 128)
    community = sanitize_string(str(body.get("community", "public")).strip(), 128)
    working = bool(body.get("working", True))
    if not device_ip or not port or scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="device_ip, port, scheme (http|https) required")

    web_fields = {
        "web_console_url": url or f"{scheme}://{device_ip}:{port}/",
        "web_console_port": port,
        "web_console_scheme": scheme,
        "web_console_title": title,
        "web_console_status_code": status_code,
        "web_console_working": working,
        "web_console_last_tested": datetime.now(timezone.utc).isoformat(),
    }
    existing = await db.managed_devices.find_one({"client_id": client_id, "ip": device_ip})
    if existing:
        await db.managed_devices.update_one(
            {"client_id": client_id, "ip": device_ip},
            {"$set": web_fields},
        )
        action = "updated"
    else:
        doc = {
            "id": str(uuid.uuid4()), "client_id": client_id,
            "ip": device_ip, "community": community,
            "name": name_from_tray or device_ip,
            "monitor_type": "http", "device_type": "network",
            "http_port": port,
            "snmp_version": "v2c",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_by": f"connector-tray:{client_data.get('name', 'unknown')}",
            **web_fields,
        }
        await db.managed_devices.insert_one(doc)
        # remove from deleted_devices blacklist if present
        await db.deleted_devices.delete_many({"client_id": client_id, "device_ip": device_ip})
        action = "created"
    logger.info(f"[WEB-UI-DETECT] {action} {device_ip}:{port} via tray (client={client_data.get('name')}) working={working}")
    return {"status": "ok", "action": action, "device_ip": device_ip, "web_console_url": web_fields["web_console_url"]}



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
    # Block force-update on offline connectors: otherwise the order gets stuck in queued forever
    last_seen_raw = connector.get("last_seen")
    is_offline = True
    if last_seen_raw:
        try:
            last_seen = datetime.fromisoformat(last_seen_raw.replace("Z", "+00:00"))
            elapsed = (datetime.now(timezone.utc) - last_seen).total_seconds()
            is_offline = elapsed > 180  # 3 minutes threshold
        except Exception:
            pass
    if is_offline:
        raise HTTPException(
            status_code=409,
            detail=f"Il connector {connector.get('hostname', client_id)} e' OFFLINE e non puo' ricevere l'ordine di aggiornamento. Attendi che torni online oppure aggiornalo manualmente sul server."
        )
    update_info = await db.connector_updates.find_one({"active": True}, {"_id": 0})
    if not update_info:
        raise HTTPException(status_code=400, detail="Nessun aggiornamento disponibile")
    if not is_newer_version(update_info["version"], connector.get("connector_version", "0.0.0")):
        raise HTTPException(status_code=400, detail="Il connector e' gia' alla versione piu' recente")
    await db.connector_status.update_one(
        {"client_id": client_id},
        {"$set": {
            "force_update": True,
            "update_status": "queued",
            "update_progress": 1,
            "update_message": f"Aggiornamento forzato a v{update_info['version']} — in attesa heartbeat",
            "update_timestamp": datetime.now(timezone.utc).isoformat(),
        }}
    )
    return {
        "status": "ok",
        "message": f"Aggiornamento forzato per {connector.get('hostname', client_id)}. Verra' applicato al prossimo heartbeat (~60s).",
        "target_version": update_info["version"]
    }


@router.get("/connector/identify")
async def connector_identify(request: Request):
    """Auto-discovery del client_id tramite X-API-Key.

    Uso: quando il connector ha l'API key ma non il client_id (es. wizard installer
    pre-v3.5.16 che non chiedeva client_id), questo endpoint permette di ricavarlo
    autonomamente senza che l'admin debba andare nel Center UI a copiarlo manualmente.

    Richiede solo X-API-Key header (no HMAC). Sicuro perche' l'API key stessa gia'
    autentica univocamente il client nel DB.
    """
    client_data = await validate_api_key(request)
    return {
        "client_id": client_data["id"],
        "client_name": client_data.get("name", ""),
        "status": "ok",
    }


@router.get("/connector/by-hostname/{hostname}")
async def connector_by_hostname(hostname: str, request: Request):
    """Preflight wizard v3.5.17: verifica se un connector con quell'hostname è già
    registrato per il cliente (evita doppioni). Richiede X-API-Key."""
    client_data = await validate_api_key(request)
    hostname = (hostname or "").strip()[:256]
    if not hostname:
        return {"exists": False}
    doc = await db.connector_status.find_one(
        {"client_id": client_data["id"], "hostname": hostname},
        {"_id": 0, "hostname": 1, "connector_version": 1, "last_heartbeat": 1, "connector_ip": 1},
    )
    if not doc:
        return {"exists": False}
    return {
        "exists": True,
        "hostname": doc.get("hostname", ""),
        "version": doc.get("connector_version", ""),
        "last_heartbeat": doc.get("last_heartbeat", ""),
        "connector_ip": doc.get("connector_ip", ""),
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
        "filename": update_info["filename"],  # v3.6.16 fix: update_check.ps1 legge $checkResponse.filename
        "download_url": f"/api/connector/download/{update_info['filename']}",
        "changelog": update_info.get("changelog", ""),
        "published_at": update_info.get("published_at", ""),
        "file_size": update_info.get("file_size", 0)
    }


@router.get("/connector/download/{filename}")
async def connector_download(filename: str, request: Request):
    # Allow either (1) a valid connector API key, or (2) an admin JWT — admins can
    # grab the latest ZIP manually from the browser, connectors pull via API key.
    client_data = None
    try:
        client_data = await verify_connector_request(request)
    except Exception:
        pass
    if not client_data:
        # Try admin JWT (Authorization: Bearer ...)
        auth_hdr = request.headers.get("Authorization") or request.headers.get("authorization") or ""
        token_hdr = None
        if auth_hdr.lower().startswith("bearer "):
            token_hdr = auth_hdr.split(" ", 1)[1]
        # Allow also ?token=<jwt> for direct browser download (anchor href)
        if not token_hdr:
            token_hdr = request.query_params.get("token")
        if token_hdr:
            try:
                import jwt as _jwt
                from deps import JWT_SECRET, JWT_ALGORITHM
                payload = _jwt.decode(token_hdr, JWT_SECRET, algorithms=[JWT_ALGORITHM])
                user_id = payload.get("user_id")
                if user_id:
                    user = await db.users.find_one({"id": user_id}, {"_id": 0, "role": 1, "email": 1})
                    if user and user.get("role") in ("admin", "superadmin", "security_admin"):
                        client_data = {"_admin": True, "email": user.get("email")}
            except Exception:
                pass
    if not client_data:
        raise HTTPException(status_code=401, detail="Invalid API key or admin token required")
    filepath = CONNECTOR_STORAGE / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=str(filepath), filename=filename, media_type="application/zip")


@router.get("/connector/public-download/latest")
async def connector_public_download_latest():
    """Public download of the latest active connector ZIP. No auth required.

    Sicuro perche':
    - Lo ZIP contiene solo gli script PowerShell open (no segreti, no credenziali).
    - Le credenziali (api_key, hmac secret) sono salvate in config.json LOCALE
      del cliente (in ProgramData), mai distribuite nel binario.
    - Permette al cliente di fare bootstrap manuale o disaster recovery senza
      conoscere il filename esatto.
    """
    update_info = await db.connector_updates.find_one({"active": True}, {"_id": 0})
    if not update_info:
        raise HTTPException(status_code=404, detail="Nessun aggiornamento attivo")
    filename = update_info.get("filename", "")
    if not filename or not re.match(r"^86NocConnector_v[\d\.]+\.zip$", filename):
        raise HTTPException(status_code=500, detail="Filename non valido")
    filepath = CONNECTOR_STORAGE / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="File ZIP non trovato sul server")
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
    try:
        content = await file.read()
        with open(filepath, "wb") as f:
            f.write(content)
    except Exception as e:
        import logging
        logging.error(f"Errore scrittura ZIP {filepath}: {e}")
        raise HTTPException(status_code=500, detail=f"Errore scrittura ZIP: {e}")

    await db.connector_updates.update_many({}, {"$set": {"active": False}})
    update_doc = {
        "version": version, "filename": safe_filename, "changelog": changelog,
        "file_size": len(content), "active": True,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "uploaded_by": current_user.get("name", "admin")
    }
    await db.connector_updates.insert_one(update_doc)

    # Copy ZIP to public downloads folder(s) so it can be downloaded via HTTPS
    # Some environments (build-time minified React) don't keep /app/frontend/public,
    # so we try multiple locations and ignore failures (non-fatal for the upload itself).
    import logging
    for dest in [
        Path("/app/frontend/public/86NocConnector.zip"),
        Path("/app/frontend/public/downloads") / safe_filename,
        Path("/app/frontend/build/86NocConnector.zip"),
        Path("/app/frontend/build/downloads") / safe_filename,
    ]:
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(filepath, dest)
        except Exception as e:
            logging.warning(f"Public copy skipped for {dest}: {e}")

    return {
        "status": "ok", "version": version, "filename": safe_filename,
        "connectors_will_update": "I connettori si aggiorneranno automaticamente entro 5 minuti (oppure immediatamente cliccando Aggiorna)"
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

    # Load client thresholds with defaults (global fallback)
    th = await db.alert_thresholds.find_one({"client_id": client_id}, {"_id": 0}) or {}
    cpu_crit = th.get("cpu_critical_pct", 95)
    cpu_warn = th.get("cpu_warning_pct", 80)
    mem_crit = th.get("memory_critical_pct", 95)
    mem_warn = th.get("memory_warning_pct", 85)
    temp_crit = 75  # fallback hardcoded
    temp_warn = 65
    offline_after_min = th.get("offline_alert_after_min", 5)

    # FASE A: Override con le soglie del profilo vendor se disponibili
    profile_key = dev.get("profile_key") or (prev_status or {}).get("profile_key")
    if not profile_key:
        md = await db.managed_devices.find_one(
            {"client_id": client_id, "ip": device_ip},
            {"_id": 0, "profile_key": 1}
        ) or {}
        profile_key = md.get("profile_key")
    profile_thresholds = {}
    if profile_key:
        try:
            from device_profiles import get_profile
            prof = get_profile(profile_key)
            if prof:
                profile_thresholds = prof.get("thresholds") or {}
                # Override only if profile specifies (profile wins on per-device tuning)
                if "cpu_crit_pct" in profile_thresholds:
                    cpu_crit = profile_thresholds["cpu_crit_pct"]
                if "cpu_warn_pct" in profile_thresholds:
                    cpu_warn = profile_thresholds["cpu_warn_pct"]
                if "mem_crit_pct" in profile_thresholds:
                    mem_crit = profile_thresholds["mem_crit_pct"]
                if "mem_warn_pct" in profile_thresholds:
                    mem_warn = profile_thresholds["mem_warn_pct"]
                if "temp_crit_c" in profile_thresholds:
                    temp_crit = profile_thresholds["temp_crit_c"]
                if "temp_warn_c" in profile_thresholds:
                    temp_warn = profile_thresholds["temp_warn_c"]
        except Exception:
            pass

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

    # --- FASE B: Vendor-specific metrics evaluation
    # Alert sui valori critici anche se il profilo non è associato (hard-coded fallback thresholds).
    vendor_metrics = dev.get("vendor_metrics") or {}
    if vendor_metrics:
        # Synology RAID / Disk / Temperature
        # --- Synology: disk / RAID status
        raid_status = vendor_metrics.get("raidStatus")
        if raid_status is not None:
            # Synology convention: 1=Normal, 2=Repairing, 3=Migrating, 4=Expanding, 5=Deleting,
            # 6=Creating, 7=RaidSyncing, 8=RaidParityChecking, 9=RaidAssembling,
            # 10=Canceling, 11=Degraded, 12=Crashed
            raid_code = int(raid_status) if isinstance(raid_status, (int, float)) else -1
            if raid_code == 11:
                alerts_to_create.append({
                    "severity": "high",
                    "title": f"RAID DEGRADED: {device_name}",
                    "message": f"Volume RAID su {device_name} ({device_ip}) in stato Degraded (disco guasto). Azione: controllare lo stato dei dischi e sostituire quello rotto.",
                    "source_type": "vendor_raid_degraded",
                })
            elif raid_code == 12:
                alerts_to_create.append({
                    "severity": "critical",
                    "title": f"RAID CRASHED: {device_name}",
                    "message": f"Volume RAID su {device_name} ({device_ip}) in stato Crashed (perdita dati possibile). Intervento URGENTE richiesto.",
                    "source_type": "vendor_raid_crashed",
                })

        # --- Synology: disk temperature (table walk: diskTemperature)
        disk_temp_crit = profile_thresholds.get("disk_temp_crit_c", 60)
        disk_temp_warn = profile_thresholds.get("disk_temp_warn_c", 50)
        disk_temps = vendor_metrics.get("diskTemperature") or {}
        if isinstance(disk_temps, dict):
            for idx, t in disk_temps.items():
                try:
                    tv = float(t)
                    if tv >= disk_temp_crit:
                        alerts_to_create.append({
                            "severity": "critical",
                            "title": f"Disco {idx} temp critica ({int(tv)}°C): {device_name}",
                            "message": f"Disco {idx} di {device_name} ({device_ip}) a {tv}°C — soglia critica {disk_temp_crit}°C",
                            "source_type": "vendor_disk_temp",
                        })
                    elif tv >= disk_temp_warn:
                        alerts_to_create.append({
                            "severity": "high",
                            "title": f"Disco {idx} temp alta ({int(tv)}°C): {device_name}",
                            "message": f"Disco {idx} di {device_name} ({device_ip}) a {tv}°C — warning {disk_temp_warn}°C",
                            "source_type": "vendor_disk_temp",
                        })
                except (ValueError, TypeError):
                    pass

        # --- APC UPS: battery status (upsBatteryStatus OID enum: 1=unknown, 2=batteryNormal, 3=batteryLow, 4=batteryDepleted)
        ups_batt = vendor_metrics.get("upsBatteryStatus")
        if ups_batt is not None:
            try:
                batt_code = int(ups_batt)
                if batt_code == 3:
                    alerts_to_create.append({
                        "severity": "high",
                        "title": f"UPS batteria BASSA: {device_name}",
                        "message": f"UPS {device_name} ({device_ip}) in stato 'Battery Low'. Verificare carica e programmare test batteria.",
                        "source_type": "vendor_ups_battery_low",
                    })
                elif batt_code == 4:
                    alerts_to_create.append({
                        "severity": "critical",
                        "title": f"UPS batteria ESAURITA: {device_name}",
                        "message": f"UPS {device_name} ({device_ip}) in stato 'Battery Depleted'. Il sistema si spegnerà al prossimo blackout. Intervento IMMEDIATO.",
                        "source_type": "vendor_ups_battery_depleted",
                    })
            except (ValueError, TypeError):
                pass

        # --- APC UPS: output source (upsOutputSource: 3=normal, 4=bypass, 5=battery, 6=booster, 7=reducer)
        out_src = vendor_metrics.get("upsOutputSource")
        if out_src is not None:
            try:
                src_code = int(out_src)
                if src_code == 5:
                    alerts_to_create.append({
                        "severity": "high",
                        "title": f"UPS su BATTERIA: {device_name}",
                        "message": f"UPS {device_name} ({device_ip}) sta alimentando il carico dalla batteria (blackout o sottotensione). Runtime limitato.",
                        "source_type": "vendor_ups_on_battery",
                    })
            except (ValueError, TypeError):
                pass

        # --- APC UPS: battery charge %
        batt_pct = vendor_metrics.get("upsEstimatedChargeRemaining")
        batt_crit = profile_thresholds.get("battery_crit_pct", 20)
        batt_warn = profile_thresholds.get("battery_warn_pct", 50)
        if batt_pct is not None:
            try:
                pct = float(batt_pct)
                if pct <= batt_crit:
                    alerts_to_create.append({
                        "severity": "critical",
                        "title": f"UPS carica critica ({int(pct)}%): {device_name}",
                        "message": f"UPS {device_name} ({device_ip}) batteria al {pct}% — soglia critica {batt_crit}%",
                        "source_type": "vendor_ups_battery_pct",
                    })
                elif pct <= batt_warn:
                    alerts_to_create.append({
                        "severity": "high",
                        "title": f"UPS carica bassa ({int(pct)}%): {device_name}",
                        "message": f"UPS {device_name} ({device_ip}) batteria al {pct}% — warning {batt_warn}%",
                        "source_type": "vendor_ups_battery_pct",
                    })
            except (ValueError, TypeError):
                pass

        # --- Fortinet: VPN tunnel down (tabella)
        vpn_tunnels = vendor_metrics.get("fgVpnTunnelStatus") or {}
        if isinstance(vpn_tunnels, dict):
            for tname, tstatus in vpn_tunnels.items():
                try:
                    tc = int(tstatus)
                    # Fortinet: 1=down, 2=up
                    if tc == 1:
                        alerts_to_create.append({
                            "severity": "high",
                            "title": f"VPN tunnel DOWN: {tname} ({device_name})",
                            "message": f"Tunnel VPN '{tname}' su Fortinet {device_name} ({device_ip}) in stato DOWN. Verifica connettività remota.",
                            "source_type": "vendor_vpn_down",
                        })
                except (ValueError, TypeError):
                    pass

        # --- Fortinet: HA cluster status (fgHaStatsSyncStatus)
        ha_sync = vendor_metrics.get("fgHaStatsSyncStatus")
        if ha_sync is not None:
            try:
                hs = int(ha_sync)
                # 0=out-of-sync, 1=in-sync
                if hs == 0:
                    alerts_to_create.append({
                        "severity": "high",
                        "title": f"HA cluster OUT-OF-SYNC: {device_name}",
                        "message": f"Fortinet {device_name} ({device_ip}) HA cluster non sincronizzato. I cambi di config non sono replicati.",
                        "source_type": "vendor_ha_out_of_sync",
                    })
            except (ValueError, TypeError):
                pass

        # --- Synology: systemStatus (1=Normal, 2=Failed)
        sys_st = vendor_metrics.get("systemStatus")
        if sys_st is not None:
            try:
                if int(sys_st) == 2:
                    alerts_to_create.append({
                        "severity": "critical",
                        "title": f"System FAILED: {device_name}",
                        "message": f"Synology {device_name} ({device_ip}) systemStatus=FAILED. Verificare log DSM.",
                        "source_type": "vendor_synology_system_failed",
                    })
            except (ValueError, TypeError):
                pass

        # --- Synology: diskStatus table (2=Init, 3=SysPart failed, 4=Crashed, 5=Failed)
        disk_statuses = vendor_metrics.get("diskStatus") or {}
        if isinstance(disk_statuses, dict):
            for idx, st in disk_statuses.items():
                try:
                    sc = int(st)
                    if sc in (4, 5):
                        alerts_to_create.append({
                            "severity": "critical",
                            "title": f"Disco {idx} {'CRASHED' if sc == 4 else 'FAILED'}: {device_name}",
                            "message": f"Disco {idx} su {device_name} ({device_ip}) in stato {sc} (4=Crashed, 5=Failed). Sostituire il disco.",
                            "source_type": "vendor_disk_failed",
                        })
                    elif sc == 3:
                        alerts_to_create.append({
                            "severity": "high",
                            "title": f"Disco {idx} SysPart Failed: {device_name}",
                            "message": f"Disco {idx} su {device_name} ({device_ip}) ha system partition corrotta. Riparazione necessaria.",
                            "source_type": "vendor_disk_syspart_failed",
                        })
                except (ValueError, TypeError):
                    pass

        # --- Generic UPS (RFC 1628): RIELLO/XANTO, CyberPower, Eaton, Socomec
        #     Riusa upsBatteryStatus, upsOutputSource, upsEstimatedChargeRemaining (già evaluated sopra)
        # --- UPS Runtime residuo
        runtime = vendor_metrics.get("upsEstimatedMinutesRemaining")
        if runtime is not None:
            try:
                rt = float(runtime)
                runtime_crit = profile_thresholds.get("runtime_min_crit", 5)
                runtime_warn = profile_thresholds.get("runtime_min_warn", 15)
                if rt <= runtime_crit:
                    alerts_to_create.append({
                        "severity": "critical",
                        "title": f"UPS runtime CRITICO ({int(rt)}min): {device_name}",
                        "message": f"UPS {device_name} ({device_ip}) residuo batteria solo {rt} min — soglia {runtime_crit} min",
                        "source_type": "vendor_ups_runtime",
                    })
                elif rt <= runtime_warn:
                    alerts_to_create.append({
                        "severity": "high",
                        "title": f"UPS runtime basso ({int(rt)}min): {device_name}",
                        "message": f"UPS {device_name} ({device_ip}) residuo batteria {rt} min — warning {runtime_warn} min",
                        "source_type": "vendor_ups_runtime",
                    })
            except (ValueError, TypeError):
                pass

        # --- UPS Output Load %
        load = vendor_metrics.get("upsOutputPercentLoad")
        if isinstance(load, dict):
            # Table: take max
            load_vals = [float(v) for v in load.values() if isinstance(v, (int, float))]
            if load_vals:
                load = max(load_vals)
        if load is not None:
            try:
                lv = float(load)
                load_crit = profile_thresholds.get("load_pct_crit", 90)
                if lv >= load_crit:
                    alerts_to_create.append({
                        "severity": "high",
                        "title": f"UPS sovraccarico ({int(lv)}%): {device_name}",
                        "message": f"UPS {device_name} ({device_ip}) carico output {lv}% — soglia {load_crit}%",
                        "source_type": "vendor_ups_overload",
                    })
            except (ValueError, TypeError):
                pass

        # --- HPE Comware switch: CPU/Memory/Temperature (tabelle indicizzate per modulo)
        # h3cEntityExtCpuUsage, h3cEntityExtMemUsage, h3cEntityExtTemperature
        cpu_warn = profile_thresholds.get("cpu_warn_pct", 70)
        cpu_crit = profile_thresholds.get("cpu_crit_pct", 90)
        mem_warn = profile_thresholds.get("mem_warn_pct", 80)
        mem_crit = profile_thresholds.get("mem_crit_pct", 95)
        temp_warn = profile_thresholds.get("temp_warn_c", 55)
        temp_crit = profile_thresholds.get("temp_crit_c", 70)

        for metric_key, label in [
            ("h3cEntityExtCpuUsage", "CPU"),
            ("cpuUtil", "CPU"),              # HP ProCurve
            ("cpuUsage", "CPU"),             # QNAP
            ("cpuUtilization", "CPU"),       # UniFi generic
            ("mtxrHlProcessorTemperature", "CPU Temp"),  # MikroTik
        ]:
            val = vendor_metrics.get(metric_key)
            if isinstance(val, dict):
                vals = [float(v) for v in val.values() if isinstance(v, (int, float))]
                if vals:
                    val = max(vals)
            if val is not None:
                try:
                    v = float(val)
                    if "Temp" in label:
                        if v >= temp_crit:
                            alerts_to_create.append({
                                "severity": "critical",
                                "title": f"{label} critica ({int(v)}°C): {device_name}",
                                "message": f"{device_name} ({device_ip}) {label} {v}°C — soglia critica {temp_crit}°C",
                                "source_type": f"vendor_{metric_key}_temp",
                            })
                        elif v >= temp_warn:
                            alerts_to_create.append({
                                "severity": "high",
                                "title": f"{label} alta ({int(v)}°C): {device_name}",
                                "message": f"{device_name} ({device_ip}) {label} {v}°C — warning {temp_warn}°C",
                                "source_type": f"vendor_{metric_key}_temp",
                            })
                    else:
                        if v >= cpu_crit:
                            alerts_to_create.append({
                                "severity": "critical",
                                "title": f"{label} {int(v)}% (critico): {device_name}",
                                "message": f"{device_name} ({device_ip}) {label} {v}% — soglia critica {cpu_crit}%",
                                "source_type": f"vendor_{metric_key}_high",
                            })
                        elif v >= cpu_warn:
                            alerts_to_create.append({
                                "severity": "high",
                                "title": f"{label} {int(v)}%: {device_name}",
                                "message": f"{device_name} ({device_ip}) {label} {v}% — warning {cpu_warn}%",
                                "source_type": f"vendor_{metric_key}_high",
                            })
                except (ValueError, TypeError):
                    pass

        # --- HPE Comware: fan + power supply state (2=fault)
        for metric_key, label in [
            ("h3cFanState", "Fan"),
            ("h3cPowerState", "Power Supply"),
            ("psuStatus", "Power Supply"),  # HP ProCurve
            ("fanStatus", "Fan"),           # HP ProCurve
            ("tempSensor", "Temp Sensor"),  # HP ProCurve
        ]:
            states = vendor_metrics.get(metric_key)
            if isinstance(states, dict):
                for idx, st in states.items():
                    try:
                        sc = int(st)
                        # Convention: 1/2=ok, 3+=fault (varies per vendor)
                        if sc in (3, 4, 5, 6):
                            alerts_to_create.append({
                                "severity": "high",
                                "title": f"{label} {idx} FAULT: {device_name}",
                                "message": f"{label} {idx} su {device_name} ({device_ip}) in stato fault (code {sc})",
                                "source_type": f"vendor_{metric_key}_fault",
                            })
                    except (ValueError, TypeError):
                        pass

        # --- MikroTik: PSU + temperature
        psu1 = vendor_metrics.get("mtxrHlPsu1Status")
        psu2 = vendor_metrics.get("mtxrHlPsu2Status")
        for psu_val, psu_name in [(psu1, "PSU1"), (psu2, "PSU2")]:
            if psu_val is not None:
                try:
                    if int(psu_val) == 0:  # MikroTik: 1=ok, 0=fault
                        alerts_to_create.append({
                            "severity": "high",
                            "title": f"{psu_name} FAULT: {device_name}",
                            "message": f"MikroTik {device_name} ({device_ip}) {psu_name} guasto",
                            "source_type": f"vendor_mikrotik_{psu_name.lower()}_fault",
                        })
                except (ValueError, TypeError):
                    pass

        mikro_temp = vendor_metrics.get("mtxrHlTemperature")
        if mikro_temp is not None:
            try:
                # MikroTik reports temperature in °C * 10 (decicelsius)
                t = float(mikro_temp) / 10 if float(mikro_temp) > 200 else float(mikro_temp)
                if t >= temp_crit:
                    alerts_to_create.append({
                        "severity": "critical",
                        "title": f"MikroTik temp critica ({int(t)}°C): {device_name}",
                        "message": f"MikroTik {device_name} ({device_ip}) temp {t}°C — soglia {temp_crit}°C",
                        "source_type": "vendor_mikrotik_temp",
                    })
            except (ValueError, TypeError):
                pass

        # --- Cisco IOS: temperature status (1=normal, 2=warning, 3=critical, 4=shutdown)
        cisco_temps = vendor_metrics.get("ciscoEnvMonTemperatureStatusValue")
        if isinstance(cisco_temps, dict):
            for idx, tstate in cisco_temps.items():
                try:
                    s = int(tstate)
                    if s >= 3:
                        alerts_to_create.append({
                            "severity": "critical" if s >= 4 else "high",
                            "title": f"Cisco temp sensor {idx} {'SHUTDOWN' if s>=4 else 'CRITICAL'}: {device_name}",
                            "message": f"Cisco {device_name} ({device_ip}) sensor {idx} stato {s} (1=normal, 3=critical, 4=shutdown)",
                            "source_type": "vendor_cisco_temp",
                        })
                except (ValueError, TypeError):
                    pass

        # --- Cisco CPU 5min
        cpu5 = vendor_metrics.get("cpmCPUTotal5min")
        if isinstance(cpu5, dict):
            vals = [float(v) for v in cpu5.values() if isinstance(v, (int, float))]
            if vals: cpu5 = max(vals)
        if cpu5 is not None:
            try:
                v = float(cpu5)
                if v >= cpu_crit:
                    alerts_to_create.append({
                        "severity": "critical",
                        "title": f"Cisco CPU 5min {int(v)}%: {device_name}",
                        "message": f"Cisco {device_name} ({device_ip}) CPU 5min avg {v}% — soglia {cpu_crit}%",
                        "source_type": "vendor_cisco_cpu",
                    })
            except (ValueError, TypeError):
                pass

        # --- QNAP SMART status (GOOD / WARNING / ERROR)
        smart_map = vendor_metrics.get("hddSMART")
        if isinstance(smart_map, dict):
            for idx, smart in smart_map.items():
                sv = str(smart).upper().strip()
                if sv == "ERROR":
                    alerts_to_create.append({
                        "severity": "critical",
                        "title": f"Disco {idx} SMART ERROR: {device_name}",
                        "message": f"QNAP {device_name} ({device_ip}) disco {idx} SMART ERROR — sostituire.",
                        "source_type": "vendor_qnap_smart",
                    })
                elif sv == "WARNING":
                    alerts_to_create.append({
                        "severity": "high",
                        "title": f"Disco {idx} SMART WARNING: {device_name}",
                        "message": f"QNAP {device_name} ({device_ip}) disco {idx} SMART WARNING — programmare sostituzione.",
                        "source_type": "vendor_qnap_smart",
                    })

        # --- Zyxel: già parziale (OID_zyxelCpuCurrent) nel polling Poll-Device
        zyxel_cpu = vendor_metrics.get("zyxelCpu5min") or vendor_metrics.get("zyxelCpuCurrent")
        if zyxel_cpu is not None:
            try:
                v = float(zyxel_cpu)
                if v >= cpu_crit:
                    alerts_to_create.append({
                        "severity": "critical",
                        "title": f"Zyxel CPU {int(v)}%: {device_name}",
                        "message": f"Zyxel {device_name} ({device_ip}) CPU {v}% — soglia {cpu_crit}%",
                        "source_type": "vendor_zyxel_cpu",
                    })
            except (ValueError, TypeError):
                pass

        zyxel_ram = vendor_metrics.get("zyxelRamUsage")
        if zyxel_ram is not None:
            try:
                v = float(zyxel_ram)
                if v >= mem_crit:
                    alerts_to_create.append({
                        "severity": "critical",
                        "title": f"Zyxel RAM {int(v)}%: {device_name}",
                        "message": f"Zyxel {device_name} ({device_ip}) RAM {v}% — soglia {mem_crit}%",
                        "source_type": "vendor_zyxel_ram",
                    })
            except (ValueError, TypeError):
                pass


    # --- Device identity change detection (sysDescr / sysName / MACs)
    # If the sysDescr or sysName of a known IP changes significantly, it may mean
    # the device was replaced, is a rogue device (ARP spoofing) or swapped hardware.
    if prev_status and prev_status.get("reachable") and reachable:
        prev_descr = (prev_status.get("sys_descr") or "").strip()
        curr_descr = (dev.get("sys_descr") or "").strip()
        prev_name = (prev_status.get("sys_name") or "").strip()
        curr_name = (dev.get("sys_name") or "").strip()

        # Alert only if both old and new values are non-empty (first population is ignored)
        if prev_descr and curr_descr and prev_descr != curr_descr:
            alerts_to_create.append({
                "severity": "critical",
                "title": f"Identità dispositivo CAMBIATA: {device_name}",
                "message": f"L'IP {device_ip} risponde con un sysDescr diverso. Prima: '{prev_descr[:100]}'. Ora: '{curr_descr[:100]}'. Possibile sostituzione HW, rogue device o ARP spoofing.",
                "source_type": "security_identity_change",
            })
        elif prev_name and curr_name and prev_name != curr_name:
            alerts_to_create.append({
                "severity": "high",
                "title": f"Hostname SNMP cambiato: {device_name}",
                "message": f"L'IP {device_ip} ha cambiato sysName da '{prev_name}' a '{curr_name}'.",
                "source_type": "security_identity_change",
            })

        # MAC address fingerprint check (from device_macs if provided)
        prev_macs = set(m.upper() for m in (prev_status.get("device_macs") or []) if m)
        curr_macs = set(m.upper() for m in (dev.get("device_macs") or []) if m)
        if prev_macs and curr_macs and not prev_macs.intersection(curr_macs):
            alerts_to_create.append({
                "severity": "critical",
                "title": f"MAC address cambiato: {device_name}",
                "message": f"Tutti i MAC address su {device_ip} sono cambiati. Prima: {', '.join(sorted(prev_macs))[:120]}. Ora: {', '.join(sorted(curr_macs))[:120]}. Possibile sostituzione dispositivo o spoofing.",
                "source_type": "security_mac_change",
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
        _conn_alert = {
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
        }
        await insert_alert_if_emit(db, _conn_alert)
        try:
            import webpush as _wp
            await _wp.notify_new_alert(db, _conn_alert)
        except Exception:
            pass


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
            "sys_name": dev.get("sys_name", ""),
            "sys_object_id": dev.get("sys_object_id", ""),
            "sys_uptime": dev.get("sys_uptime", ""),
            "device_macs": dev.get("device_macs", []),
            "http_status": dev.get("http_status", None),
            "ping_ms": dev.get("ping_ms", None),
            "cpu_usage": dev.get("cpu_usage", None),
            "memory_usage": dev.get("memory_usage", None),
            "temperature": dev.get("temperature", None),
            "device_class": dev.get("device_class", "generic"),
            "monitor_type": dev.get("monitor_type"),  # v3.6.18: persist SNMP config in poll_status
            "snmp_version": dev.get("snmp_version"),
            "snmp_community": dev.get("snmp_community") or dev.get("community"),
            "community": dev.get("community") or dev.get("snmp_community"),
            "hardware": dev.get("hardware", None),
            "firewall": dev.get("firewall", None),
            "redfish": dev.get("redfish", None),
            "ping_stats": dev.get("ping_stats", None),
            "open_ports": dev.get("open_ports", None),
            "http_details": dev.get("http_details", None),
            "vendor_metrics": dev.get("vendor_metrics", None),
            "entity_mib": dev.get("entity_mib", None),
            "primary_mac": dev.get("primary_mac", None),
            "if_aliases": dev.get("if_aliases", None),
            "arp_entries_count": len(dev.get("arp_table") or []) if dev.get("arp_table") else 0,
            "last_poll": dev.get("poll_timestamp", now_iso),
            "updated_at": now_iso
        }
        # Ingest ARP table into arp_cache collection for cross-device MAC lookup
        arp_table = dev.get("arp_table") or []
        if isinstance(arp_table, list) and arp_table:
            try:
                now_dt = datetime.now(timezone.utc)
                for entry in arp_table:
                    ip_e = (entry.get("ip") or "").strip() if isinstance(entry, dict) else ""
                    mac_e = (entry.get("mac") or "").strip().upper() if isinstance(entry, dict) else ""
                    if not ip_e or not mac_e:
                        continue
                    await db.arp_cache.update_one(
                        {"client_id": client_id, "ip": ip_e},
                        {"$set": {
                            "client_id": client_id,
                            "ip": ip_e,
                            "mac": mac_e,
                            "source_device_ip": dev.get("device_ip"),
                            "last_seen": now_dt,
                        }},
                        upsert=True,
                    )
            except Exception as e:
                logger.debug(f"ARP cache upsert failed for {dev.get('device_ip')}: {e}")
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

        # Auto-detect Web UI from open_ports scan
        # Il connector fa TCP probe + HTTP GET: se trova una porta che risponde con
        # un title/server header valido, la salviamo come "porta osservata".
        # Priorità scelta: HTTPS > HTTP, preferenza porte management note,
        # confidence = (risposta HTTP 2xx/3xx + title non vuoto).
        try:
            await _auto_detect_web_ui(client_id, dev)
        except Exception as e:
            logger.warning(f"Auto-detect web UI failed for {dev.get('device_ip')}: {e}")

        # Auto-classify new devices via Device Profile fingerprinting (non-blocking)
        # Retry policy:
        #   1. prev_status None (primo ingest)                 → match
        #   2. sys_descr cambiato                              → match
        #   3. profile_key mancante E abbiamo identificatori   → retry
        # Il caso 3 copre i device storici che erano stati ingestati prima
        # che lo SNMP funzionasse correttamente (sysObjectID/sysDescr vuoti):
        # ora che il connector raccoglie i metadati veri, riaggancia il profilo
        # automaticamente al prossimo heartbeat senza richiedere intervento manuale.
        try:
            is_new = prev_status is None
            descr_changed = prev_status and (prev_status.get("sys_descr") or "") != (dev.get("sys_descr") or "")
            already_matched = bool((prev_status or {}).get("profile_key"))
            already_matched_manual = bool(
                (prev_status or {}).get("profile_key")
                and not (prev_status or {}).get("profile_auto_matched", False)
            )
            cur_soid = dev.get("sys_object_id") or dev.get("sysObjectID")
            cur_descr = dev.get("sys_descr")
            has_identifier = bool(cur_soid) or bool(cur_descr)
            # Ri-analizza se manca il profilo e abbiamo almeno un identificatore.
            # NON sovrascriviamo un profilo impostato MANUALMENTE dall'utente.
            missing_profile_retry = (
                has_identifier and not already_matched and not already_matched_manual
            )
            if is_new or descr_changed or missing_profile_retry:
                from device_profiles import fingerprint as _fp
                matched = _fp(cur_soid, cur_descr)
                if matched:
                    snmp = matched.get("snmp") or {}
                    wc = matched.get("web_console") or {}
                    await db.device_poll_status.update_one(
                        {"client_id": client_id, "device_ip": dev["device_ip"]},
                        {"$set": {
                            "profile_key": matched["key"],
                            "vendor": matched["vendor"],
                            "family": matched["family"],
                            "profile_auto_matched": True,
                            "profile_matched_at": now_iso,
                        }}
                    )
                    # Also patch managed_devices if it exists and doesn't have an explicit profile
                    existing_md = await db.managed_devices.find_one(
                        {"ip": dev["device_ip"], "client_id": client_id},
                        {"_id": 0, "profile_key": 1}
                    )
                    if existing_md and not existing_md.get("profile_key"):
                        await db.managed_devices.update_one(
                            {"ip": dev["device_ip"], "client_id": client_id},
                            {"$set": {
                                "profile_key": matched["key"],
                                "vendor": matched["vendor"],
                                "device_type": matched["family"],
                                "snmp_port": snmp.get("port", 161),
                                "snmp_version": snmp.get("version"),
                                "web_console_port": wc.get("port"),
                                "web_console_scheme": wc.get("scheme"),
                            }}
                        )
                    reason = "new" if is_new else ("descr-changed" if descr_changed else "missing-profile-retry")
                    logger.info(f"Auto-classified {dev['device_ip']} → {matched['key']} ({matched['vendor']}) [{reason}]")
        except Exception as e:
            logger.warning(f"Profile auto-classify failed for {dev.get('device_ip')}: {e}")

        # Fallback classifier (regex hostname/sysDescr + Printer-MIB sysObjectID).
        # Si attiva solo se il fingerprint vendor-specifico sopra NON ha matchato e
        # il device ha device_type generico (network/server/iLO sbagliato/none).
        # Indispensabile per stampanti senza profilo SNMP dedicato (es. HP OfficeJet,
        # Brother MFC, Sharp MX) che altrimenti finiscono sotto "Server / iLO".
        try:
            is_new = prev_status is None
            descr_changed = prev_status and (prev_status.get("sys_descr") or "") != (dev.get("sys_descr") or "")
            if is_new or descr_changed:
                existing_md = await db.managed_devices.find_one(
                    {"ip": dev["device_ip"], "client_id": client_id},
                    {"_id": 0, "device_type": 1, "profile_key": 1, "name": 1, "model": 1},
                )
                cur_type = (existing_md or {}).get("device_type") or ""
                # Riclassifica solo se: nessun profilo applicato E type generico/sbagliato
                generic_types = {"", "network", "generic", "server", "ilo", "unknown"}
                if existing_md and not existing_md.get("profile_key") and cur_type.lower() in generic_types:
                    new_type = classify_device_type(
                        sys_descr=dev.get("sys_descr"),
                        sys_object_id=dev.get("sys_object_id") or dev.get("sysObjectID"),
                        hostname=existing_md.get("name") or dev.get("name"),
                        model=existing_md.get("model") or dev.get("model"),
                    )
                    if new_type and new_type != cur_type:
                        await db.managed_devices.update_one(
                            {"ip": dev["device_ip"], "client_id": client_id},
                            {"$set": {
                                "device_type": new_type,
                                "device_type_auto_classified_at": now_iso,
                            }},
                        )
                        logger.info(f"Reclassified {dev['device_ip']}: '{cur_type}' → '{new_type}' (regex)")
        except Exception as e:
            logger.warning(f"Regex auto-classify failed for {dev.get('device_ip')}: {e}")

        # Auto-promote managed_devices.monitor_type based on REAL poll evidence.
        # Motivazione: alla prima creazione via auto-detect Web UI il connector
        # scrive monitor_type="http" hardcoded (line ~353). Poi pollando scopre
        # che SNMP risponde (sys_descr valido, ENTITY-MIB letto, vendor_metrics
        # popolati, oppure il connector stesso invia monitor_type="snmp+http"/"snmp").
        # La tabella Dispositivi legge da managed_devices, quindi continuava a
        # mostrare "HTTP" anche se in realtà il device era pollato via SNMP+HTTP.
        # Promuovo ad "snmp+http" quando c'è evidenza forte, mai demoto.
        try:
            has_snmp_evidence = bool(
                dev.get("sys_descr") or
                dev.get("entity_mib") or
                (dev.get("vendor_metrics") and isinstance(dev.get("vendor_metrics"), dict) and len(dev["vendor_metrics"]) > 0) or
                (dev.get("cpu_usage") is not None) or
                (dev.get("memory_usage") is not None)
            )
            reported_mt = (dev.get("monitor_type") or "").lower()
            # Determina il tipo effettivo in base a evidenze e stato reported dal connector
            has_http_evidence = bool(
                (dev.get("http_status") and dev.get("http_status") < 400) or
                dev.get("http_details") or
                reported_mt in ("http", "snmp+http")
            )
            if has_snmp_evidence and has_http_evidence:
                target_mt = "snmp+http"
            elif has_snmp_evidence:
                target_mt = "snmp"
            elif has_http_evidence:
                target_mt = "http"
            else:
                target_mt = None   # non tocco se non ho evidenza

            if target_mt:
                md = await db.managed_devices.find_one(
                    {"ip": dev["device_ip"], "client_id": client_id},
                    {"_id": 0, "monitor_type": 1, "monitor_type_user_locked": 1},
                )
                if md and not md.get("monitor_type_user_locked"):
                    current_mt = (md.get("monitor_type") or "").lower()
                    # Regola non-regressione: snmp+http > snmp|http > ping
                    rank = {"": 0, "ping": 1, "http": 2, "snmp": 2, "snmp+http": 3}
                    if rank.get(target_mt, 0) > rank.get(current_mt, 0):
                        await db.managed_devices.update_one(
                            {"ip": dev["device_ip"], "client_id": client_id},
                            {"$set": {
                                "monitor_type": target_mt,
                                "monitor_type_auto_promoted": True,
                                "monitor_type_updated_at": now_iso,
                            }},
                        )
                        logger.info(
                            f"[MONITOR-TYPE-PROMOTE] {dev['device_ip']} {current_mt or '(none)'} → {target_mt} "
                            f"(snmp_evidence={has_snmp_evidence}, http_evidence={has_http_evidence})"
                        )
        except Exception as e:
            logger.warning(f"Monitor-type auto-promote failed for {dev.get('device_ip')}: {e}")

        # Generate alerts based on state transitions + thresholds
        try:
            await _check_device_thresholds(client_id, dev, prev_status)
        except Exception as e:
            logger.warning(f"Errore check soglie {dev.get('device_ip')}: {e}")

        # Time-series recording (metric_history, 30gg TTL)
        try:
            from routes.metric_history import record_metrics
            await record_metrics(client_id, dev["device_ip"], dev)
        except Exception as e:
            logger.debug(f"record_metrics skip {dev.get('device_ip')}: {e}")

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


@router.post("/connector/{client_id}/cleanup-stale-devices")
async def cleanup_stale_devices(
    client_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Self-healing cleanup dei device rimossi dal connector.

    Logica self-healing:
      1. Il connector del cliente DEVE essere ONLINE (last_seen < 5 min) — altrimenti
         risposta di sicurezza "connector_offline" e nessuna delete, per evitare di
         cancellare tutto durante una manutenzione del connector.
      2. Ogni device attivo ha `last_seen` in managed_devices aggiornato ad ogni
         poll (tipicamente < 2 min). Se un device ha `last_seen` piu` vecchio di
         `stale_threshold_minutes` (default 30) → il connector non sta piu` facendo
         polling → e` stato rimosso dalla sua config.
      3. Device MANUALI (source != connector) sono PROTETTI.
      4. Device SILENZIATI (alerts_silenced=true) sono PROTETTI comunque — non
         vengono rimossi dal cleanup automatico, per rispettare l'intento utente.

    Body:
        {
            "stale_threshold_minutes": 30,   # default
            "dry_run": true                   # default - mostra preview, NON cancella
        }
    """
    body = await request.json() if request.headers.get("content-length") else {}
    check_nosql_injection(body or {})
    threshold_min = int((body or {}).get("stale_threshold_minutes") or 30)
    dry_run = bool((body or {}).get("dry_run", True))  # sicurezza: default dry-run

    # Verifica connector online
    connector = await db.connectors.find_one({"client_id": client_id}, {"_id": 0, "last_seen": 1, "hostname": 1})
    if not connector:
        raise HTTPException(status_code=404, detail="Connector non registrato per questo cliente")
    last_seen_raw = connector.get("last_seen")
    now = datetime.now(timezone.utc)
    connector_online = False
    seconds_since_hb = None
    if last_seen_raw:
        try:
            last_seen = datetime.fromisoformat(str(last_seen_raw).replace("Z", "+00:00"))
            seconds_since_hb = (now - last_seen).total_seconds()
            connector_online = seconds_since_hb < 300  # 5 min
        except Exception:
            pass
    if not connector_online:
        return {
            "ok": False,
            "reason": "connector_offline",
            "message": f"Connector del cliente offline (ultimo heartbeat {int(seconds_since_hb or 0)}s fa). Cleanup saltato per sicurezza.",
            "connector_hostname": connector.get("hostname"),
        }

    threshold_ts = now - timedelta(minutes=threshold_min)
    candidates = []  # {id, ip, name, last_seen, reason}

    async for d in db.managed_devices.find(
        {"client_id": client_id},
        {"_id": 0, "id": 1, "ip": 1, "name": 1, "last_seen": 1, "source": 1, "alerts_silenced": 1},
    ):
        if d.get("source") and d.get("source") != "connector":
            continue  # manuale, protetto
        if d.get("alerts_silenced"):
            continue  # silenziato, protetto
        last_s = d.get("last_seen")
        if not last_s:
            continue  # mai pollato, potrebbe essere appena aggiunto — skip
        try:
            last_dt = datetime.fromisoformat(str(last_s).replace("Z", "+00:00"))
        except Exception:
            continue
        if last_dt < threshold_ts:
            candidates.append({
                "id": d.get("id"),
                "ip": d.get("ip"),
                "name": d.get("name"),
                "last_seen": last_s,
                "stale_minutes": int((now - last_dt).total_seconds() / 60),
            })

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "connector_online": True,
            "threshold_minutes": threshold_min,
            "candidates_count": len(candidates),
            "candidates": candidates,
        }

    # Delete confermato
    removed_ips = []
    for c in candidates:
        ip = c["ip"]
        if not ip:
            continue
        await db.managed_devices.delete_many({"client_id": client_id, "ip": ip})
        await db.device_poll_status.delete_many({"client_id": client_id, "device_ip": ip})
        try:
            await db.alerts.update_many(
                {"client_id": client_id, "device_ip": ip, "status": {"$ne": "resolved"}},
                {"$set": {"status": "resolved", "resolved_at": now.isoformat(),
                           "resolved_by_system": True,
                           "resolution_note": f"Device stale {c['stale_minutes']}min - rimosso da cleanup"}}
            )
        except Exception:
            pass
        removed_ips.append(ip)

    audit_logger and await audit_logger.log(
        AuditAction.DELETE_DEVICE,
        user_id=(current_user or {}).get("id"),
        user_email=(current_user or {}).get("email"),
        resource_type="bulk_device",
        resource_id=client_id,
        details={"client_id": client_id, "removed_count": len(removed_ips), "removed_ips": removed_ips,
                 "threshold_minutes": threshold_min, "cleanup_type": "stale_auto"},
    )
    return {
        "ok": True,
        "removed_count": len(removed_ips),
        "removed": candidates,
        "threshold_minutes": threshold_min,
    }


@router.post("/connector/{client_id}/sync-active-devices")
async def sync_active_devices(
    client_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Sincronizzazione inversa Center ← Connector: l'admin (o il connector stesso)
    fornisce la lista di IP/hostname dei device ATTUALMENTE configurati sul connector.
    Il Center rimuove TUTTI i device di questo cliente con source='connector' che NON
    sono nella lista → cosi` i device deselezionati/rimossi dalla UI del connector
    spariscono anche dal Center, evitando "zombie offline" che restano per sempre.

    Body:
        {
            "active_ips": ["10.100.61.220", "10.100.61.34", ...],
            "dry_run": false   # opzionale, default false → se true solo preview
        }

    I device MANUALI (aggiunti dall'admin via UI, non dal connector) sono PROTETTI e
    non vengono mai rimossi, anche se mancano dalla lista.
    """
    body = await request.json()
    check_nosql_injection(body)
    active_ips = body.get("active_ips") or []
    if not isinstance(active_ips, list):
        raise HTTPException(status_code=400, detail="active_ips deve essere una lista")
    active_set = {str(ip).strip() for ip in active_ips if ip}
    dry_run = bool(body.get("dry_run", False))

    # Collect candidates from all 3 collections (managed_devices, device_poll_status).
    # db.devices = manualmente aggiunti → SEMPRE protetti (no delete).
    to_remove = []  # list of {id, ip, source_colls}
    ip_seen = set()

    async for d in db.managed_devices.find(
        {"client_id": client_id, "source": "connector"},
        {"_id": 0, "id": 1, "ip": 1, "name": 1},
    ):
        ip = d.get("ip")
        if not ip or ip in ip_seen:
            continue
        if ip not in active_set:
            to_remove.append({"id": d.get("id"), "ip": ip, "name": d.get("name"), "source_collections": ["managed_devices"]})
            ip_seen.add(ip)

    async for p in db.device_poll_status.find(
        {"client_id": client_id},
        {"_id": 0, "device_ip": 1, "device_name": 1},
    ):
        ip = p.get("device_ip")
        if not ip or ip in ip_seen:
            continue
        if ip not in active_set:
            to_remove.append({"id": None, "ip": ip, "name": p.get("device_name"), "source_collections": ["device_poll_status"]})
            ip_seen.add(ip)

    if dry_run:
        return {"ok": True, "dry_run": True, "would_remove_count": len(to_remove), "would_remove": to_remove}

    # Execute deletion. Preserve db.devices (manuali).
    deleted = 0
    for d in to_remove:
        ip = d["ip"]
        await db.managed_devices.delete_many({"client_id": client_id, "ip": ip, "source": "connector"})
        await db.device_poll_status.delete_many({"client_id": client_id, "device_ip": ip})
        # Resolve any open alert against this device
        try:
            await db.alerts.update_many(
                {"client_id": client_id, "device_ip": ip, "status": {"$ne": "resolved"}},
                {"$set": {"status": "resolved", "resolved_at": datetime.now(timezone.utc).isoformat(),
                           "resolved_by_system": True,
                           "resolution_note": "Device rimosso dal connector (sync inversa)"}}
            )
        except Exception:
            pass
        deleted += 1

    audit_logger and await audit_logger.log(
        AuditAction.DELETE_DEVICE,
        user_id=(current_user or {}).get("id"),
        user_email=(current_user or {}).get("email"),
        resource_type="bulk_device",
        resource_id=client_id,
        details={"client_id": client_id, "removed_count": deleted, "active_ips_count": len(active_set),
                 "removed_ips": [d["ip"] for d in to_remove]},
    )
    return {"ok": True, "removed_count": deleted, "removed": to_remove, "active_ips_received": len(active_set)}


@router.delete("/connector/{client_id}/managed-devices/{device_id}")
async def remove_managed_device(client_id: str, device_id: str, current_user: dict = Depends(get_current_user)):
    """Rimuove un device dal Center. Multi-source:
    - Prova a risolvere l'id via managed_devices/db.devices/poll_<ip> → ottiene l'IP target
    - Cancella il record da TUTTE le collection (managed_devices, devices, device_poll_status)
      usando sia l'id che l'IP come chiavi. Cosi` il device sparisce per davvero,
      non solo da una collection, evitando "zombie" che restano nelle altre.
    """
    # Cerca il device senza upsert (il resolver fa upsert, qui non vogliamo)
    md = await db.managed_devices.find_one(
        {"$or": [{"id": device_id}, {"ip": device_id}]},
        {"_id": 0, "ip": 1, "id": 1},
    )
    manual = await db.devices.find_one(
        {"$or": [{"id": device_id}, {"ip_address": device_id}]},
        {"_id": 0, "ip_address": 1, "id": 1},
    )

    # Se device_id assomiglia a `poll_<ip>` estrai l'IP per le delete
    synth_ip = None
    if device_id.startswith("poll_"):
        synth_ip = device_id[len("poll_"):].replace("_", ".")

    # IP candidate (per cancellare da device_poll_status)
    candidate_ip = (md or {}).get("ip") or (manual or {}).get("ip_address") or synth_ip

    # Esegui delete in tutte le collection dove puo` esistere il record
    results = {"managed_devices": 0, "devices": 0, "device_poll_status": 0}
    if md or manual or synth_ip:
        r1 = await db.managed_devices.delete_many(
            {"$or": [{"id": device_id, "client_id": client_id},
                     {"ip": candidate_ip, "client_id": client_id} if candidate_ip else {"_nomatch": 1}]}
        )
        results["managed_devices"] = r1.deleted_count

        r2 = await db.devices.delete_many(
            {"$or": [{"id": device_id, "client_id": client_id},
                     {"ip_address": candidate_ip, "client_id": client_id} if candidate_ip else {"_nomatch": 1}]}
        )
        results["devices"] = r2.deleted_count

        if candidate_ip:
            r3 = await db.device_poll_status.delete_many(
                {"client_id": client_id, "device_ip": candidate_ip}
            )
            results["device_poll_status"] = r3.deleted_count

    total = sum(results.values())
    if total == 0:
        raise HTTPException(status_code=404, detail="Device non trovato in nessuna collection")

    # Cleanup collaterale: alert/metrics/live_metrics/iLO data per lo stesso device
    if candidate_ip:
        try:
            await db.alerts.update_many(
                {"client_id": client_id, "device_ip": candidate_ip, "status": {"$ne": "resolved"}},
                {"$set": {"status": "resolved", "resolved_at": datetime.now(timezone.utc).isoformat(),
                           "resolved_by_system": True, "resolution_note": "Device rimosso dall'utente"}}
            )
        except Exception:
            pass

    audit_logger and await audit_logger.log(
        AuditAction.DELETE_DEVICE,
        user_id=(current_user or {}).get("id"),
        user_email=(current_user or {}).get("email"),
        resource_type="device",
        resource_id=device_id,
        details={"client_id": client_id, "ip": candidate_ip, "deletes": results},
    )
    return {"status": "ok", "deletes": results, "total": total}


async def _resolve_or_upsert_managed_device(
    client_id: str,
    device_id: str,
) -> tuple[str, str, bool]:
    """Resolver multi-source per gli endpoint di update device.
    Cerca il device in (1) managed_devices, (2) db.devices, (3) device_poll_status
    via id sintetico `poll_<ip>`. Se trovato fuori da managed_devices, fa upsert
    minimale cosi` i successivi `update_one` per `client_id+ip` funzionano.
    Restituisce (device_ip, device_name, was_upserted). Solleva HTTPException 404
    se nessuna source contiene il device.
    """
    md = await db.managed_devices.find_one(
        {"id": device_id, "client_id": client_id},
        {"_id": 0, "ip": 1, "name": 1},
    )
    if md and md.get("ip"):
        return md["ip"], md.get("name") or "", False

    now_iso = datetime.now(timezone.utc).isoformat()

    # Fallback 1: db.devices (manualmente aggiunti)
    manual = await db.devices.find_one(
        {"id": device_id, "client_id": client_id},
        {"_id": 0, "ip_address": 1, "name": 1},
    )
    if manual and manual.get("ip_address"):
        ip = manual["ip_address"]
        name = manual.get("name") or ""
        await db.managed_devices.update_one(
            {"client_id": client_id, "ip": ip},
            {
                "$set": {"name": name, "ip": ip, "client_id": client_id},
                "$setOnInsert": {"id": device_id, "created_at": now_iso, "created_by": "auto-resolver"},
            },
            upsert=True,
        )
        return ip, name, True

    # Fallback 2: device_id sintetico `poll_<ip-with-underscores>`
    if device_id.startswith("poll_"):
        synth_ip = device_id[len("poll_"):].replace("_", ".")
        pd = await db.device_poll_status.find_one(
            {"client_id": client_id, "device_ip": synth_ip},
            {"_id": 0, "device_ip": 1, "device_name": 1},
        )
        if pd:
            ip = pd.get("device_ip") or synth_ip
            name = pd.get("device_name") or synth_ip
            await db.managed_devices.update_one(
                {"client_id": client_id, "ip": ip},
                {
                    "$set": {"name": name, "ip": ip, "client_id": client_id},
                    "$setOnInsert": {"id": device_id, "created_at": now_iso, "created_by": "auto-resolver"},
                },
                upsert=True,
            )
            return ip, name, True

    raise HTTPException(status_code=404, detail="Device non trovato in managed_devices, devices, o device_poll_status")


@router.put("/connector/{client_id}/managed-devices/{device_id}/monitor-type")
async def update_device_monitor_type_by_id(
    client_id: str,
    device_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Aggiorna il metodo di monitoraggio di un dispositivo (snmp | ping | http | snmp+http)."""
    body = await request.json()
    check_nosql_injection(body)
    mt = body.get("monitor_type")
    if mt not in ("snmp", "ping", "http", "snmp+http"):
        raise HTTPException(status_code=400, detail="monitor_type deve essere uno di: snmp, ping, http, snmp+http")
    update = {"monitor_type": mt}
    if body.get("http_port"):
        try:
            update["http_port"] = int(body.get("http_port"))
        except Exception:
            pass
    # Multi-source resolver: gestisce device-id da managed_devices/devices/poll_<ip>
    device_ip, _, _ = await _resolve_or_upsert_managed_device(client_id, device_id)
    await db.managed_devices.update_one(
        {"client_id": client_id, "ip": device_ip},
        {"$set": update},
    )
    return {"ok": True, "monitor_type": mt, "device_ip": device_ip}


@router.post("/connector/{client_id}/managed-devices/bulk-upgrade-snmp")
async def bulk_upgrade_snmp_monitor_type(
    client_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Per tutti i device del cliente con monitor_type='http' che hanno una community
    SNMP o snmp_version configurata, passa il monitor_type a 'snmp+http'.
    Utile per correggere device importati come http-only che però hanno SNMP attivo.
    """
    upgraded = []
    async for d in db.managed_devices.find({"client_id": client_id, "monitor_type": "http"}, {"_id": 0}):
        has_snmp = bool(d.get("community")) or d.get("snmp_version") or d.get("snmpv3_username")
        if has_snmp:
            await db.managed_devices.update_one(
                {"id": d["id"]},
                {"$set": {"monitor_type": "snmp+http"}},
            )
            upgraded.append({"id": d["id"], "name": d.get("name"), "ip": d.get("ip")})
    return {"ok": True, "upgraded_count": len(upgraded), "upgraded": upgraded}


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
    # Multi-source resolver
    device_ip, _, _ = await _resolve_or_upsert_managed_device(client_id, device_id)
    await db.managed_devices.update_one(
        {"client_id": client_id, "ip": device_ip},
        {"$set": update}
    )
    await audit_logger.log(
        AuditAction.UPDATE_DEVICE,
        user_id=current_user["id"], user_email=current_user["email"],
        resource_type="device", resource_id=device_id,
        details={"action": "snmp_config_updated", "version": snmp_version},
    )
    return {"status": "ok", "snmp_version": snmp_version, "device_ip": device_ip}



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
    result = []
    for d in devices:
        dev_out = {
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
        }
        # Enrich with vendor-specific OIDs (same logic as /connector/managed-devices).
        # Senza questo arricchimento il connector non sapeva quali OID vendor pollare
        # (Synology DSM, APC UPS, HPE iLO, ecc.) e le schede dispositivi restavano
        # vuote nelle sezioni HARDWARE/Sistema/RAID/Dischi nonostante il profilo
        # fosse applicato.
        try:
            pk = d.get("profile_key")
            if pk:
                from device_profiles import get_profile
                profile = get_profile(pk)
                if profile:
                    oids = profile.get("oids") or {}
                    scalars: dict = {}
                    tables: dict = {}
                    skip_base = {
                        "sysDescr", "sysObjectID", "sysUpTime", "sysContact", "sysName",
                        "sysLocation", "ifNumber", "ifDescr", "ifOperStatus",
                        "ifInOctets", "ifOutOctets",
                    }
                    for name, oid in oids.items():
                        if not oid or not isinstance(oid, str):
                            continue
                        if name in skip_base:
                            continue
                        if oid.endswith(".0"):
                            scalars[name] = oid
                        else:
                            tables[name] = oid
                    if scalars or tables:
                        dev_out["vendor_snmp_targets"] = {
                            "profile_key": pk,
                            "vendor": profile.get("vendor"),
                            "scalars": scalars,
                            "tables": tables,
                            "poll_interval_seconds": profile.get("polling_interval_seconds", 120),
                        }
                        dev_out["profile_thresholds"] = profile.get("thresholds") or {}
        except Exception as e:
            logger.warning(f"fetch-devices vendor enrichment failed for {d.get('ip')}: {e}")
        result.append(dev_out)
    return result


@router.put("/connector/{client_id}/managed-devices/{device_id}/silence")
async def update_device_silence(
    client_id: str,
    device_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Toggle del flag `alerts_silenced`. Quando true, nessun alert verra` creato
    per questo device (gating in alert_filter.should_emit_alert applicato a tutti
    i punti di emissione). Esistenti alert NON vengono toccati — l'admin puo`
    risolverli manualmente. Il flag e` cached lato server (TTL 30s) per perf.
    """
    body = await request.json()
    check_nosql_injection(body)
    silenced = bool(body.get("silenced", False))
    silence_reason = sanitize_string(body.get("reason") or "", max_length=200)
    now_iso = datetime.now(timezone.utc).isoformat()

    update_doc = {
        "alerts_silenced": silenced,
        "alerts_silenced_updated_at": now_iso,
        "alerts_silenced_reason": silence_reason if silenced else "",
        "alerts_silenced_by": (current_user or {}).get("email") if silenced else "",
    }

    # Multi-source resolver: gestisce device-id da managed_devices/devices/poll_<ip>
    device_ip, device_name, _ = await _resolve_or_upsert_managed_device(client_id, device_id)
    await db.managed_devices.update_one(
        {"client_id": client_id, "ip": device_ip},
        {"$set": update_doc},
    )

    invalidate_silence_cache(client_id=client_id, device_ip=device_ip)

    audit_logger and await audit_logger.log(
        AuditAction.UPDATE_DEVICE,
        user_id=(current_user or {}).get("id"),
        user_email=(current_user or {}).get("email"),
        resource_type="managed_device",
        resource_id=device_id,
        details={
            "client_id": client_id,
            "alerts_silenced": silenced,
            "reason": silence_reason,
            "device_name": device_name,
            "device_ip": device_ip,
        },
    )
    return {"ok": True, "alerts_silenced": silenced, "device_id": device_id, "device_ip": device_ip}


@router.post("/connector/{client_id}/managed-devices/auto-classify")
async def bulk_auto_classify_devices(
    client_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Riclassifica automaticamente i device del cliente basandosi su sysDescr/
    sysObjectID/hostname/model. Aggiorna `device_type` solo dove la classifica
    differisce da quella corrente — non sovrascrive con None se nulla matcha.
    Utile dopo onboarding o per correggere device classificati come "server"
    quando in realta` sono stampanti, NAS, ecc.
    """
    changed = []
    async for d in db.managed_devices.find({"client_id": client_id}, {"_id": 0}):
        sys_descr = d.get("sys_descr") or d.get("vendor_telemetry", {}).get("sys_descr")
        sys_object_id = d.get("sys_object_id") or d.get("vendor_telemetry", {}).get("sys_object_id")
        new_type = classify_device_type(
            sys_descr=sys_descr,
            sys_object_id=sys_object_id,
            hostname=d.get("name"),
            model=d.get("model"),
        )
        old_type = d.get("device_type") or ""
        if new_type and new_type != old_type:
            await db.managed_devices.update_one(
                {"id": d["id"]},
                {"$set": {"device_type": new_type, "device_type_auto_classified_at": datetime.now(timezone.utc).isoformat()}},
            )
            changed.append({
                "id": d["id"],
                "name": d.get("name"),
                "ip": d.get("ip"),
                "old_type": old_type or "(none)",
                "new_type": new_type,
            })
    return {"ok": True, "changed_count": len(changed), "changed": changed}


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
                "remote_sys_cap": int(n.get("remote_sys_cap", 0) or 0),
                "updated_at": now_iso,
            })
        await db.lldp_neighbors.insert_many(docs)

    logger.info(f"LLDP neighbors updated for {client_id}: {len(neighbors)} entries")
    return {"status": "ok", "neighbors_stored": len(neighbors)}


@router.post(f"/{C}/cn")
@router.post("/connector/cdp-neighbors")
async def connector_cdp_report(request: Request):
    """Receive CDP (Cisco Discovery Protocol) neighbor data from the connector."""
    client_data = await verify_connector_request(request)
    body = await request.json()
    check_nosql_injection(body)
    client_id = client_data["id"]
    neighbors = body.get("neighbors", [])
    now_iso = datetime.now(timezone.utc).isoformat()

    # Clear old CDP data for this client and re-insert fresh
    await db.cdp_neighbors.delete_many({"client_id": client_id})

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
                "remote_platform": sanitize_string(n.get("remote_platform", ""), 256),
                "remote_sys_cap": int(n.get("remote_sys_cap", 0) or 0),
                "updated_at": now_iso,
            })
        await db.cdp_neighbors.insert_many(docs)

    logger.info(f"CDP neighbors updated for {client_id}: {len(neighbors)} entries")
    return {"status": "ok", "neighbors_stored": len(neighbors)}


@router.post(f"/{C}/sp")
@router.post("/connector/switch-ports")
async def connector_switch_ports_report(request: Request):
    """Riceve la tabella completa delle porte degli switch dal connector.

    Body:
    {
      "switches": [
        { "local_ip": "192.168.1.2", "device_mac": "...",
          "ports": [
            {"idx": 1, "name": "Gi1/0/1", "oper": 1, "admin": 1, "speed_mbps": 1000, "last_change_s": 12345},
            ...
          ]
        }
      ]
    }
    Oper/Admin: 1=up, 2=down, 3=testing, 5=dormant, 6=notPresent, 7=lowerLayerDown
    """
    client_data = await verify_connector_request(request)
    body = await request.json()
    check_nosql_injection(body)
    client_id = client_data["id"]
    switches = body.get("switches", []) or []
    now_iso = datetime.now(timezone.utc).isoformat()

    # Wipe and reinsert per-switch to stay idempotent and handle port changes
    # v3.6.9+: flap detection - confronta stato precedente con nuovo per tracciare UP/DOWN events
    total_stored = 0
    total_flaps = 0
    stored_per_switch: list[dict] = []
    for sw in switches:
        local_ip = sanitize_string(sw.get("local_ip", ""), 64)
        if not local_ip:
            continue
        ports = sw.get("ports", []) or []

        # Leggi stato precedente delle porte per flap detection
        prev_ports = await db.switch_ports.find(
            {"client_id": client_id, "local_ip": local_ip},
            {"_id": 0, "idx": 1, "oper": 1, "admin": 1, "speed_mbps": 1}
        ).to_list(2000)
        prev_by_idx = {int(p.get("idx", 0)): p for p in prev_ports if p.get("idx") is not None}

        flap_events = []  # buffer per bulk insert

        await db.switch_ports.delete_many({"client_id": client_id, "local_ip": local_ip})
        if ports:
            docs = []
            for p in ports:
                try:
                    idx_v = int(p.get("idx", 0))
                except Exception:
                    continue
                new_oper = int(p.get("oper", 0)) if p.get("oper") is not None else 0
                new_admin = int(p.get("admin", 0)) if p.get("admin") is not None else 0
                new_speed = int(p.get("speed_mbps", 0) or 0)

                # Flap detection
                prev = prev_by_idx.get(idx_v)
                if prev:
                    prev_oper = int(prev.get("oper", 0) or 0)
                    prev_admin = int(prev.get("admin", 0) or 0)
                    prev_speed = int(prev.get("speed_mbps", 0) or 0)
                    events = []
                    if prev_oper != new_oper:
                        events.append({"kind": "oper_change", "from": prev_oper, "to": new_oper})
                    if prev_admin != new_admin:
                        events.append({"kind": "admin_change", "from": prev_admin, "to": new_admin})
                    # Speed change solo se entrambi > 0 (evita rumore da 0->N al primo link-up)
                    if prev_speed > 0 and new_speed > 0 and prev_speed != new_speed:
                        events.append({"kind": "speed_change", "from": prev_speed, "to": new_speed})
                    for ev in events:
                        flap_events.append({
                            "client_id": client_id,
                            "local_ip": local_ip,
                            "idx": idx_v,
                            "port_name": sanitize_string(str(p.get("name") or f"port{idx_v}"), 128),
                            "ts": now_iso,
                            **ev,
                        })

                docs.append({
                    "client_id": client_id,
                    "local_ip": local_ip,
                    "idx": idx_v,
                    "name": sanitize_string(str(p.get("name") or f"port{idx_v}"), 128),
                    "descr": sanitize_string(str(p.get("descr") or ""), 128),
                    "alias": sanitize_string(str(p.get("alias") or ""), 128),
                    "oper": new_oper,
                    "admin": new_admin,
                    "speed_mbps": new_speed,
                    "last_change_s": int(p.get("last_change_s", 0) or 0),
                    "in_octets": str(p.get("in_octets") or "0"),
                    "out_octets": str(p.get("out_octets") or "0"),
                    "rx_bps": int(p.get("rx_bps", 0) or 0),
                    "tx_bps": int(p.get("tx_bps", 0) or 0),
                    "rx_pps": int(p.get("rx_pps", 0) or 0),
                    "tx_pps": int(p.get("tx_pps", 0) or 0),
                    "poe_admin": int(p.get("poe_admin", 0) or 0),
                    "poe_status": int(p.get("poe_status", 0) or 0),
                    "poe_class": int(p.get("poe_class", 0) or 0),
                    "updated_at": now_iso,
                })
            if docs:
                await db.switch_ports.insert_many(docs)
                total_stored += len(docs)

        # Insert flap events (se presenti)
        if flap_events:
            await db.port_flap_events.insert_many(flap_events)
            total_flaps += len(flap_events)
            # Retention: elimina eventi > 30 giorni per evitare crescita indefinita
            cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            await db.port_flap_events.delete_many({
                "client_id": client_id, "local_ip": local_ip, "ts": {"$lt": cutoff}
            })

        stored_per_switch.append({"local_ip": local_ip, "ports_count": len(ports)})

    logger.info(f"Switch ports updated for {client_id}: {len(switches)} switch, {total_stored} porte totali, {total_flaps} eventi flap")
    return {"status": "ok", "switches_stored": len(switches), "total_ports": total_stored, "flap_events": total_flaps, "per_switch": stored_per_switch}


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
    ip_port_probes = body.get("ip_port_probes", [])  # v3.6.13: TCP fingerprint
    bmc_candidates = body.get("bmc_candidates", [])  # v3.6.14: Redfish BMC auto-discovery

    # Build IP -> listening_ports map from probes
    ip_ports_map = {}
    for probe in ip_port_probes:
        pip = probe.get("ip", "")
        ports = probe.get("ports", []) or []
        if pip and ports:
            ip_ports_map[pip] = sorted(set(int(p) for p in ports if str(p).isdigit()))

    # Build IP -> BMC info map
    ip_bmc_map = {}
    for bmc in bmc_candidates:
        bip = bmc.get("ip", "")
        if bip and bmc.get("bmc_kind"):
            ip_bmc_map[bip] = {
                "bmc_kind": bmc.get("bmc_kind", ""),
                "redfish_version": bmc.get("redfish_version", ""),
                "oem_hint": bmc.get("oem_hint", ""),
            }

    # Store discovery data (replace old data for this client)
    await db.network_discovery.delete_many({"client_id": client_id})
    if mac_tables or port_speeds or device_macs or ip_port_probes or bmc_candidates:
        await db.network_discovery.insert_one({
            "client_id": client_id,
            "mac_tables": mac_tables,
            "port_speeds": port_speeds,
            "device_macs": device_macs,
            "ip_port_probes": ip_port_probes,
            "bmc_candidates": bmc_candidates,
            "updated_at": now_iso,
        })

    # Upsert BMC candidates into dedicated collection (for admin "Add server" UI)
    # Keep only non-managed BMCs so the admin sees real suggestions.
    # v3.6.17 PERF: bulk_write invece di N awaits separate.
    managed_ip_set_for_bmc = set()
    _mdev_for_bmc = await db.managed_devices.find({"client_id": client_id}, {"_id": 0, "ip": 1}).to_list(2000)
    for _md in _mdev_for_bmc:
        if _md.get("ip"):
            managed_ip_set_for_bmc.add(_md["ip"])
    bmc_ops = []
    from pymongo import UpdateOne
    for bmc in bmc_candidates:
        bip = bmc.get("ip", "")
        if not bip or not bmc.get("bmc_kind"):
            continue
        if bip in managed_ip_set_for_bmc:
            continue  # gia' censito
        bmc_ops.append(UpdateOne(
            {"client_id": client_id, "ip": bip},
            {"$set": {
                "client_id": client_id, "ip": bip,
                "bmc_kind": bmc.get("bmc_kind", ""),
                "redfish_version": bmc.get("redfish_version", ""),
                "oem_hint": bmc.get("oem_hint", ""),
                "server_header": bmc.get("server_header", ""),
                "last_seen": now_iso,
            }, "$setOnInsert": {"first_seen": now_iso, "dismissed": False}},
            upsert=True,
        ))
    if bmc_ops:
        await db.bmc_candidates.bulk_write(bmc_ops, ordered=False)
    # Drop BMC candidates not seen in last 24h or already managed
    if managed_ip_set_for_bmc:
        await db.bmc_candidates.delete_many({
            "client_id": client_id, "ip": {"$in": list(managed_ip_set_for_bmc)}
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
            ep_ip = resolved_ip or entry.get("ip", "")
            ep_bmc = ip_bmc_map.get(ep_ip, {}) if ep_ip else {}
            discovered_endpoints.append({
                "client_id": client_id,
                "switch_ip": switch_ip,
                "port": port,
                "mac": mac,
                "ip": ep_ip,
                "vlan": vlan,
                "hostname": entry.get("hostname", ""),
                "is_managed": resolved_ip in managed_ips,
                "listening_ports": ip_ports_map.get(ep_ip, []),  # v3.6.13
                "bmc_kind": ep_bmc.get("bmc_kind", ""),  # v3.6.14: ilo/idrac/ipmi/xcc
                "bmc_version": ep_bmc.get("redfish_version", ""),
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
    # BEFORE replacing, capture previous IP<->MAC bindings so we can detect changes.
    prev_endpoints = await db.discovered_endpoints.find(
        {"client_id": client_id}, {"_id": 0, "ip": 1, "mac": 1, "switch_ip": 1, "port": 1}
    ).to_list(10000)
    prev_ip_mac = {}  # ip -> set(mac)
    prev_mac_ip = {}  # mac -> ip
    for p in prev_endpoints:
        if p.get("ip") and p.get("mac"):
            prev_ip_mac.setdefault(p["ip"], set()).add(p["mac"].upper())
            prev_mac_ip[p["mac"].upper()] = p["ip"]

    await db.discovered_endpoints.delete_many({"client_id": client_id})
    if discovered_endpoints:
        await db.discovered_endpoints.insert_many(discovered_endpoints)

    # Detect IP/MAC binding changes (possible spoofing / device replacement / roaming)
    curr_ip_mac = {}
    curr_mac_ip = {}
    for e in discovered_endpoints:
        if e.get("ip") and e.get("mac"):
            curr_ip_mac.setdefault(e["ip"], set()).add(e["mac"].upper())
            curr_mac_ip[e["mac"].upper()] = e["ip"]

    identity_alerts = []
    now_iso_alerts = datetime.now(timezone.utc).isoformat()

    # Case A: same IP, different MAC(s) (ARP spoofing, device replaced)
    for ip, new_macs in curr_ip_mac.items():
        old_macs = prev_ip_mac.get(ip, set())
        if old_macs and not old_macs.intersection(new_macs):
            identity_alerts.append({
                "severity": "critical",
                "title": f"IP con MAC CAMBIATO: {ip}",
                "message": f"L'IP {ip} ora risponde con un MAC diverso. Prima: {', '.join(sorted(old_macs))[:80]}. Ora: {', '.join(sorted(new_macs))[:80]}. Possibile ARP spoofing o sostituzione HW.",
                "device_ip": ip,
                "source_type": "security_ip_mac_change",
            })

    # Case B: same MAC, different IP (DHCP reassignment or device moved, lower severity)
    for mac, new_ip in curr_mac_ip.items():
        old_ip = prev_mac_ip.get(mac)
        if old_ip and old_ip != new_ip:
            # Only alert for managed/known devices to avoid spam from dynamic clients
            if old_ip in managed_ips or new_ip in managed_ips:
                identity_alerts.append({
                    "severity": "high",
                    "title": f"Dispositivo {mac} cambiato IP: {old_ip} → {new_ip}",
                    "message": f"Il MAC {mac} è stato visto prima su {old_ip} e ora su {new_ip}. DHCP lease cambiato o dispositivo spostato.",
                    "device_ip": new_ip,
                    "source_type": "security_mac_ip_roam",
                })

    # Insert identity alerts (dedup)
    for a in identity_alerts:
        existing = await db.alerts.find_one({
            "client_id": client_id, "title": a["title"], "status": "active"
        })
        if not existing:
            _conn2_alert = {
                "id": str(uuid.uuid4()),
                "client_id": client_id,
                "device_ip": a["device_ip"],
                "device_name": managed_ip_names.get(a["device_ip"], a["device_ip"]),
                "device_type": "network",
                "severity": a["severity"],
                "source_type": a["source_type"],
                "title": a["title"],
                "message": a["message"],
                "status": "active",
                "acknowledged_by": None, "acknowledged_at": None, "resolved_at": None,
                "created_at": now_iso_alerts,
            }
            await insert_alert_if_emit(db, _conn2_alert)
            try:
                import webpush as _wp
                await _wp.notify_new_alert(db, _conn2_alert)
            except Exception:
                pass

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


@router.post("/maintenance/backfill-client-id")
async def backfill_orphan_records(current_user: dict = Depends(get_current_user)):
    """
    Find records without client_id (alerts, device_poll_status, vault credentials)
    and assign them to the correct client by resolving their device_ip.
    Safe idempotent operation for admins.
    """
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo admin")

    # Build an IP -> client_id mapping from all authoritative sources
    ip_to_client = {}
    async for md in db.managed_devices.find({}, {"_id": 0, "ip": 1, "client_id": 1}):
        if md.get("ip") and md.get("client_id"):
            ip_to_client[md["ip"]] = md["client_id"]
    async for ps in db.device_poll_status.find({"client_id": {"$ne": None}}, {"_id": 0, "device_ip": 1, "client_id": 1}):
        if ps.get("device_ip") and ps.get("client_id") and ps["device_ip"] not in ip_to_client:
            ip_to_client[ps["device_ip"]] = ps["client_id"]
    async for ep in db.discovered_endpoints.find({}, {"_id": 0, "ip": 1, "client_id": 1}):
        if ep.get("ip") and ep.get("client_id") and ep["ip"] not in ip_to_client:
            ip_to_client[ep["ip"]] = ep["client_id"]

    # If single-client installation, fall back to that client for everything
    all_clients = await db.clients.find({}, {"_id": 0, "id": 1}).to_list(50)
    single_client_id = all_clients[0]["id"] if len(all_clients) == 1 else None

    stats = {"alerts_fixed": 0, "poll_status_fixed": 0, "credentials_fixed": 0, "orphans_remaining": 0}

    async for a in db.alerts.find({"$or": [{"client_id": None}, {"client_id": ""}, {"client_id": {"$exists": False}}]}, {"_id": 0, "id": 1, "device_ip": 1}):
        new_cid = ip_to_client.get(a.get("device_ip")) or single_client_id
        if new_cid:
            await db.alerts.update_one({"id": a["id"]}, {"$set": {"client_id": new_cid}})
            stats["alerts_fixed"] += 1
        else:
            stats["orphans_remaining"] += 1

    async for ps in db.device_poll_status.find({"$or": [{"client_id": None}, {"client_id": ""}, {"client_id": {"$exists": False}}]}, {"_id": 0, "device_ip": 1}):
        new_cid = ip_to_client.get(ps.get("device_ip")) or single_client_id
        if new_cid:
            await db.device_poll_status.update_one({"device_ip": ps["device_ip"]}, {"$set": {"client_id": new_cid}})
            stats["poll_status_fixed"] += 1

    async for c in db.device_credentials.find({"$or": [{"client_id": None}, {"client_id": ""}, {"client_id": {"$exists": False}}]}, {"_id": 0, "id": 1, "device_ip": 1}):
        new_cid = ip_to_client.get(c.get("device_ip")) or single_client_id
        if new_cid:
            await db.device_credentials.update_one({"id": c["id"]}, {"$set": {"client_id": new_cid}})
            stats["credentials_fixed"] += 1

    return {
        "status": "ok",
        "message": f"Backfill completato: {stats['alerts_fixed']} alert, {stats['poll_status_fixed']} device, {stats['credentials_fixed']} credenziali aggiornate.",
        **stats,
    }


# ==================== BMC CANDIDATES (v3.6.14) ====================
# Redfish/BMC auto-discovery: il connector trova iLO/iDRAC/IPMI/XCC sulla rete
# e li propone come nuovi device da censire (con un click lato UI).

@router.get("/bmc-candidates")
async def list_bmc_candidates(
    client_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """Lista dei BMC scoperti dal connector e non ancora censiti/scartati."""
    q = {"dismissed": {"$ne": True}}
    if client_id:
        q["client_id"] = client_id
    items = await db.bmc_candidates.find(q, {"_id": 0}).sort("last_seen", -1).to_list(500)
    # Enrich with switch_ip/port if available from discovered_endpoints
    ips = [i.get("ip") for i in items if i.get("ip")]
    ep_map = {}
    if ips:
        async for e in db.discovered_endpoints.find(
            {"ip": {"$in": ips}},
            {"_id": 0, "ip": 1, "switch_ip": 1, "port": 1, "mac": 1, "vlan": 1},
        ):
            ep_map[e["ip"]] = e
    for i in items:
        ep = ep_map.get(i.get("ip"), {})
        i["switch_ip"] = ep.get("switch_ip", "")
        i["switch_port"] = ep.get("port", "")
        i["mac"] = ep.get("mac", "")
        i["vlan"] = ep.get("vlan", "")
    return {"items": items, "count": len(items)}


@router.post("/bmc-candidates/{client_id}/{ip}/dismiss")
async def dismiss_bmc_candidate(
    client_id: str, ip: str,
    current_user: dict = Depends(get_current_user),
):
    """Nascondi un BMC candidato (non proporlo piu' nella UI)."""
    r = await db.bmc_candidates.update_one(
        {"client_id": client_id, "ip": ip},
        {"$set": {"dismissed": True, "dismissed_at": datetime.now(timezone.utc).isoformat(),
                  "dismissed_by": current_user.get("email", "")}},
    )
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Candidate non trovato")
    return {"status": "ok"}


@router.post("/bmc-candidates/{client_id}/{ip}/import")
async def import_bmc_candidate(
    client_id: str, ip: str,
    current_user: dict = Depends(get_current_user),
):
    """Importa un BMC candidato come managed device (Redfish-enabled).
    Crea un record in db.devices con device_type='server' e redfish_enabled=True.
    Le credenziali vanno aggiunte in un secondo step dal Vault.
    """
    cand = await db.bmc_candidates.find_one({"client_id": client_id, "ip": ip}, {"_id": 0})
    if not cand:
        raise HTTPException(status_code=404, detail="Candidate non trovato")
    client = await db.clients.find_one({"id": client_id}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client non trovato")
    # Nome suggerito dal vendor BMC
    bmc_kind = cand.get("bmc_kind", "")
    kind_label = {
        "ilo": "HPE iLO", "idrac": "Dell iDRAC", "ipmi": "Supermicro IPMI",
        "xcc": "Lenovo XCC", "redfish_generic": "Redfish BMC",
    }.get(bmc_kind, "BMC")
    device_name = f"{kind_label} {ip}"
    # Skip se gia' esiste
    existing = await db.devices.find_one({"client_id": client_id, "ip_address": ip}, {"_id": 0})
    if existing:
        # Marca come imported cosi' sparisce dalla lista
        await db.bmc_candidates.update_one(
            {"client_id": client_id, "ip": ip},
            {"$set": {"dismissed": True, "imported_as": existing.get("id"),
                      "dismissed_at": datetime.now(timezone.utc).isoformat()}},
        )
        return {"status": "already_exists", "device_id": existing.get("id")}
    device_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await db.devices.insert_one({
        "id": device_id,
        "client_id": client_id,
        "name": device_name,
        "device_type": "server",
        "ip_address": ip,
        "hostname": "",
        "location": "",
        "status": "active",
        "redfish_enabled": True,
        "last_poll": None,
        "health_status": None,
        "created_at": now,
        "created_via": "bmc_auto_discovery",
        "bmc_kind": bmc_kind,
        "bmc_redfish_version": cand.get("redfish_version", ""),
    })
    await db.bmc_candidates.update_one(
        {"client_id": client_id, "ip": ip},
        {"$set": {"dismissed": True, "imported_as": device_id, "dismissed_at": now,
                  "dismissed_by": current_user.get("email", "")}},
    )
    try:
        await audit_logger.log(
            AuditAction.CREATE_DEVICE, user_id=current_user["id"], user_email=current_user["email"],
            resource_type="device", resource_id=device_id,
            details={"name": device_name, "type": "server", "source": "bmc_auto_discovery",
                     "bmc_kind": bmc_kind, "ip": ip},
        )
    except Exception:
        pass
    return {"status": "imported", "device_id": device_id, "name": device_name}
