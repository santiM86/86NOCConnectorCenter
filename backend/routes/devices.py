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
                "last_poll": pd.get("last_poll"),
                "sys_descr": pd.get("sys_descr", ""),
                "cpu_usage": pd.get("cpu_usage"),
                "uptime": pd.get("uptime"),
                "ports": pd.get("ports"),
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
            # Connector devices may have extra fields, use dict directly
            result.append({
                "id": d["id"], "client_id": d.get("client_id", ""), "client_name": d.get("client_name", ""),
                "name": d.get("name", "?"), "device_type": d.get("device_type", ""), "ip_address": d.get("ip_address", ""),
                "hostname": d.get("hostname", ""), "location": d.get("location", ""), "status": d.get("status", "unknown"),
                "redfish_enabled": d.get("redfish_enabled", False), "has_credentials": d.get("has_credentials", False),
                "source": d.get("source", "manual"), "sys_descr": d.get("sys_descr", ""),
                "cpu_usage": d.get("cpu_usage"), "uptime": d.get("uptime"),
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
