"""
Datto RMM API Integration (v3.6.20)
====================================
Endpoint custom esposto da `portal.86bit.it` che ritorna lista clienti + dispositivi
del tenant Datto RMM dell'azienda. URL forma:
    https://portal.86bit.it/api/v1/reports/datto/getDattoDevices?api_key=...&userId=...&json=true

Risposta attesa (per cliente):
    {
      "site_id": "abc123", "site_name": "Cliente XYZ",
      "devices": [
         { "name": "PC-MARIO", "mac_address": "AA:BB:CC:DD:EE:FF", "ip": "10.10.41.55",
           "os": "Windows 10", "device_id": "..." },
         ...
      ]
    }

Una volta sincronizzato il tenant Datto, ogni `client_id` locale puo' essere
"linkato" a un site Datto. Il sistema poi:
  - Salva i device Datto in `db.datto_devices` (per client_id)
  - Arricchisce `db.discovered_endpoints` con `datto_*` (datto_name, datto_os, datto_id) per match MAC/IP
  - In topology._build_mac_neighbor: priorita' lldp > mac_manual > mac_fdb_trunk > mac_datto > mac_managed > mac_oui > mac_unknown

Collections:
- datto_settings        : { id: "global", api_key_enc, user_id, base_url, updated_at, updated_by }
- datto_sites_cache     : per-site list dei device scaricati (TTL 6h)
- datto_client_links    : { client_id, site_id, site_name, last_sync_at }
- datto_devices         : per (client_id, mac) row con info Datto

Endpoints:
- GET    /api/admin/datto/config              : ritorna preview chiave + user_id
- PUT    /api/admin/datto/config              : salva config (encrypts api_key)
- DELETE /api/admin/datto/config              : rimuove config
- POST   /api/admin/datto/test                : chiama l'endpoint Datto e ritorna lista site_id+nome
- GET    /api/datto/sites                     : lista cached sites disponibili (per dropdown link)
- POST   /api/datto/sync-now                  : forza fetch live dei device da Datto
- GET    /api/clients/{client_id}/datto/link  : ritorna mapping corrente
- PUT    /api/clients/{client_id}/datto/link  : associa client_id locale a un site Datto + sync
- DELETE /api/clients/{client_id}/datto/link  : rimuove il link
"""
from __future__ import annotations

import logging
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from database import db
from deps import get_current_user, require_admin
from security import security_manager
logger = logging.getLogger(__name__)
audit = logging.getLogger("audit")

router = APIRouter(prefix="/api", tags=["datto-rmm"])

DEFAULT_BASE_URL = "https://portal.86bit.it/api/v1/reports/datto/getDattoDevices"
SITES_CACHE_TTL_HOURS = 6


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class DattoConfigIn(BaseModel):
    api_key: str = Field(..., min_length=8, max_length=400)
    user_id: str = Field(..., min_length=4, max_length=100)
    base_url: Optional[str] = Field(default=None, max_length=500)


class DattoConfigOut(BaseModel):
    configured: bool
    api_key_preview: str
    user_id: str
    base_url: str
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None


class DattoLinkIn(BaseModel):
    site_id: str = Field(..., min_length=1, max_length=200)


def _mask_key(api_key: str) -> str:
    if not api_key or len(api_key) < 8:
        return "********"
    return f"****{api_key[-4:]}"


def _norm_mac(m: Optional[str]) -> str:
    if not m:
        return ""
    s = str(m).upper().replace("-", ":").replace(".", ":").strip()
    # Datto sometimes returns "AABBCCDDEEFF" senza separatori
    if ":" not in s and len(s) == 12:
        s = ":".join(s[i:i + 2] for i in range(0, 12, 2))
    return s


# ---------------------------------------------------------------------------
# Config admin (encrypted) - GET / PUT / DELETE
# ---------------------------------------------------------------------------
@router.get("/admin/datto/config", response_model=DattoConfigOut)
async def get_datto_config(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    cfg = await db.datto_settings.find_one({"id": "global"}, {"_id": 0})
    if not cfg:
        return DattoConfigOut(
            configured=False, api_key_preview="********",
            user_id="", base_url=DEFAULT_BASE_URL,
        )
    return DattoConfigOut(
        configured=True,
        api_key_preview=cfg.get("api_key_preview", "********"),
        user_id=cfg.get("user_id", ""),
        base_url=cfg.get("base_url") or DEFAULT_BASE_URL,
        updated_at=cfg.get("updated_at"),
        updated_by=cfg.get("updated_by"),
    )


@router.put("/admin/datto/config", response_model=DattoConfigOut)
async def put_datto_config(
    payload: DattoConfigIn,
    current_user: dict = Depends(get_current_user),
):
    require_admin(current_user)
    encrypted = security_manager.encrypt_credential(payload.api_key)
    now = datetime.now(timezone.utc).isoformat()
    base_url = (payload.base_url or DEFAULT_BASE_URL).strip()
    if not base_url.startswith("http"):
        raise HTTPException(status_code=400, detail="base_url deve iniziare con http(s)")
    doc = {
        "id": "global",
        "api_key_enc": encrypted,
        "api_key_preview": _mask_key(payload.api_key),
        "user_id": payload.user_id.strip(),
        "base_url": base_url,
        "updated_at": now,
        "updated_by": current_user.get("email", ""),
    }
    await db.datto_settings.update_one({"id": "global"}, {"$set": doc}, upsert=True)
    audit.info(f"datto_config_saved by={current_user.get('email')}")
    return DattoConfigOut(
        configured=True,
        api_key_preview=doc["api_key_preview"],
        user_id=doc["user_id"], base_url=doc["base_url"],
        updated_at=doc["updated_at"], updated_by=doc["updated_by"],
    )


@router.delete("/admin/datto/config")
async def delete_datto_config(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    r = await db.datto_settings.delete_one({"id": "global"})
    await db.datto_sites_cache.delete_many({})
    audit.info(f"datto_config_deleted by={current_user.get('email')}")
    return {"deleted": r.deleted_count}


# ---------------------------------------------------------------------------
# Live fetch da portal.86bit.it
# ---------------------------------------------------------------------------
async def _fetch_datto_payload(timeout: float = 30.0) -> dict:
    cfg = await db.datto_settings.find_one({"id": "global"}, {"_id": 0})
    if not cfg:
        raise HTTPException(status_code=400, detail="Datto RMM API non configurata")
    api_key = security_manager.decrypt_credential(cfg["api_key_enc"])
    base_url = cfg.get("base_url") or DEFAULT_BASE_URL
    user_id = cfg.get("user_id", "")
    params = {"api_key": api_key, "userId": user_id, "json": "true"}
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(base_url, params=params)
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Errore rete Datto API: {e}")
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code,
                            detail=f"Datto API ha risposto {resp.status_code}: {resp.text[:200]}")
    try:
        return resp.json()
    except Exception:
        raise HTTPException(status_code=502, detail="Risposta Datto non e' JSON valido")


def _normalize_sites(payload: Any) -> list[dict]:
    """Normalizza payload Datto a una lista di {site_id, site_name, devices}.
    Accetta sia dict singolo, lista di siti, o {"sites": [...]} / {"data": [...]} / {"clients": [...]}.
    """
    if isinstance(payload, dict):
        for k in ("sites", "data", "clients", "items", "result"):
            if k in payload and isinstance(payload[k], list):
                items = payload[k]
                break
        else:
            items = [payload]
    elif isinstance(payload, list):
        items = payload
    else:
        items = []
    sites: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        site_id = str(
            it.get("site_id") or it.get("siteId") or it.get("id")
            or it.get("uid") or it.get("client_id") or ""
        ).strip()
        site_name = (
            it.get("site_name") or it.get("siteName") or it.get("name")
            or it.get("client_name") or it.get("client") or ""
        )
        devs = it.get("devices") or it.get("Devices") or it.get("device_list") or []
        if not isinstance(devs, list):
            devs = []
        if not site_id:
            # Fallback: usa nome come id se non c'e'
            site_id = site_name.replace(" ", "_").lower() if site_name else f"unknown_{len(sites)}"
        sites.append({
            "site_id": site_id,
            "site_name": str(site_name or site_id),
            "devices": devs,
        })
    return sites


def _normalize_device(d: dict) -> dict:
    return {
        "datto_id": str(d.get("device_id") or d.get("id") or d.get("uid") or ""),
        "name": d.get("name") or d.get("hostname") or d.get("device_name") or "",
        "mac": _norm_mac(d.get("mac_address") or d.get("mac") or d.get("macAddress")),
        "ip": (d.get("ip") or d.get("ip_address") or d.get("ipAddress") or "").strip(),
        "os": d.get("os") or d.get("operating_system") or d.get("os_name") or "",
        "os_version": d.get("os_version") or d.get("operatingSystem") or "",
        "raw": {k: v for k, v in d.items() if k in (
            "manufacturer", "model", "serial_number", "lastSeen", "last_seen",
            "online", "status", "agent_version",
        )},
    }


@router.post("/admin/datto/test")
async def test_datto_connection(current_user: dict = Depends(get_current_user)):
    """Chiama l'endpoint Datto e ritorna i siti trovati (numero device)."""
    require_admin(current_user)
    payload = await _fetch_datto_payload(timeout=20.0)
    sites = _normalize_sites(payload)
    summary = [
        {"site_id": s["site_id"], "site_name": s["site_name"],
         "device_count": len(s.get("devices", []))}
        for s in sites
    ]
    return {"ok": True, "sites_found": len(sites), "sites": summary}


async def _refresh_sites_cache():
    """Ri-popola datto_sites_cache + datto_devices per tutti i siti.
    Lasciato come internal helper, chiamato da /admin/datto/test, /datto/sync-now,
    e dal scheduler periodico (TODO: integrarlo nello scheduler globale).
    """
    payload = await _fetch_datto_payload()
    sites = _normalize_sites(payload)
    now = datetime.now(timezone.utc).isoformat()
    # Replace whole cache
    await db.datto_sites_cache.delete_many({})
    if sites:
        cache_docs = [
            {"site_id": s["site_id"], "site_name": s["site_name"],
             "device_count": len(s.get("devices", [])),
             "fetched_at": now}
            for s in sites
        ]
        await db.datto_sites_cache.insert_many(cache_docs)
    # Per ogni linked client, aggiorna datto_devices
    links = await db.datto_client_links.find({}, {"_id": 0}).to_list(1000)
    site_by_id = {s["site_id"]: s for s in sites}
    matched_total = 0
    for link in links:
        cid = link.get("client_id")
        sid = link.get("site_id")
        if not cid or sid not in site_by_id:
            continue
        site = site_by_id[sid]
        devs = [_normalize_device(d) for d in site.get("devices", [])]
        # Replace devices for this client
        await db.datto_devices.delete_many({"client_id": cid})
        if devs:
            await db.datto_devices.insert_many([
                {**d, "client_id": cid, "site_id": sid, "site_name": site["site_name"], "fetched_at": now}
                for d in devs
            ])
        # Match con discovered_endpoints (per MAC, fallback IP)
        matched = await _match_with_discovered(cid, devs)
        matched_total += matched
        await db.datto_client_links.update_one(
            {"client_id": cid},
            {"$set": {"last_sync_at": now, "device_count": len(devs), "matched_count": matched}},
        )
    return {"sites": len(sites), "linked_clients": len(links), "matched_endpoints": matched_total}


async def _match_with_discovered(client_id: str, datto_devices: list[dict]) -> int:
    """Per ogni device Datto, trova match in discovered_endpoints by MAC (primary) o IP (fallback).
    Aggiorna i campi datto_id/datto_name/datto_os/datto_ip nei matched endpoints.
    Ritorna conteggio matchati.
    """
    if not datto_devices:
        return 0
    # Build maps
    mac_map = {d["mac"]: d for d in datto_devices if d.get("mac")}
    ip_map = {d["ip"]: d for d in datto_devices if d.get("ip")}
    # Find candidate endpoints
    eps = await db.discovered_endpoints.find(
        {"client_id": client_id},
        {"_id": 0, "mac": 1, "ip": 1, "switch_ip": 1, "port": 1},
    ).to_list(50000)
    matched = 0
    from pymongo import UpdateOne
    ops = []
    for ep in eps:
        ep_mac = (ep.get("mac") or "").upper()
        ep_ip = ep.get("ip") or ""
        d = mac_map.get(ep_mac) or ip_map.get(ep_ip)
        if not d:
            continue
        ops.append(UpdateOne(
            {"client_id": client_id, "switch_ip": ep["switch_ip"],
             "port": ep["port"], "mac": ep["mac"]},
            {"$set": {
                "datto_id": d["datto_id"], "datto_name": d["name"],
                "datto_os": d["os"], "datto_os_version": d["os_version"],
                "datto_ip": d["ip"],
            }},
        ))
        matched += 1
    if ops:
        await db.discovered_endpoints.bulk_write(ops, ordered=False)
    return matched


@router.post("/datto/sync-now")
async def datto_sync_now(current_user: dict = Depends(get_current_user)):
    """Forza il refresh del cache + match con tutti i client linkati."""
    require_admin(current_user)
    result = await _refresh_sites_cache()
    audit.info(f"datto_sync_now by={current_user.get('email')} -> {result}")
    return {"ok": True, **result}


# ---------------------------------------------------------------------------
# Sites disponibili + linking per cliente
# ---------------------------------------------------------------------------
@router.get("/datto/sites")
async def list_datto_sites(current_user: dict = Depends(get_current_user)):
    """Lista cached sites Datto disponibili per il dropdown di linking."""
    sites = await db.datto_sites_cache.find({}, {"_id": 0}).sort("site_name", 1).to_list(2000)
    if not sites:
        # Auto-refresh on first call (best effort)
        try:
            await _refresh_sites_cache()
            sites = await db.datto_sites_cache.find({}, {"_id": 0}).sort("site_name", 1).to_list(2000)
        except HTTPException:
            pass
    return {"items": sites, "count": len(sites)}


@router.get("/datto/scheduler-status")
async def datto_scheduler_status(current_user: dict = Depends(get_current_user)):
    """Ritorna ultimo refresh + prossimo scheduled run dello scheduler Datto (auto-sync 6h)."""
    require_admin(current_user)
    cfg = await db.datto_settings.find_one({"id": "global"}, {"_id": 0, "id": 1})
    last = await db.datto_sites_cache.find_one({}, {"_id": 0, "fetched_at": 1}, sort=[("fetched_at", -1)])
    sites_count = await db.datto_sites_cache.count_documents({})
    devices_count = await db.datto_devices.count_documents({})
    links_count = await db.datto_client_links.count_documents({})
    next_run = None
    try:
        # Best-effort: leggi lo scheduler globale se accessibile
        from server import datto_scheduler  # type: ignore
        if datto_scheduler:
            jobs = datto_scheduler.get_jobs()
            for j in jobs:
                if j.id == "datto_rmm_auto_sync" and j.next_run_time:
                    next_run = j.next_run_time.isoformat()
                    break
    except Exception:
        pass
    return {
        "configured": bool(cfg),
        "last_refresh_at": (last or {}).get("fetched_at"),
        "next_scheduled_at": next_run,
        "interval_hours": 6,
        "sites_in_cache": sites_count,
        "linked_clients": links_count,
        "synced_devices": devices_count,
    }


@router.get("/clients/{client_id}/datto/link")
async def get_datto_link(
    client_id: str, current_user: dict = Depends(get_current_user),
):
    link = await db.datto_client_links.find_one({"client_id": client_id}, {"_id": 0})
    if not link:
        return {"linked": False}
    # Conteggi
    device_count = await db.datto_devices.count_documents({"client_id": client_id})
    return {"linked": True, **link, "device_count": device_count}


@router.put("/clients/{client_id}/datto/link")
async def set_datto_link(
    client_id: str, payload: DattoLinkIn,
    current_user: dict = Depends(get_current_user),
):
    require_admin(current_user)
    # Verifica che il client esista
    client = await db.clients.find_one({"id": client_id}, {"_id": 0, "name": 1})
    if not client:
        raise HTTPException(status_code=404, detail="Client non trovato")
    # Verifica che il site_id esista nel cache (o refresh-fly)
    site = await db.datto_sites_cache.find_one({"site_id": payload.site_id}, {"_id": 0})
    if not site:
        try:
            await _refresh_sites_cache()
        except HTTPException:
            pass
        site = await db.datto_sites_cache.find_one({"site_id": payload.site_id}, {"_id": 0})
        if not site:
            raise HTTPException(status_code=404, detail=f"Site Datto '{payload.site_id}' non trovato")
    now = datetime.now(timezone.utc).isoformat()
    await db.datto_client_links.update_one(
        {"client_id": client_id},
        {"$set": {
            "client_id": client_id, "client_name": client.get("name", ""),
            "site_id": payload.site_id, "site_name": site["site_name"],
            "linked_at": now, "linked_by": current_user.get("email", ""),
        }},
        upsert=True,
    )
    audit.info(f"datto_link client={client_id} -> site={payload.site_id} by={current_user.get('email')}")
    # Sync immediato di questo cliente
    try:
        await _refresh_sites_cache()
    except Exception as e:
        logger.warning(f"datto immediate sync failed: {e}")
    link = await db.datto_client_links.find_one({"client_id": client_id}, {"_id": 0})
    device_count = await db.datto_devices.count_documents({"client_id": client_id})
    return {"linked": True, **(link or {}), "device_count": device_count}


@router.delete("/clients/{client_id}/datto/link")
async def remove_datto_link(
    client_id: str, current_user: dict = Depends(get_current_user),
):
    require_admin(current_user)
    r1 = await db.datto_client_links.delete_one({"client_id": client_id})
    r2 = await db.datto_devices.delete_many({"client_id": client_id})
    # Cleanup datto_* fields nei discovered_endpoints
    await db.discovered_endpoints.update_many(
        {"client_id": client_id, "datto_id": {"$exists": True}},
        {"$unset": {"datto_id": "", "datto_name": "", "datto_os": "",
                    "datto_os_version": "", "datto_ip": ""}},
    )
    audit.info(f"datto_unlink client={client_id} by={current_user.get('email')}")
    return {"unlinked": r1.deleted_count, "devices_removed": r2.deleted_count}


@router.get("/clients/{client_id}/datto/devices")
async def list_datto_devices_for_client(
    client_id: str, current_user: dict = Depends(get_current_user),
):
    """Restituisce i device Datto del cliente linkato + flag matched (con discovered_endpoints)."""
    devs = await db.datto_devices.find({"client_id": client_id}, {"_id": 0}).to_list(5000)
    # Per ognuno, conta se e' matched in discovered_endpoints
    matched_macs = set()
    if devs:
        macs = [d.get("mac") for d in devs if d.get("mac")]
        if macs:
            async for ep in db.discovered_endpoints.find(
                {"client_id": client_id, "mac": {"$in": macs}},
                {"_id": 0, "mac": 1},
            ):
                matched_macs.add((ep.get("mac") or "").upper())
    for d in devs:
        d["matched"] = (d.get("mac") or "").upper() in matched_macs
    return {"items": devs, "count": len(devs),
            "matched": sum(1 for d in devs if d["matched"])}
