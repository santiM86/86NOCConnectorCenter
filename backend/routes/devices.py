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
                "source": "connector",
                "connector_hostname": pd.get("connector_hostname", ""),
                "last_poll": pd.get("last_poll"),
                "sys_descr": pd.get("sys_descr", ""),
                "cpu_usage": pd.get("cpu_usage"),
                "memory_usage": pd.get("memory_usage"),
                "temperature": pd.get("temperature"),
                "uptime": pd.get("sys_uptime") or pd.get("uptime", ""),
                "ports": pd.get("ports"),
                "monitor_type": md.get("monitor_type") or pd.get("monitor_type", ""),
                "snmp_community": md.get("community", ""),
                "snmp_version": md.get("snmp_version", ""),
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
            })

    # 3rd pass: managed_devices orfani (aggiunti manualmente via UI o dal tray
    # Apri Web UI, ma non ancora pollati dal connector) - altrimenti sparirebbero
    # dalla UI del cliente finche' il connector non li vede.
    for md in managed_devices_raw:
        md_ip = md.get("ip") or md.get("ip_address", "")
        if not md_ip or md_ip in manual_ips:
            continue
        manual_ips.add(md_ip)
        devices.append({
            "id": md.get("id") or f"md_{md_ip.replace('.','_')}",
            "client_id": md.get("client_id", ""),
            "name": md.get("name", md_ip),
            "device_type": md.get("device_type", "server"),
            "ip_address": md_ip,
            "hostname": md.get("hostname", ""),
            "location": md.get("location", ""),
            "status": "pending",  # non ancora pollato
            "redfish_enabled": False,
            "source": "managed",
            "last_poll": md.get("web_console_last_tested"),
            "monitor_type": md.get("monitor_type", ""),
            "snmp_community": md.get("community", ""),
            "snmp_version": md.get("snmp_version", ""),
            "http_port": md.get("http_port"),
            "web_console_url": md.get("web_console_url"),
            "web_console_port": md.get("web_console_port"),
            "web_console_scheme": md.get("web_console_scheme"),
            "web_console_title": md.get("web_console_title"),
            "profile_key": md.get("profile_key"),
            "vendor": md.get("vendor"),
            "family": md.get("family"),
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
