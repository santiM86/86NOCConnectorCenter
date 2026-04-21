"""
CMDB (Configuration Management Database) — asset inventory strutturato.
Ogni device puo' avere un record arricchito con vendor, contratto, garanzia,
responsabile interno, posizione, ciclo vita. Alerts/incident linkano qui
per "di chi e' sta cosa".
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone
import uuid
import logging

from database import db
from deps import get_current_user

router = APIRouter(prefix="/api/cmdb", tags=["cmdb"])
audit = logging.getLogger("audit")


class CMDBAsset(BaseModel):
    device_ip: str
    client_id: Optional[str] = None
    vendor: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    firmware: Optional[str] = None
    purchase_date: Optional[str] = None
    warranty_end: Optional[str] = None
    support_contract: Optional[str] = None
    support_expires: Optional[str] = None
    location: Optional[str] = None
    rack: Optional[str] = None
    responsible_user: Optional[str] = None
    lifecycle_state: Optional[str] = Field(default="production", description="production|staging|retired|spare")
    tags: List[str] = []
    notes: Optional[str] = None


@router.get("/assets")
async def list_assets(client_id: Optional[str] = None, lifecycle: Optional[str] = None,
                      current_user: dict = Depends(get_current_user)):
    q = {}
    if client_id:
        q["client_id"] = client_id
    if lifecycle:
        q["lifecycle_state"] = lifecycle
    cursor = db.cmdb_assets.find(q, {"_id": 0}).sort("updated_at", -1).limit(500)
    items = [d async for d in cursor]
    return {"items": items}


@router.get("/assets/{device_ip}")
async def get_asset(device_ip: str, current_user: dict = Depends(get_current_user)):
    doc = await db.cmdb_assets.find_one({"device_ip": device_ip}, {"_id": 0})
    # Arricchisci con managed_device
    md = await db.managed_devices.find_one({"ip": device_ip}, {"_id": 0})
    return {"asset": doc, "managed_device": md}


@router.post("/assets")
async def upsert_asset(asset: CMDBAsset, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "superadmin", "operator"):
        raise HTTPException(status_code=403, detail="Permission denied")
    now = datetime.now(timezone.utc)
    data = asset.model_dump()
    data["updated_at"] = now
    data["updated_by"] = current_user.get("email")
    await db.cmdb_assets.update_one(
        {"device_ip": asset.device_ip},
        {"$set": data, "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": now}},
        upsert=True
    )
    audit.info(f"[AUDIT] cmdb_upsert | user={current_user.get('email')} | device={asset.device_ip}")
    return {"ok": True, "device_ip": asset.device_ip}


@router.delete("/assets/{device_ip}")
async def delete_asset(device_ip: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin only")
    res = await db.cmdb_assets.delete_one({"device_ip": device_ip})
    audit.info(f"[AUDIT] cmdb_delete | user={current_user.get('email')} | device={device_ip}")
    return {"deleted": res.deleted_count > 0}


@router.get("/autofill/{device_ip}")
async def autofill_from_telemetry(device_ip: str, current_user: dict = Depends(get_current_user)):
    """Pre-compila i campi CMDB pescando da iLO telemetry / device_poll_status / ilo_status.
    Utile per "Nuovo asset" con import automatico dei dati gia' conosciuti.
    """
    # Sources in priority order
    snap = await db.ilo_telemetry.find_one({"device_ip": device_ip}, {"_id": 0}, sort=[("timestamp", -1)])
    dps = await db.device_poll_status.find_one({"device_ip": device_ip}, {"_id": 0})
    stat = await db.ilo_status.find_one({"device_ip": device_ip}, {"_id": 0})
    cred = await db.device_credentials.find_one({"device_ip": device_ip}, {"_id": 0})

    sources = [snap or {}, (dps or {}).get("redfish") or {}, stat or {}]

    def pick(*keys):
        for s in sources:
            for k in keys:
                v = s.get(k)
                if v not in (None, ""):
                    return v
        return None

    vendor = None
    model = pick("server_model", "model")
    if model:
        mlow = model.lower()
        if "proliant" in mlow or "hpe" in mlow or "hp " in mlow:
            vendor = "HPE"
        elif "poweredge" in mlow or "dell" in mlow:
            vendor = "Dell"
        elif "thinksystem" in mlow or "lenovo" in mlow:
            vendor = "Lenovo"
        elif "cisco" in mlow:
            vendor = "Cisco"

    ilo_fw = pick("ilo_firmware")
    bios_fw = pick("bios_version")
    firmware = None
    if ilo_fw or bios_fw:
        firmware = f"iLO {ilo_fw}" if ilo_fw else ""
        if bios_fw:
            firmware = (firmware + " · " if firmware else "") + f"BIOS {bios_fw}"

    # client_id lookup: credential e' la fonte piu' affidabile
    client_id = None
    client_name = None
    if cred:
        client_id = cred.get("client_id")
    if not client_id and dps:
        client_id = dps.get("client_id")
    if client_id:
        cl = await db.clients.find_one({"id": client_id}, {"_id": 0, "name": 1})
        if cl:
            client_name = cl.get("name")

    payload = {
        "device_ip": device_ip,
        "device_name": pick("device_name") or (cred or {}).get("device_name"),
        "vendor": vendor,
        "model": model,
        "serial_number": pick("serial_number"),
        "firmware": firmware,
        "client_id": client_id,
        "client_name": client_name,
        "source": "ilo_telemetry" if snap else ("device_poll_status" if dps else "ilo_status" if stat else "credentials_only"),
        "has_data": bool(vendor or model or pick("serial_number") or firmware),
    }
    return payload


@router.get("/candidates")
async def monitored_devices_candidates(current_user: dict = Depends(get_current_user)):
    """Lista dei device gia' monitorati (credenziali iLO in Vault o telemetry attiva)
    non ancora presenti in CMDB. Permette di popolare il CMDB con un click.
    """
    in_cmdb = set(await db.cmdb_assets.distinct("device_ip"))
    creds = await db.device_credentials.find(
        {"credential_type": {"$in": ["ilo", "redfish", "snmp"]}},
        {"_id": 0, "device_ip": 1, "device_name": 1, "client_id": 1}
    ).to_list(500)
    candidates = []
    for c in creds:
        ip = c.get("device_ip")
        if not ip or ip in in_cmdb:
            continue
        candidates.append({"device_ip": ip, "device_name": c.get("device_name"), "client_id": c.get("client_id")})
    return {"items": candidates, "total": len(candidates)}



@router.get("/warranty-alerts")
async def warranty_alerts(days_ahead: int = 60, current_user: dict = Depends(get_current_user)):
    """Device con garanzia/contratto in scadenza nei prossimi N giorni."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) + timedelta(days=days_ahead)).isoformat()[:10]
    cursor = db.cmdb_assets.find(
        {"$or": [
            {"warranty_end": {"$lte": cutoff, "$ne": None}},
            {"support_expires": {"$lte": cutoff, "$ne": None}},
        ]},
        {"_id": 0}
    ).sort("warranty_end", 1).limit(200)
    items = [d async for d in cursor]
    return {"items": items, "cutoff_date": cutoff}
