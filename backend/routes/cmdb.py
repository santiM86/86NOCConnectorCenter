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
