"""Memoria porte — azioni utente.

POST /api/devices/{switch_ip}/switch-ports/{idx}/authorize-device?client_id=
  → il cambio dispositivo è autorizzato: chiude l'alert port_device_change, la memoria impara il nuovo
    device (entra in `authorized_devices`, così non rialerta se ricompare) e sparisce il badge CAMBIATO.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from database import db
from deps import get_current_user, require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/devices", tags=["port-memory"])


class AuthorizeBody(BaseModel):
    note: Optional[str] = None


@router.post("/{device_ip}/switch-ports/{idx}/authorize-device")
async def authorize_port_device(device_ip: str, idx: int, body: AuthorizeBody = None, client_id: str = None,
                                current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    from .tenant_scope import resolve_device_client_id
    cid = await resolve_device_client_id(device_ip, client_id)
    if not cid:
        raise HTTPException(status_code=404, detail="Switch non trovato")
    q = {"client_id": cid, "local_ip": device_ip, "idx": idx}
    mem = await db.port_memory.find_one(q, {"_id": 0, "last_device": 1, "prev_device": 1, "authorized_devices": 1})
    if not mem:
        raise HTTPException(status_code=404, detail="Nessuna memoria per questa porta")
    now = datetime.now(timezone.utc).isoformat()
    who = current_user.get("email")
    auth = {a["mac"]: a for a in (mem.get("authorized_devices") or []) if a.get("mac")}
    for d in (mem.get("last_device"), mem.get("prev_device")):
        if d and d.get("mac"):
            auth[d["mac"]] = {"mac": d["mac"], "ip": d.get("ip") or "", "name": d.get("name") or "", "by": who, "at": now,
                              "note": (body.note if body else None) or ""}
    await db.port_memory.update_one(q, {"$set": {"authorized_devices": list(auth.values())[-20:], "device_authorized_at": now},
                                        "$unset": {"prev_device": "", "device_changed_at": ""}})
    res = await db.alerts.update_many(
        {"client_id": cid, "device_ip": device_ip, "source_type": "port_device_change", "raw_data.idx": idx,
         "status": {"$in": ["active", "acknowledged"]}},
        {"$set": {"status": "resolved", "resolved_at": now, "resolved_by": who, "resolution_reason": "manual",
                  "resolution_note": f"Cambio dispositivo autorizzato da {who}" + (f": {body.note}" if body and body.note else "")}})
    logger.info("port device authorized %s:%s by %s (alerts closed=%s)", device_ip, idx, who, res.modified_count)
    return {"ok": True, "alerts_closed": res.modified_count, "authorized_devices": list(auth.values())}
