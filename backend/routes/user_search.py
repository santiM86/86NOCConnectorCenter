"""Cerca utente: 'dov'e' Mario?' → PC (Datto RMM ultimo utente) + switch/porta dove e' collegato."""
from __future__ import annotations

import json
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from database import db
from deps import get_current_user
from security import security_manager

router = APIRouter(prefix="/api", tags=["user-search"])


async def _backfill_last_user(limit: int = 3000) -> None:
    """Device sincronizzati prima del campo last_user: lo ricava una volta dal blob cifrato."""
    async for d in db.datto_devices.find({"last_user": {"$exists": False}, "raw_enc": {"$nin": [None, ""]}},
                                         {"_id": 1, "raw_enc": 1}).limit(limit):
        try:
            lst = (json.loads(security_manager.decrypt_credential(d["raw_enc"])) or {}).get("list") or {}
            user = (lst.get("lastLoggedInUser") or "").strip()
        except Exception:
            user = ""
        await db.datto_devices.update_one({"_id": d["_id"]}, {"$set": {"last_user": user}})


async def _locate(client_id: str, macs: set, ips: set) -> Optional[dict]:
    ors = []
    if macs:
        ors.append({"mac": {"$in": list(macs)}})
    if ips:
        ors.append({"ip": {"$in": list(ips)}})
    if not ors:
        return None
    ep = await db.discovered_endpoints.find_one(
        {"client_id": client_id, "switch_ip": {"$nin": [None, ""]}, "port": {"$ne": None}, "$or": ors},
        {"_id": 0, "switch_ip": 1, "port": 1, "mac": 1, "ip": 1, "last_seen_at": 1}, sort=[("last_seen_at", -1)])
    if not ep:
        return None
    sw = await db.managed_devices.find_one({"client_id": client_id, "$or": [{"ip": ep["switch_ip"]}, {"ip_address": ep["switch_ip"]}]},
                                           {"_id": 0, "name": 1, "device_name": 1, "hostname": 1})
    try:
        idx = int(ep["port"])
    except Exception:
        idx = None
    pm = await db.port_memory.find_one({"client_id": client_id, "local_ip": ep["switch_ip"], "idx": idx}, {"_id": 0, "name": 1}) if idx is not None else None
    return {"switch_ip": ep["switch_ip"], "switch_name": (sw or {}).get("name") or (sw or {}).get("device_name") or (sw or {}).get("hostname") or ep["switch_ip"],
            "port": idx, "port_name": (pm or {}).get("name") or "", "mac": ep.get("mac"), "seen_at": ep.get("last_seen_at")}


@router.get("/datto/user-search")
async def user_search(q: str, current_user: dict = Depends(get_current_user)):
    q = (q or "").strip()
    if len(q) < 2:
        raise HTTPException(400, "Scrivi almeno 2 caratteri")
    await _backfill_last_user()
    rx = {"$regex": re.escape(q), "$options": "i"}
    devs = await db.datto_devices.find({"last_user": rx}, {"_id": 0, "client_id": 1, "uid": 1, "name": 1, "ip": 1, "ip_list": 1, "mac": 1,
                                                          "mac_list": 1, "online": 1, "last_user": 1}).limit(50).to_list(50)
    client_names = {c["id"]: c.get("name") async for c in db.clients.find({"id": {"$in": list({d["client_id"] for d in devs})}}, {"_id": 0, "id": 1, "name": 1})}
    out = []
    for d in devs:
        macs = {m for m in (d.get("mac_list") or []) + [d.get("mac")] if m}
        async for lk in db.datto_mac_links.find({"client_id": d["client_id"], "datto_uid": d.get("uid")}, {"_id": 0, "mac": 1}):
            macs.add(lk["mac"])
        ips = {i for i in (d.get("ip_list") or []) + [d.get("ip")] if i}
        out.append({
            "client_id": d["client_id"], "client_name": client_names.get(d["client_id"]) or d["client_id"],
            "pc_name": d.get("name") or "", "pc_ip": d.get("ip") or "", "online": d.get("online"), "user": d.get("last_user") or "",
            "location": await _locate(d["client_id"], macs, ips),
        })
    out.sort(key=lambda r: (r["online"] is not True, r["location"] is None, r["pc_name"].lower()))
    return {"query": q, "results": out}
