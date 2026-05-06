"""Device CRUD and credentials routes."""
from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
import uuid
from datetime import datetime, timezone

from database import db
from models import DeviceCreate, DeviceResponse, DeviceCredentials, RedfishTestRequest
from security import security_manager
from audit import AuditAction
from deps import get_current_user, audit_logger, redfish_poller

router = APIRouter(prefix="/api", tags=["devices"])


@router.post("/devices", response_model=DeviceResponse)
async def create_device(device: DeviceCreate, current_user: dict = Depends(get_current_user)):
    client = await db.clients.find_one({"id": device.client_id}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    device_doc = {
        "id": str(uuid.uuid4()), "client_id": device.client_id,
        "name": device.name, "device_type": device.device_type,
        "ip_address": device.ip_address, "hostname": device.hostname or "",
        "location": device.location or "", "status": "active",
        "redfish_enabled": device.redfish_enabled or False,
        "last_poll": None, "health_status": None,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.devices.insert_one(device_doc)
    await audit_logger.log(
        AuditAction.CREATE_DEVICE, user_id=current_user["id"], user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        resource_type="device", resource_id=device_doc["id"],
        details={"name": device.name, "type": device.device_type}
    )
    return DeviceResponse(**device_doc, client_name=client["name"], has_credentials=False)


@router.get("/devices")
async def get_devices(client_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    query = {}
    if client_id:
        query["client_id"] = client_id

    now_iso = datetime.now(timezone.utc).isoformat()

    # Fetch manually added devices
    devices = await db.devices.find(query, {"_id": 0}).to_list(1000)
    manual_ips = {d["ip_address"] for d in devices}

    # Fetch connector-reported devices (device_poll_status)
    poll_query = query.copy()
    poll_devices = await db.device_poll_status.find(poll_query, {"_id": 0}).to_list(5000)
    poll_by_ip = {pd.get("device_ip"): pd for pd in poll_devices if pd.get("device_ip")}

    # Fetch managed devices for community/snmp info
    managed_query = query.copy()
    managed_devices_raw = await db.managed_devices.find(managed_query, {"_id": 0}).to_list(5000)
    managed_by_ip = {}
    for md in managed_devices_raw:
        md_ip = md.get("ip") or md.get("ip_address", "")
        if md_ip:
            managed_by_ip[md_ip] = md

    # Enrich manually-added devices with profile_key from managed_devices/poll_status
    for d in devices:
        ip = d.get("ip_address")
        if not ip:
            continue
        md = managed_by_ip.get(ip) or {}
        pd = poll_by_ip.get(ip) or {}
        d["profile_key"] = d.get("profile_key") or md.get("profile_key") or pd.get("profile_key")
        d["vendor"] = d.get("vendor") or md.get("vendor") or pd.get("vendor")
        d["family"] = d.get("family") or md.get("family") or pd.get("family")
        # alerts_silenced flag (managed_devices wins; default False)
        d["alerts_silenced"] = bool(md.get("alerts_silenced", d.get("alerts_silenced", False)))
        d["alerts_silenced_reason"] = md.get("alerts_silenced_reason") or d.get("alerts_silenced_reason") or ""

    # Merge: add connector devices that aren't already in manual list
    for pd in poll_devices:
        ip = pd.get("device_ip", "")
        if ip and ip not in manual_ips:
            manual_ips.add(ip)
            # Determine device type from poll data, class, and name
            dev_type = pd.get("device_type", "")
            if not dev_type or dev_type == "?":
                dev_class = (pd.get("device_class") or "").lower()
                dev_name = (pd.get("device_name") or "").lower()
                sys_descr = (pd.get("sys_descr") or "").lower()
                combined = f"{dev_name} {sys_descr} {dev_class}"

                if any(k in combined for k in ["firewall", "zyxel", "usg", "fortigate", "pfsense", "sonicwall"]):
                    dev_type = "firewall"
                elif any(k in combined for k in ["ilo", "idrac", "ipmi", "bmc"]):
                    dev_type = "ilo"
                elif any(k in combined for k in ["ups", "xanto", "apc", "eaton", "liebert"]):
                    dev_type = "ups"
                elif any(k in combined for k in ["nas", "synology", "qnap"]):
                    dev_type = "nas"
                elif any(k in combined for k in ["printer", "laser", "stampante", "mfp", "laserjet", "officejet"]):
                    dev_type = "printer"
                elif any(k in combined for k in ["tvcc", "camera", "telecamera", "hikvision", "dahua", "nvr", "dvr"]):
                    dev_type = "tvcc"
                elif any(k in combined for k in ["ap ", "wifi", "ubiquiti", "unifi", "access point"]):
                    dev_type = "access-point"
                elif any(k in combined for k in ["router", "mikrotik", "draytek", "fritzbox", "vodafone station"]):
                    dev_type = "router"
                elif any(k in combined for k in ["switch", "hp 5130", "hp 5120", "officeconnect", "aruba", "netgear gs", "cisco catalyst", "gs110"]):
                    dev_type = "switch"
                elif any(k in combined for k in ["srv", "server", "proliant", "poweredge", "esxi", "vmware", "backup", "veeam"]):
                    dev_type = "server"
                else:
                    dev_type = dev_class if dev_class and dev_class != "generic" else "server"
            # Get managed device config (community, snmp version, etc.)
            md = managed_by_ip.get(ip, {})
            # Profile key: managed_devices wins over poll_status (manual override > auto-detect)
            profile_key = md.get("profile_key") or pd.get("profile_key")
            vendor = md.get("vendor") or pd.get("vendor")
            family = md.get("family") or pd.get("family")
            devices.append({
                "id": f"poll_{ip.replace('.','_')}",
                "client_id": pd.get("client_id", ""),
                "name": pd.get("device_name", ip),
                "device_type": dev_type,
                "ip_address": ip,
                "hostname": pd.get("sys_name", ""),
                "location": pd.get("sys_location", ""),
                "status": "online" if pd.get("reachable") else "offline",
                "redfish_enabled": False,
                # v3.8.18: source = chi ha SCOPERTO il device, non chi lo polla.
                # Se il device esiste in managed_devices con source=connector-scanner,
                # e' stato scoperto dallo Scanner anche se ora il Master lo polla via SNMP.
                # Solo se NON e' in managed_devices o e' in con altro source -> "connector-master".
                "source": (md.get("source") if md.get("source") in ("connector-scanner", "connector-master") else "connector-master"),
                "auto_added": bool(md.get("auto_added", False)),
                "discovered_via": md.get("discovered_via"),
                "discovered_subnet": md.get("discovered_subnet"),
                "vlan_id": md.get("vlan_id"),
                "mac": md.get("mac", ""),
                "mac_is_random": bool(md.get("mac_is_random", False)),
                "fingerbank_device_name": md.get("fingerbank_device_name"),
                "fingerbank_score": md.get("fingerbank_score"),
                "connection_type": md.get("connection_type"),
                "connection_source": md.get("connection_source"),
                "connection_via_switch": md.get("connection_via_switch"),
                "connection_via_port": md.get("connection_via_port"),
                "connection_confidence": md.get("connection_confidence"),
                "connector_hostname": pd.get("connector_hostname", ""),
                "last_poll": pd.get("last_poll"),
                "sys_descr": pd.get("sys_descr", ""),
                "cpu_usage": pd.get("cpu_usage"),
                "memory_usage": pd.get("memory_usage"),
                "temperature": pd.get("temperature"),
                "uptime": pd.get("sys_uptime") or pd.get("uptime", ""),
                "ports": pd.get("ports"),
                "monitor_type": md.get("monitor_type") or pd.get("monitor_type", ""),
                "snmp_community": md.get("community") or pd.get("snmp_community") or pd.get("community", ""),
                "snmp_version": md.get("snmp_version") or pd.get("snmp_version", ""),
                "http_port": md.get("http_port"),
                "ping_ms": pd.get("ping_ms"),
                # Web Console (auto-detected dal Connector tray)
                "web_console_url": md.get("web_console_url"),
                "web_console_port": md.get("web_console_port"),
                "web_console_scheme": md.get("web_console_scheme"),
                "web_console_title": md.get("web_console_title"),
                # Device Profile (vendor auto-config)
                "profile_key": profile_key,
                "vendor": vendor,
                "family": family,
                "profile_auto_matched": pd.get("profile_auto_matched", False) if not md.get("profile_key") else False,
                "alerts_silenced": bool(md.get("alerts_silenced", False)),
                "alerts_silenced_reason": md.get("alerts_silenced_reason") or "",
            })

    # 3rd pass: managed_devices orfani (aggiunti manualmente via UI, dal tray
    # Apri Web UI, oppure auto-censiti dal Connector Scanner via /lan-scan
    # con source="connector-scanner") - altrimenti sparirebbero
    # dalla UI del cliente finche' il connector non li vede.
    for md in managed_devices_raw:
        md_ip = md.get("ip") or md.get("ip_address", "")
        if not md_ip or md_ip in manual_ips:
            continue
        manual_ips.add(md_ip)
        # v3.8.15: preserva il source originale (connector-scanner / connector-master / manual)
        # cosi' la colonna FONTE in UI distingue MASTER vs SCANNER vs MANUALE.
        md_source = md.get("source") or "managed"
        # Status: i device dal Scanner sono "online" (li abbiamo appena visti via ARP/mDNS)
        # se last_seen_at recente; altrimenti pending.
        if md_source == "connector-scanner" and md.get("last_seen_at"):
            md_status = "online"
        else:
            md_status = "pending"
        devices.append({
            "id": md.get("id") or f"md_{md_ip.replace('.','_')}",
            "client_id": md.get("client_id", ""),
            "name": md.get("name", md_ip),
            "device_type": md.get("device_type", "server"),
            "ip_address": md_ip,
            "mac": md.get("mac", ""),
            "hostname": md.get("hostname", ""),
            "location": md.get("location", ""),
            "status": md_status,
            "redfish_enabled": False,
            "source": md_source,
            "auto_added": bool(md.get("auto_added", False)),
            "discovered_via": md.get("discovered_via"),
            "discovered_subnet": md.get("discovered_subnet"),
            "vlan_id": md.get("vlan_id"),
            "last_poll": md.get("web_console_last_tested") or md.get("last_seen_at"),
            "last_seen_at": md.get("last_seen_at"),
            "monitor_type": md.get("monitor_type", ""),
            "snmp_community": md.get("community") or md.get("snmp_community", ""),
            "snmp_version": md.get("snmp_version", ""),
            "http_port": md.get("http_port"),
            "web_console_url": md.get("web_console_url"),
            "web_console_port": md.get("web_console_port"),
            "web_console_scheme": md.get("web_console_scheme"),
            "web_console_title": md.get("web_console_title"),
            "profile_key": md.get("profile_key"),
            "vendor": md.get("vendor"),
            "family": md.get("family"),
            "fingerbank_device_name": md.get("fingerbank_device_name"),
            "fingerbank_score": md.get("fingerbank_score"),
            "mac_is_random": bool(md.get("mac_is_random", False)),
            "connection_type": md.get("connection_type"),  # lan|wifi|unknown
            "connection_source": md.get("connection_source"),
            "connection_via_switch": md.get("connection_via_switch"),
            "connection_via_port": md.get("connection_via_port"),
            "connection_confidence": md.get("connection_confidence"),
            "alerts_silenced": bool(md.get("alerts_silenced", False)),
            "alerts_silenced_reason": md.get("alerts_silenced_reason") or "",
            "created_at": md.get("created_at") or md.get("auto_added_at") or now_iso,
        })

    client_ids = list(set(d["client_id"] for d in devices if d.get("client_id")))
    clients = await db.clients.find({"id": {"$in": client_ids}}, {"_id": 0}).to_list(1000)
    client_map = {c["id"]: c["name"] for c in clients}
    device_ids = [d["id"] for d in devices if not d["id"].startswith("poll_")]
    creds = await db.device_credentials.find({"device_id": {"$in": device_ids}}, {"_id": 0, "device_id": 1}).to_list(1000)
    cred_device_ids = {c["device_id"] for c in creds}
    result = []
    for d in devices:
        d["client_name"] = client_map.get(d["client_id"], "")
        d["has_credentials"] = d["id"] in cred_device_ids
        try:
            result.append(DeviceResponse(**d))
        except Exception:
            result.append({
                "id": d["id"], "client_id": d.get("client_id", ""), "client_name": d.get("client_name", ""),
                "name": d.get("name", "?"), "device_type": d.get("device_type", ""), "ip_address": d.get("ip_address", ""),
                "hostname": d.get("hostname", ""), "location": d.get("location", ""), "status": d.get("status", "unknown"),
                "redfish_enabled": d.get("redfish_enabled", False), "has_credentials": d.get("has_credentials", False),
                "source": d.get("source", "manual"), "sys_descr": d.get("sys_descr", ""),
                "cpu_usage": d.get("cpu_usage"), "memory_usage": d.get("memory_usage"),
                "temperature": d.get("temperature"), "uptime": d.get("uptime", ""),
                "connector_hostname": d.get("connector_hostname", ""),
                "monitor_type": d.get("monitor_type", ""), "snmp_community": d.get("snmp_community", ""),
                "snmp_version": d.get("snmp_version", ""), "http_port": d.get("http_port"),
                "ping_ms": d.get("ping_ms"), "last_poll": d.get("last_poll"),
                # Web Console (auto-detected dal Connector tray)
                "web_console_url": d.get("web_console_url"),
                "web_console_port": d.get("web_console_port"),
                "web_console_scheme": d.get("web_console_scheme"),
                "web_console_title": d.get("web_console_title"),
                "profile_key": d.get("profile_key"),
                "vendor": d.get("vendor"),
                "family": d.get("family"),
                "alerts_silenced": d.get("alerts_silenced", False),
                "alerts_silenced_reason": d.get("alerts_silenced_reason", ""),
            })
    return result


@router.get("/devices/{device_id}", response_model=DeviceResponse)
async def get_device(device_id: str, current_user: dict = Depends(get_current_user)):
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    client = await db.clients.find_one({"id": device["client_id"]}, {"_id": 0})
    device["client_name"] = client["name"] if client else ""
    cred = await db.device_credentials.find_one({"device_id": device_id})
    device["has_credentials"] = cred is not None
    return DeviceResponse(**device)


@router.get("/devices/by-ip/{device_ip}/vendor-details")
async def device_vendor_details(device_ip: str, current_user: dict = Depends(get_current_user)):
    """Returns full vendor-specific telemetry (vendor_metrics + profile info) for a device.
    Used by the vendor-specific detail pages in the frontend.
    """
    ps = await db.device_poll_status.find_one({"device_ip": device_ip}, {"_id": 0})
    md = await db.managed_devices.find_one({"ip": device_ip}, {"_id": 0})
    if not ps and not md:
        raise HTTPException(status_code=404, detail="Device non trovato")

    profile_key = (md or {}).get("profile_key") or (ps or {}).get("profile_key")
    profile_data = None
    if profile_key:
        try:
            from device_profiles import get_profile
            profile_data = get_profile(profile_key)
        except Exception:
            profile_data = None

    return {
        "device_ip": device_ip,
        "name": (md or ps or {}).get("name") or (ps or {}).get("device_name") or device_ip,
        "profile_key": profile_key,
        "profile": {
            "vendor": (profile_data or {}).get("vendor"),
            "family": (profile_data or {}).get("family"),
            "label": (profile_data or {}).get("label"),
            "thresholds": (profile_data or {}).get("thresholds"),
        } if profile_data else None,
        "vendor_metrics": (ps or {}).get("vendor_metrics") or {},
        "cpu_usage": (ps or {}).get("cpu_usage"),
        "memory_usage": (ps or {}).get("memory_usage"),
        "temperature": (ps or {}).get("temperature"),
        "hardware": (ps or {}).get("hardware"),
        "last_poll": (ps or {}).get("last_poll"),
        "status": (ps or {}).get("status"),
    }


@router.post("/devices/{device_id}/credentials")
async def set_device_credentials(device_id: str, credentials: DeviceCredentials, current_user: dict = Depends(get_current_user)):
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    encrypted_username = security_manager.encrypt_credential(credentials.username)
    encrypted_password = security_manager.encrypt_credential(credentials.password)
    await db.device_credentials.update_one(
        {"device_id": device_id},
        {"$set": {
            "device_id": device_id,
            "username_encrypted": encrypted_username,
            "password_encrypted": encrypted_password,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": current_user["id"]
        }},
        upsert=True
    )
    await audit_logger.log(
        AuditAction.STORE_CREDENTIAL, user_id=current_user["id"], user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        resource_type="device_credential", resource_id=device_id,
        details={"device_name": device["name"]}
    )
    return {"message": "Credentials stored securely"}


@router.delete("/devices/{device_id}/credentials")
async def delete_device_credentials(device_id: str, current_user: dict = Depends(get_current_user)):
    await db.device_credentials.delete_one({"device_id": device_id})
    await audit_logger.log(
        AuditAction.DELETE_CREDENTIAL, user_id=current_user["id"], user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        resource_type="device_credential", resource_id=device_id
    )
    return {"message": "Credentials deleted"}


@router.post("/devices/{device_id}/test-redfish")
async def test_device_redfish(device_id: str, current_user: dict = Depends(get_current_user)):
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    cred = await db.device_credentials.find_one({"device_id": device_id}, {"_id": 0})
    if not cred:
        raise HTTPException(status_code=400, detail="No credentials stored")
    try:
        username = security_manager.decrypt_credential(cred["username_encrypted"])
        password = security_manager.decrypt_credential(cred["password_encrypted"])
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to decrypt credentials")
    result = await redfish_poller.test_connection(device["ip_address"], username, password)
    return result


@router.post("/devices/test-redfish")
async def test_redfish_connection(test: RedfishTestRequest, current_user: dict = Depends(get_current_user)):
    result = await redfish_poller.test_connection(test.ip_address, test.username, test.password)
    return result


@router.patch("/devices/{device_id}")
async def patch_device(device_id: str, payload: dict, current_user: dict = Depends(get_current_user)):
    """Aggiorna in modo selettivo i campi di un device (es. client_id, name).
    Pensato per cleanup multi-tenant: riassegnazione device a un cliente diverso.
    Whitelist dei campi modificabili - mai concedere update arbitrari da JSON."""
    device = await db.devices.find_one({"id": device_id}, {"_id": 0})
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    allowed = {"client_id", "name", "device_type", "ip_address", "hostname", "location", "status", "redfish_enabled"}
    updates = {k: v for k, v in payload.items() if k in allowed}
    if not updates:
        raise HTTPException(status_code=400, detail=f"No valid fields. Allowed: {sorted(allowed)}")

    # Se cambia client_id, verifica che il nuovo cliente esista
    if "client_id" in updates:
        target = await db.clients.find_one({"id": updates["client_id"]}, {"_id": 0, "id": 1, "name": 1})
        if not target:
            raise HTTPException(status_code=400, detail=f"Target client_id {updates['client_id']} not found")

    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    # Se l'utente sta cambiando il nome, blocca l'auto-promote dal connector
    # (sys_name SNMP) per evitare che sovrascriva la rinomina manuale.
    if "name" in updates and updates["name"] != device.get("name"):
        updates["name_user_locked"] = True
    await db.devices.update_one({"id": device_id}, {"$set": updates})
    # Cascade su managed_devices: stesso lock + nome aggiornato per coerenza UI
    if "name" in updates:
        try:
            await db.managed_devices.update_one(
                {"ip": device.get("ip_address")},
                {"$set": {
                    "device_name": updates["name"],
                    "name": updates["name"],
                    "name_user_locked": True,
                }},
            )
        except Exception:
            pass
    # Cascade update su collezioni correlate per coerenza multi-tenant
    if "client_id" in updates:
        try:
            await db.device_poll_status.update_many(
                {"device_ip": device.get("ip_address")},
                {"$set": {"client_id": updates["client_id"]}}
            )
            await db.managed_devices.update_many(
                {"ip": device.get("ip_address")},
                {"$set": {"client_id": updates["client_id"]}}
            )
        except Exception:
            pass

    await audit_logger.log(
        AuditAction.UPDATE_DEVICE if hasattr(AuditAction, "UPDATE_DEVICE") else AuditAction.CREATE_DEVICE,
        user_id=current_user["id"], user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        resource_type="device", resource_id=device_id,
        details={"patched_fields": list(updates.keys())}
    )
    updated = await db.devices.find_one({"id": device_id}, {"_id": 0})
    return updated


@router.delete("/devices/{device_id}")
async def delete_device(device_id: str, current_user: dict = Depends(get_current_user)):
    result = await db.devices.delete_one({"id": device_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Device not found")
    await db.device_credentials.delete_one({"device_id": device_id})
    await audit_logger.log(
        AuditAction.DELETE_DEVICE, user_id=current_user["id"], user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        resource_type="device", resource_id=device_id
    )
    return {"message": "Device deleted"}


# ============================================================================
# PROFILE RE-MATCH — forza fingerprint vendor su device gia` polled
# ============================================================================
# Caso d'uso: device ingestati prima che SNMP/sys_descr funzionassero; ora i
# metadati sono disponibili ma il matcher automatico non si ri-attiva (prev_status
# non-None). Questi endpoint permettono di ri-agganciare il profilo:
#  - singolo device via id O ip
#  - bulk su tutti i device di un cliente
# NON sovrascrive profili impostati manualmente dall'utente.


async def _rematch_one(client_id: str, device_ip: str) -> dict:
    """Esegue il fingerprint su un device usando sys_object_id/sys_descr correnti.

    Ritorna un dict con l'esito: {matched: bool, profile_key?, vendor?, skipped_reason?}.
    """
    ps = await db.device_poll_status.find_one(
        {"client_id": client_id, "device_ip": device_ip},
        {"_id": 0, "sys_descr": 1, "sys_object_id": 1, "profile_key": 1, "profile_auto_matched": 1},
    ) or {}
    md = await db.managed_devices.find_one(
        {"client_id": client_id, "ip": device_ip},
        {"_id": 0, "profile_key": 1, "name": 1},
    ) or {}

    # Skip: profilo manuale (utente ha scelto esplicitamente) → non sovrascrivere
    manual_profile = bool(md.get("profile_key")) and not ps.get("profile_auto_matched", False)
    if manual_profile:
        return {
            "device_ip": device_ip, "name": md.get("name"),
            "matched": False, "skipped_reason": "manual-profile",
            "current_profile_key": md.get("profile_key"),
        }

    sys_object_id = ps.get("sys_object_id")
    sys_descr = ps.get("sys_descr")
    if not sys_object_id and not sys_descr:
        return {
            "device_ip": device_ip, "name": md.get("name"),
            "matched": False, "skipped_reason": "no-identifier",
        }

    from device_profiles import fingerprint as _fp
    matched = _fp(sys_object_id, sys_descr)
    if not matched:
        return {
            "device_ip": device_ip, "name": md.get("name"),
            "matched": False, "skipped_reason": "no-match",
            "sys_object_id": sys_object_id,
        }

    from datetime import datetime, timezone as _tz
    now_iso = datetime.now(_tz.utc).isoformat()
    snmp = matched.get("snmp") or {}
    wc = matched.get("web_console") or {}

    await db.device_poll_status.update_one(
        {"client_id": client_id, "device_ip": device_ip},
        {"$set": {
            "profile_key": matched["key"],
            "vendor": matched["vendor"],
            "family": matched["family"],
            "profile_auto_matched": True,
            "profile_matched_at": now_iso,
        }},
    )
    # Aggiorna managed_device solo se non ha gia` un profilo manuale
    if md and not md.get("profile_key"):
        await db.managed_devices.update_one(
            {"client_id": client_id, "ip": device_ip},
            {"$set": {
                "profile_key": matched["key"],
                "vendor": matched["vendor"],
                "device_type": matched["family"],
                "snmp_port": snmp.get("port", 161),
                "snmp_version": snmp.get("version"),
                "web_console_port": wc.get("port"),
                "web_console_scheme": wc.get("scheme"),
            }},
        )
    return {
        "device_ip": device_ip, "name": md.get("name"),
        "matched": True,
        "profile_key": matched["key"],
        "vendor": matched["vendor"],
        "family": matched["family"],
    }


@router.post("/clients/{client_id}/rematch-profiles")
async def rematch_profiles_bulk(
    client_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Ri-esegue il fingerprint dei profili vendor su tutti i device del cliente.

    Utile quando lo SNMP ha iniziato a funzionare dopo l'ingest iniziale e
    i device non hanno piu` ricevuto auto-classificazione. NON sovrascrive
    profili impostati manualmente.

    Ritorna summary: {total, matched, skipped, details[]}.
    """
    # Controllo cliente esistente
    client = await db.clients.find_one({"id": client_id}, {"_id": 0, "name": 1})
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Unione IP da managed_devices + device_poll_status (copre device auto-discovered)
    ips: set[str] = set()
    async for d in db.managed_devices.find({"client_id": client_id}, {"_id": 0, "ip": 1}):
        if d.get("ip"):
            ips.add(d["ip"])
    async for d in db.device_poll_status.find({"client_id": client_id}, {"_id": 0, "device_ip": 1}):
        if d.get("device_ip"):
            ips.add(d["device_ip"])

    # v3.8.18: propagazione community SNMP corretta del cliente.
    # I device auto-censiti dallo Scanner partono con community="public" (default).
    # Calcolo la community piu' usata dai device che il Master polla con SUCCESSO
    # (device_poll_status.reachable=true) e la propago a tutti i managed_devices
    # del cliente che hanno ancora "public" o community vuota.
    from datetime import datetime as _dt2, timezone as _tz2
    now_iso2 = _dt2.now(_tz2.utc).isoformat()
    community_counter: dict[str, int] = {}
    async for pd in db.device_poll_status.find(
        {"client_id": client_id, "reachable": True},
        {"_id": 0, "snmp_community": 1, "community": 1},
    ):
        c = pd.get("snmp_community") or pd.get("community") or ""
        c = c.strip()
        if c and c.lower() != "public":
            community_counter[c] = community_counter.get(c, 0) + 1
    # Anche le community manuali in db.devices contano (admin le ha settate a mano)
    async for dv in db.devices.find(
        {"client_id": client_id},
        {"_id": 0, "snmp_community": 1},
    ):
        c = (dv.get("snmp_community") or "").strip()
        if c and c.lower() != "public":
            community_counter[c] = community_counter.get(c, 0) + 2  # peso doppio: scelta umana
    # Anche managed_devices con community gia' valorizzata != public
    async for md in db.managed_devices.find(
        {"client_id": client_id},
        {"_id": 0, "community": 1, "snmp_community": 1},
    ):
        c = (md.get("community") or md.get("snmp_community") or "").strip()
        if c and c.lower() != "public":
            community_counter[c] = community_counter.get(c, 0) + 1

    community_propagated = 0
    best_community = ""
    if community_counter:
        best_community = max(community_counter, key=community_counter.get)
        # Aggiorna i managed_devices con community=public (o vuota): il Master ritentera'
        # il poll col valore corretto al prossimo ciclo.
        upd = await db.managed_devices.update_many(
            {
                "client_id": client_id,
                "$or": [
                    {"community": {"$in": ["", "public", None]}},
                    {"community": {"$exists": False}},
                ],
            },
            {"$set": {
                "community": best_community,
                "snmp_community": best_community,
                "community_propagated_at": now_iso2,
                "community_propagated_from": "rematch-profiles bulk",
            }},
        )
        community_propagated = upd.modified_count

    details = []
    matched_count = 0
    skipped_count = 0
    for ip in sorted(ips):
        try:
            res = await _rematch_one(client_id, ip)
            details.append(res)
            if res.get("matched"):
                matched_count += 1
            else:
                skipped_count += 1
        except Exception as e:
            details.append({"device_ip": ip, "matched": False, "error": str(e)})
            skipped_count += 1

    await audit_logger.log(
        AuditAction.UPDATE_DEVICE, user_id=current_user["id"], user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        resource_type="client", resource_id=client_id,
        details={"action": "rematch_profiles_bulk", "total": len(ips), "matched": matched_count},
    )

    return {
        "client_id": client_id,
        "client_name": client.get("name"),
        "total": len(ips),
        "matched": matched_count,
        "skipped": skipped_count,
        "community_propagated": community_propagated,
        "community_used": best_community,
        "details": details,
    }


@router.post("/clients/{client_id}/devices/{device_ip}/rematch-profile")
async def rematch_profile_single(
    client_id: str,
    device_ip: str,
    current_user: dict = Depends(get_current_user),
):
    """Ri-esegue il fingerprint del profilo vendor su un singolo device."""
    res = await _rematch_one(client_id, device_ip)
    await audit_logger.log(
        AuditAction.UPDATE_DEVICE, user_id=current_user["id"], user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        resource_type="device", resource_id=device_ip,
        details={"action": "rematch_profile", "result": res},
    )
    return res


@router.post("/clients/{client_id}/devices/recognize-unknowns")
async def recognize_unknown_devices(
    client_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Ri-esegue il riconoscimento (OUI + Fingerbank + reverse-DNS) sui device
    auto-censiti dallo Scanner che hanno ancora vendor/nome generici (es. "192.168.x.y"
    senza vendor). Utile dopo che Fingerbank è stato configurato a posteriori, o per
    device il cui MAC è arrivato in un secondo momento.
    """
    import socket
    from datetime import datetime, timezone
    from routes.oui_lookup import lookup_oui, classify_device
    from services import fingerbank_service

    fb_configured = await fingerbank_service.is_configured()
    now_iso = datetime.now(timezone.utc).isoformat()

    # v3.8.16: detection MAC LAA (randomizzato per privacy).
    def _is_laa_mac(mac_normalized: str) -> bool:
        try:
            first_byte = int(mac_normalized.split(":")[0], 16)
            return bool(first_byte & 0x02)
        except Exception:
            return False

    # Pesca i device da rivedere: source=connector-scanner E (no vendor OR name=ip OR no fingerbank_at)
    candidates = await db.managed_devices.find(
        {
            "client_id": client_id,
            "source": "connector-scanner",
        },
        {"_id": 0, "id": 1, "ip": 1, "mac": 1, "vendor": 1, "name": 1,
         "hostname": 1, "fingerbank_at": 1, "device_type": 1, "sys_descr": 1,
         "mac_is_random": 1},
    ).to_list(2000)

    summary = {
        "total_scanned": 0,
        "oui_matched": 0,
        "fingerbank_matched": 0,
        "rdns_matched": 0,
        "private_mac_labeled": 0,
        "no_mac": 0,
        "skipped": 0,
    }

    for md in candidates:
        ip = md.get("ip")
        if not ip:
            continue
        # Salta device gia' completi (hanno vendor + name diverso da IP + fingerbank fatto)
        has_vendor = bool((md.get("vendor") or "").strip())
        has_decent_name = bool((md.get("name") or "").strip()) and md.get("name") != ip
        has_fb = bool(md.get("fingerbank_at"))
        if has_vendor and has_decent_name and (has_fb or not fb_configured):
            summary["skipped"] += 1
            continue
        summary["total_scanned"] += 1
        update: dict = {}

        mac_norm = (md.get("mac") or "").lower().replace("-", ":").strip()
        mac_valid = mac_norm and len(mac_norm.replace(":", "")) == 12
        mac_is_laa = mac_valid and _is_laa_mac(mac_norm)

        if mac_valid:
            if mac_is_laa:
                # MAC randomizzato → etichetta chiara, non chiamare OUI/Fingerbank
                update["mac_is_random"] = True
                if not has_vendor:
                    update["vendor"] = "MAC randomizzato (privacy)"
                if not has_decent_name:
                    update["name"] = f"Dispositivo personale {ip}"
                update["device_type"] = "endpoint-private"
                summary["private_mac_labeled"] += 1
            else:
                # OUI lookup classico
                if not has_vendor:
                    try:
                        v = lookup_oui(mac_norm) or ""
                        if v:
                            update["vendor"] = v
                            summary["oui_matched"] += 1
                            try:
                                update["device_type"] = classify_device(
                                    mac=mac_norm, vendor=v, sys_descr=md.get("sys_descr") or ""
                                ) or md.get("device_type") or "endpoint"
                            except Exception:
                                pass
                    except Exception:
                        pass
                # Fingerbank lookup (solo MAC reali)
                if fb_configured and not has_fb:
                    try:
                        fb = await fingerbank_service.interrogate(mac=mac_norm)
                        if fb and fb.get("device_name"):
                            update["fingerbank_device_name"] = fb["device_name"]
                            update["fingerbank_score"] = fb.get("score")
                            update["fingerbank_at"] = now_iso
                            summary["fingerbank_matched"] += 1
                    except Exception:
                        pass
        else:
            summary["no_mac"] += 1

        # Reverse DNS lookup (sempre tentato per device senza nome decente, anche LAA)
        if not has_decent_name and "name" not in update:
            try:
                old_to = socket.getdefaulttimeout()
                socket.setdefaulttimeout(2.0)
                try:
                    h, _, _ = socket.gethostbyaddr(ip)
                    if h and h != ip:
                        update["hostname"] = h
                        update["name"] = h.split(".")[0] if "." in h else h
                        summary["rdns_matched"] += 1
                finally:
                    socket.setdefaulttimeout(old_to)
            except Exception:
                pass

        # Se abbiamo trovato vendor ma name e' ancora ip, miglioriamo il name
        if "vendor" in update and not has_decent_name and "name" not in update:
            update["name"] = f"{update['vendor']} {ip}"

        if update:
            update["updated_at"] = now_iso
            await db.managed_devices.update_one(
                {"client_id": client_id, "ip": ip, "source": "connector-scanner"},
                {"$set": update},
            )

    await audit_logger.log(
        AuditAction.UPDATE_DEVICE, user_id=current_user["id"], user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        resource_type="client", resource_id=client_id,
        details={"action": "recognize_unknowns", "summary": summary},
    )
    return {
        "client_id": client_id,
        "fingerbank_configured": fb_configured,
        **summary,
    }


# v3.8.17: keyword-set per riconoscere se un LLDP neighbor remote_sys_name/desc
# rappresenta un Access Point WiFi vs uno switch/router cablato.
_AP_KEYWORDS = (
    "ap-", "ap_", " ap ", "wap", "wifi", "wi-fi", "wireless", "wlan",
    "aruba ap", "unifi ap", "uap", "meraki mr", "cisco air", "ruckus",
    "aerohive", "extreme ap", "mikrotik cap", "tp-link eap", "netgear wac",
    "engenius", "edgemax ap",
)


def _is_ap_neighbor(remote_sys_name: str, remote_sys_descr: str = "") -> bool:
    """Ritorna True se il neighbor LLDP/CDP è probabilmente un Access Point WiFi."""
    blob = f"{remote_sys_name or ''} {remote_sys_descr or ''}".lower()
    return any(k in blob for k in _AP_KEYWORDS)


@router.post("/clients/{client_id}/devices/correlate-connectivity")
async def correlate_connectivity(
    client_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Correla i device del cliente con la CAM table degli switch e i neighbor
    LLDP per stabilire se ogni device e' connesso via LAN (cavo) o Wi-Fi.

    Workflow:
    1. Per ogni managed_device con MAC valido del cliente.
    2. Cerca in `discovered_endpoints` (popolata dal Master via dot1dTpFdbTable)
       quale switch+port vede quel MAC.
    3. Risali in `switch_ports` per ottenere il nome porta (Gi1/0/5).
    4. Risali in `lldp_neighbors` per vedere se quella porta ha come neighbor
       un Access Point WiFi (matching keyword Aruba AP/Unifi/Meraki/AP-/WAP/...).
    5. Se neighbor=AP -> connection_type=wifi, altrimenti=lan.
    6. Fallback: se MAC non trovato in CAM E mac_is_random=True -> wifi (LAA).
    7. Altrimenti unknown.

    Salva su managed_devices: connection_type, connection_source,
    connection_via_switch, connection_via_port, connection_confidence.
    """
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()

    devices = await db.managed_devices.find(
        {"client_id": client_id},
        {"_id": 0, "id": 1, "ip": 1, "mac": 1, "mac_is_random": 1,
         "source": 1, "connection_type": 1},
    ).to_list(2000)

    # Index discovered_endpoints by MAC (uppercase as inserted by Master)
    cam_entries = await db.discovered_endpoints.find(
        {"client_id": client_id, "mac": {"$ne": ""}, "switch_ip": {"$ne": ""}},
        {"_id": 0, "mac": 1, "switch_ip": 1, "port": 1},
    ).to_list(20000)
    cam_by_mac: dict = {}
    for e in cam_entries:
        m = (e.get("mac") or "").upper().replace("-", ":")
        if m and len(m.replace(":", "")) == 12 and e.get("switch_ip"):
            cam_by_mac[m] = (e["switch_ip"], e.get("port", 0))

    # Index switch_ports for (switch_ip, idx) -> port_name
    sp_docs = await db.switch_ports.find(
        {"client_id": client_id},
        {"_id": 0, "local_ip": 1, "idx": 1, "name": 1},
    ).to_list(10000)
    port_name_by_key: dict = {}
    for sp in sp_docs:
        if sp.get("local_ip") and sp.get("idx") is not None:
            port_name_by_key[(sp["local_ip"], int(sp["idx"]))] = sp.get("name", "")

    # Index lldp_neighbors by (switch_ip, port_id_or_desc)
    lldp_docs = await db.lldp_neighbors.find(
        {"client_id": client_id},
        {"_id": 0, "local_ip": 1, "local_port_id": 1, "local_port_desc": 1,
         "remote_sys_name": 1, "remote_sys_descr": 1, "remote_chassis_id": 1},
    ).to_list(5000)
    lldp_by_port: dict = {}
    # Set di MAC che sono "device LLDP" stesso (AP/switch/IP-Phone neighbor)
    # → quei MAC sono dispositivi CABLATI (l'AP usa l'ethernet uplink, non e' un client WiFi).
    lldp_chassis_macs: set = set()

    def _normalize_chassis_to_mac(chassis: str) -> str:
        if not chassis:
            return ""
        # Cisco format: aabb.ccdd.eeff -> aabbccddeeff -> aa:bb:cc:dd:ee:ff
        cleaned = "".join(c for c in chassis.lower() if c in "0123456789abcdef")
        if len(cleaned) == 12:
            return ":".join(cleaned[i:i+2] for i in range(0, 12, 2)).upper()
        return ""

    for ln in lldp_docs:
        for pkey in (ln.get("local_port_id"), ln.get("local_port_desc")):
            if ln.get("local_ip") and pkey:
                lldp_by_port[(ln["local_ip"], str(pkey))] = ln
        chassis_mac = _normalize_chassis_to_mac(ln.get("remote_chassis_id", ""))
        if chassis_mac:
            lldp_chassis_macs.add(chassis_mac)

    summary = {
        "total_devices": len(devices),
        "lan_count": 0,
        "wifi_count": 0,
        "unknown_count": 0,
        "skipped_no_mac": 0,
        "via_lldp_ap": 0,
        "via_cam_lan": 0,
        "via_laa_inference": 0,
    }

    for d in devices:
        mac_norm = (d.get("mac") or "").upper().replace("-", ":").strip()
        if not mac_norm or len(mac_norm.replace(":", "")) != 12:
            summary["skipped_no_mac"] += 1
            # se non abbiamo MAC ma source e' connector-scanner, segna unknown
            await db.managed_devices.update_one(
                {"client_id": client_id, "id": d["id"]},
                {"$set": {
                    "connection_type": "unknown",
                    "connection_source": "no_mac",
                    "connection_correlated_at": now_iso,
                }},
            )
            continue

        ctype = "unknown"
        csource = "no_data"
        via_switch = ""
        via_port = ""
        confidence = 0  # 0-100

        cam_hit = cam_by_mac.get(mac_norm)
        if cam_hit:
            sw_ip, port_idx = cam_hit
            port_name = port_name_by_key.get((sw_ip, port_idx), str(port_idx))
            ln = lldp_by_port.get((sw_ip, port_name)) or lldp_by_port.get((sw_ip, str(port_idx)))
            via_switch = sw_ip
            via_port = port_name or str(port_idx)
            # v3.8.17: se il device E' lui stesso un LLDP neighbor (AP/IP-Phone/switch),
            # allora e' CABLATO per definizione (LLDP gira solo su Ethernet).
            if mac_norm in lldp_chassis_macs:
                ctype = "lan"
                csource = "self_is_lldp_device"
                confidence = 99
                summary["via_cam_lan"] += 1
            elif ln and _is_ap_neighbor(ln.get("remote_sys_name", ""), ln.get("remote_sys_descr", "")):
                ctype = "wifi"
                csource = f"lldp:ap={ln.get('remote_sys_name','?')}"
                confidence = 95
                summary["via_lldp_ap"] += 1
            else:
                ctype = "lan"
                csource = "cam_table"
                confidence = 90
                summary["via_cam_lan"] += 1
        else:
            # MAC non in CAM table del Master
            if d.get("mac_is_random"):
                ctype = "wifi"
                csource = "laa_inference"  # MAC randomizzato e' tipicamente Wi-Fi privacy
                confidence = 75
                summary["via_laa_inference"] += 1
            else:
                ctype = "unknown"
                csource = "no_cam_match"
                confidence = 0

        summary[f"{ctype}_count"] += 1

        await db.managed_devices.update_one(
            {"client_id": client_id, "id": d["id"]},
            {"$set": {
                "connection_type": ctype,
                "connection_source": csource,
                "connection_via_switch": via_switch,
                "connection_via_port": via_port,
                "connection_confidence": confidence,
                "connection_correlated_at": now_iso,
            }},
        )

    await audit_logger.log(
        AuditAction.UPDATE_DEVICE, user_id=current_user["id"], user_email=current_user["email"],
        ip_address=current_user.get("_request_ip"),
        resource_type="client", resource_id=client_id,
        details={"action": "correlate_connectivity", "summary": summary},
    )
    return {"client_id": client_id, **summary}



@router.get("/clients/{client_id}/ilo-health")
async def get_client_ilo_health(client_id: str, current_user: dict = Depends(get_current_user)):
    """Return Redfish/iLO hardware telemetry for all iLO servers of a client."""
    # Fetch poll_status docs that contain actual Redfish data (not null/empty)
    docs = await db.device_poll_status.find(
        {
            "client_id": client_id,
            "$or": [
                {"device_class": "hpe-ilo"},
                {"redfish.server_model": {"$nin": [None, ""]}},
                {"redfish.bios_version": {"$nin": [None, ""]}},
                {"monitor_type": "redfish_direct"},
            ],
        },
        {"_id": 0}
    ).to_list(100)
    # Resolve managed_device names for display
    managed = await db.managed_devices.find(
        {"client_id": client_id}, {"_id": 0, "ip": 1, "name": 1}
    ).to_list(200)
    name_map = {m["ip"]: m.get("name") for m in managed}
    result = []
    for d in docs:
        ip = d.get("device_ip")
        rf = d.get("redfish", {}) or {}
        hw = d.get("hardware", {}) or {}
        result.append({
            "device_ip": ip,
            "device_name": name_map.get(ip) or d.get("device_name") or ip,
            "polling_mode": d.get("monitor_type", "unknown"),
            "last_poll": d.get("last_poll"),
            "reachable": d.get("reachable", False),
            "server_model": rf.get("server_model"),
            "serial_number": rf.get("serial_number"),
            "bios_version": rf.get("bios_version"),
            "ilo_firmware": rf.get("ilo_firmware"),
            "ilo_license": rf.get("ilo_license"),
            "power_watts": rf.get("power_watts"),
            "total_memory_gb": rf.get("total_memory_gb"),
            "memory_dimms": rf.get("memory_dimms", []),
            "network_adapters": rf.get("network_adapters", []),
            "storage_controllers": rf.get("storage_controllers", []),
            "health_status": hw.get("health_status"),
            "temperatures": hw.get("temperatures", []),
            "fans": hw.get("fans", []),
            "power_supplies": hw.get("power_supplies", []),
        })
    return result
