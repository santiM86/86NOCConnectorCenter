"""Traffic Anomaly Detection API routes."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from database import db
from deps import get_current_user, require_admin
from services import traffic_anomaly as ta

router = APIRouter(prefix="/api/security/traffic", tags=["traffic-anomaly"])


class ConfigPatch(BaseModel):
    enabled: Optional[bool] = None
    spike_factor: Optional[float] = None
    floor_mbps: Optional[float] = None
    warmup: Optional[int] = None
    severity: Optional[str] = None


@router.get("/status")
async def status(current_user: dict = Depends(get_current_user)):
    return await ta.get_status()


@router.put("/config")
async def update_config(patch: ConfigPatch, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    cfg = await ta.set_config(patch.model_dump(exclude_none=True))
    return {"ok": True, "config": cfg}


@router.post("/scan")
async def scan_now(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    return {"ok": True, "result": await ta.scan_all()}


@router.get("/alerts")
async def anomaly_alerts(
    client_id: Optional[str] = None,
    status_filter: Optional[str] = "active",
    limit: int = 200,
    current_user: dict = Depends(get_current_user),
):
    q: dict = {"source_type": "traffic_anomaly"}
    if client_id:
        q["client_id"] = client_id
    if status_filter and status_filter != "all":
        q["status"] = status_filter
    items = await db.alerts.find(q, {"_id": 0}).sort("created_at", -1).to_list(min(limit, 1000))
    cids = list({i.get("client_id") for i in items if i.get("client_id")})
    clients = await db.clients.find({"id": {"$in": cids}}, {"_id": 0, "id": 1, "name": 1}).to_list(1000)
    cmap = {c["id"]: c["name"] for c in clients}
    for i in items:
        i["client_name"] = cmap.get(i.get("client_id"), "")
    return {"total": len(items), "items": items}
