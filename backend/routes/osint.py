"""OSINT / Threat Intelligence API routes."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from database import db
from deps import get_current_user, require_admin
from services import osint_service as osint

logger = logging.getLogger("osint.routes")

router = APIRouter(prefix="/api/osint", tags=["osint"])


class KeyRequest(BaseModel):
    api_key: str = Field(..., min_length=6, max_length=512)


@router.get("/status")
async def status(current_user: dict = Depends(get_current_user)):
    """Stato generale: feed, conteggi IOC/KEV/exposure, chiavi configurate.
    Sola lettura: accessibile a qualsiasi utente autenticato (admin/operator/viewer)."""
    return await osint.get_status()


@router.put("/keys/{provider}")
async def set_key(provider: str, payload: KeyRequest, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    try:
        await osint.set_api_key(provider, payload.api_key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "keys": await osint.keys_status()}


@router.delete("/keys/{provider}")
async def delete_key(provider: str, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    if provider not in osint.KEYED_PROVIDERS:
        raise HTTPException(status_code=400, detail="Provider non valido")
    deleted = await osint.delete_api_key(provider)
    return {"ok": True, "deleted": deleted}


@router.post("/refresh")
async def refresh(current_user: dict = Depends(get_current_user)):
    """Forza il refresh immediato di tutti i feed globali."""
    require_admin(current_user)
    res = await osint.refresh_all_feeds(force=True)
    return {"ok": True, "results": res, "status": await osint.get_status()}


@router.get("/lookup/{ip}")
async def lookup(ip: str, current_user: dict = Depends(get_current_user)):
    """Arricchimento on-demand di un IP pubblico (IOC locali + AbuseIPDB + GreyNoise + InternetDB + KEV)."""
    try:
        return await osint.lookup_ip(ip)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/kev")
async def list_kev(
    q: Optional[str] = None, limit: int = 100,
    current_user: dict = Depends(get_current_user),
):
    """Catalogo CISA KEV (CVE attivamente sfruttate), ricercabile."""
    query: dict = {}
    if q:
        query["$or"] = [
            {"cve_id": {"$regex": q, "$options": "i"}},
            {"vendor": {"$regex": q, "$options": "i"}},
            {"product": {"$regex": q, "$options": "i"}},
            {"name": {"$regex": q, "$options": "i"}},
            {"short_description": {"$regex": q, "$options": "i"}},
        ]
    items = await db.cisa_kev.find(query, {"_id": 0}).sort("date_added", -1).to_list(min(limit, 500))
    return {"total": len(items), "items": items}


@router.get("/exposure")
async def exposure(
    client_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """Findings di esposizione (Shodan InternetDB) sugli IP pubblici monitorati.
    Filtrabile per cliente (isolamento multi-tenant)."""
    query: dict = {}
    if client_id:
        query["client_id"] = client_id
    items = await db.osint_exposure.find(query, {"_id": 0}).sort("kev_count", -1).to_list(1000)
    client_ids = list({i.get("client_id") for i in items if i.get("client_id")})
    clients = await db.clients.find({"id": {"$in": client_ids}}, {"_id": 0, "id": 1, "name": 1}).to_list(1000)
    cmap = {c["id"]: c["name"] for c in clients}
    for i in items:
        i["client_name"] = cmap.get(i.get("client_id"), "")
    return {"total": len(items), "items": items}


@router.post("/c2-scan")
async def c2_scan(current_user: dict = Depends(get_current_user)):
    """Esegue subito la correlazione C2 sui syslog recenti (trigger manuale, admin)."""
    require_admin(current_user)
    from services.osint_poller import osint_c2_tick
    summary = await osint_c2_tick()
    return {"ok": True, "summary": summary}


@router.get("/c2-matches")
async def c2_matches(
    client_id: Optional[str] = None,
    status_filter: Optional[str] = "active",
    limit: int = 100,
    current_user: dict = Depends(get_current_user),
):
    """Alert di comunicazione con IP malevoli noti (source_type=osint_c2)."""
    query: dict = {"source_type": "osint_c2"}
    if client_id:
        query["client_id"] = client_id
    if status_filter and status_filter != "all":
        query["status"] = status_filter
    items = await db.alerts.find(query, {"_id": 0}).sort("created_at", -1).to_list(min(limit, 500))
    client_ids = list({i.get("client_id") for i in items if i.get("client_id")})
    clients = await db.clients.find({"id": {"$in": client_ids}}, {"_id": 0, "id": 1, "name": 1}).to_list(1000)
    cmap = {c["id"]: c["name"] for c in clients}
    for i in items:
        i["client_name"] = cmap.get(i.get("client_id"), "")
    return {"total": len(items), "items": items}
