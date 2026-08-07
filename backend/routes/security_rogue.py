"""Rogue / New Device Detection API routes."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from database import db
from deps import get_current_user, require_admin
from services import rogue_detection as rogue

router = APIRouter(prefix="/api/security/rogue", tags=["rogue-detection"])


class ConfigPatch(BaseModel):
    enabled: Optional[bool] = None
    severity: Optional[str] = None


class AuthorizeReq(BaseModel):
    client_id: str
    mac: str = Field(..., min_length=6)
    note: str = ""


class AllowlistDelReq(BaseModel):
    client_id: str
    mac: str


@router.get("/status")
async def status(current_user: dict = Depends(get_current_user)):
    return await rogue.get_status()


@router.put("/config")
async def update_config(patch: ConfigPatch, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    if patch.severity is not None and patch.severity not in rogue.VALID_SEVERITIES:
        raise HTTPException(400, f"Severity non valida: {patch.severity}")
    cfg = await rogue.set_config(patch.model_dump(exclude_none=True))
    return {"ok": True, "config": cfg}


@router.get("/alerts")
async def rogue_alerts(
    client_id: Optional[str] = None,
    status_filter: Optional[str] = "active",
    limit: int = 200,
    current_user: dict = Depends(get_current_user),
):
    q: dict = {"source_type": "rogue_device"}
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


@router.post("/scan")
async def scan_now(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    return {"ok": True, "result": await rogue.scan_all()}


@router.post("/authorize")
async def authorize(req: AuthorizeReq, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    res = await rogue.authorize(req.client_id, req.mac, current_user.get("email", ""), req.note)
    return {"ok": True, **res}


@router.get("/allowlist")
async def allowlist(client_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    items = await rogue.list_allowlist(client_id)
    cids = list({i.get("client_id") for i in items if i.get("client_id")})
    clients = await db.clients.find({"id": {"$in": cids}}, {"_id": 0, "id": 1, "name": 1}).to_list(1000)
    cmap = {c["id"]: c["name"] for c in clients}
    for i in items:
        i["client_name"] = cmap.get(i.get("client_id"), "")
    return {"total": len(items), "items": items}


@router.delete("/allowlist")
async def del_allowlist(req: AllowlistDelReq, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    deleted = await rogue.remove_from_allowlist(req.client_id, req.mac)
    return {"ok": True, "deleted": deleted}


@router.get("/remediation/{alert_id}")
async def remediation(alert_id: str, current_user: dict = Depends(get_current_user)):
    """Guida di isolamento (remediation) per un alert rogue. NB: azione manuale —
    l'agent non esegue ancora SNMP-SET, quindi forniamo i passi, non l'esecuzione."""
    a = await db.alerts.find_one({"id": alert_id, "source_type": "rogue_device"}, {"_id": 0})
    if not a:
        raise HTTPException(404, "Alert rogue non trovato")
    sw = a.get("rogue_switch_ip")
    port = a.get("rogue_port_name") or (f"index {a.get('rogue_port')}" if a.get("rogue_port") else None)
    steps = [
        f"Identifica il dispositivo: MAC {a.get('raw_data')}"
        + (f" (vendor {a.get('rogue_vendor')})" if a.get("rogue_vendor") else "")
        + (f", IP {a.get('device_ip')}" if a.get("device_ip") else "") + ".",
    ]
    if sw and port:
        steps.append(f"Sullo switch {sw}, individua la porta {port} a cui è connesso il MAC.")
        steps.append(f"Metti la porta in shutdown/admin-down per isolare il dispositivo "
                     f"(es. Cisco: 'interface {port}' → 'shutdown'; HPE/Comware: 'interface {port}' → 'shutdown').")
    else:
        steps.append("Localizza la porta di accesso del dispositivo (via tabella MAC dello switch, "
                     "'show mac address-table | include <MAC>').")
        steps.append("Metti la porta in shutdown/admin-down per isolare il dispositivo.")
    steps.append("In alternativa, sposta la porta su una VLAN di quarantena o applica un blocco 802.1X.")
    steps.append("Quando verificato, se legittimo usa 'Autorizza' per non ricevere più l'alert.")
    return {
        "alert_id": alert_id,
        "mac": a.get("raw_data"),
        "switch_ip": sw,
        "port": port,
        "auto_executable": False,
        "note": "Isolamento manuale: l'agent non dispone ancora di comando SNMP-SET per lo shutdown porta.",
        "steps": steps,
    }
