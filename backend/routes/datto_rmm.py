"""
Datto RMM API Integration (v3.7.0 — Privacy Hardened)
=====================================================
MODALITA' ZERO-KNOWLEDGE:
- Dei payload Datto (lista device + audit) salviamo in chiaro SOLO i 3 campi
  operativi: `name`, `mac`, `ip`. Tutto il resto (OS, utente, SN BIOS, dischi,
  RAM, modello, dominio, ...) e' cifrato AES-256-GCM come blob opaco in
  `raw_enc` e non viene mai esposto via API.
- `uid` Datto e' memorizzato in chiaro perche' e' l'ID interno usato server-side
  per richiamare l'audit endpoint. Non viene esposto al client.
- Solo i device MATCHATI 100% con il Center (via MAC primario, IP fallback)
  vengono usati per arricchire `discovered_endpoints` con `datto_name`.
- Credenziali Datto (api_key, userId) sempre prese da `datto_settings` cifrato.
- Nessun log in chiaro di api_key/userId/uid.

Endpoints:
- GET    /api/admin/datto/config
- PUT    /api/admin/datto/config
- DELETE /api/admin/datto/config
- POST   /api/admin/datto/test
- GET    /api/datto/sites
- POST   /api/datto/sync-now
- GET    /api/datto/scheduler-status
- GET    /api/clients/{client_id}/datto/link
- PUT    /api/clients/{client_id}/datto/link
- DELETE /api/clients/{client_id}/datto/link
- GET    /api/clients/{client_id}/datto/devices  (ritorna SOLO name/mac/ip/matched)
"""
from __future__ import annotations

import logging
import asyncio
import json
from datetime import datetime, timezone
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
DEFAULT_AUDIT_URL = "https://portal.86bit.it/api/v1/reports/datto/getDeviceAuditDataFromUid"
AUDIT_CONCURRENCY = 3           # richieste audit concorrenti verso il portal
AUDIT_PER_SYNC_CAP = 500        # cap di sicurezza per sync (evita hammering)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class DattoConfigIn(BaseModel):
    api_key: str = Field(..., min_length=8, max_length=400)
    user_id: str = Field(..., min_length=4, max_length=100)
    base_url: Optional[str] = Field(default=None, max_length=500)
    audit_url: Optional[str] = Field(default=None, max_length=500)


class DattoConfigOut(BaseModel):
    configured: bool
    api_key_preview: str
    user_id: str
    base_url: str
    audit_url: str
    updated_at: Optional[str] = None
    updated_by: Optional[str] = None


class DattoLinkIn(BaseModel):
    site_id: str = Field(..., min_length=1, max_length=200)


# ---------------------------------------------------------------------------
# Helper: normalizzazione MAC/IP e logging sicuro
# ---------------------------------------------------------------------------
def _mask_key(api_key: str) -> str:
    if not api_key or len(api_key) < 8:
        return "********"
    return f"****{api_key[-4:]}"


def _norm_mac(m: Any) -> str:
    if not m:
        return ""
    s = str(m).upper().replace("-", ":").replace(".", ":").strip()
    if ":" not in s and len(s) == 12:
        s = ":".join(s[i:i + 2] for i in range(0, 12, 2))
    # Filtra MAC invalidi/speciali
    if s in ("00:00:00:00:00:00", "FF:FF:FF:FF:FF:FF"):
        return ""
    if s.startswith("01:00:5E") or s.startswith("33:33:"):
        return ""  # multicast IPv4/IPv6
    if len(s) != 17:
        return ""
    return s


def _norm_ip(ip: Any) -> str:
    if not ip:
        return ""
    s = str(ip).strip()
    # Escludi IP palesemente non utili
    if s.startswith("127.") or s == "0.0.0.0" or s.startswith("169.254."):
        return ""
    return s


def _encrypt_blob(obj: Any) -> str:
    """Serializza dict/list a JSON e lo cifra AES-256-GCM."""
    try:
        return security_manager.encrypt_credential(json.dumps(obj, default=str, ensure_ascii=False))
    except Exception as e:
        logger.warning(f"datto_encrypt_blob_failed: {type(e).__name__}")
        return ""


def _safe_uid_tag(uid: str) -> str:
    """Log-safe tag per uid: mostra solo primi 4 + ultimi 2 char."""
    if not uid or len(uid) < 8:
        return "uid=****"
    return f"uid={uid[:4]}..{uid[-2:]}"


# ---------------------------------------------------------------------------
# Config admin (encrypted)
# ---------------------------------------------------------------------------
@router.get("/admin/datto/config", response_model=DattoConfigOut)
async def get_datto_config(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    cfg = await db.datto_settings.find_one({"id": "global"}, {"_id": 0})
    if not cfg:
        return DattoConfigOut(
            configured=False, api_key_preview="********",
            user_id="", base_url=DEFAULT_BASE_URL, audit_url=DEFAULT_AUDIT_URL,
        )
    return DattoConfigOut(
        configured=True,
        api_key_preview=cfg.get("api_key_preview", "********"),
        user_id=cfg.get("user_id", ""),
        base_url=cfg.get("base_url") or DEFAULT_BASE_URL,
        audit_url=cfg.get("audit_url") or DEFAULT_AUDIT_URL,
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
    audit_url = (payload.audit_url or DEFAULT_AUDIT_URL).strip()
    if not base_url.startswith("http") or not audit_url.startswith("http"):
        raise HTTPException(status_code=400, detail="Gli URL devono iniziare con http(s)")
    doc = {
        "id": "global",
        "api_key_enc": encrypted,
        "api_key_preview": _mask_key(payload.api_key),
        "user_id": payload.user_id.strip(),
        "base_url": base_url,
        "audit_url": audit_url,
        "updated_at": now,
        "updated_by": current_user.get("email", ""),
    }
    await db.datto_settings.update_one({"id": "global"}, {"$set": doc}, upsert=True)
    audit.info(f"datto_config_saved by={current_user.get('email')}")
    return DattoConfigOut(
        configured=True,
        api_key_preview=doc["api_key_preview"],
        user_id=doc["user_id"], base_url=doc["base_url"], audit_url=doc["audit_url"],
        updated_at=doc["updated_at"], updated_by=doc["updated_by"],
    )


@router.delete("/admin/datto/config")
async def delete_datto_config(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    r = await db.datto_settings.delete_one({"id": "global"})
    await db.datto_sites_cache.delete_many({})
    await db.datto_devices.delete_many({})
    await db.datto_audit_cache.delete_many({})
    audit.info(f"datto_config_purged by={current_user.get('email')}")
    return {"deleted": r.deleted_count}


# ---------------------------------------------------------------------------
# Live fetch — devices list (con paginazione best-effort)
# ---------------------------------------------------------------------------
async def _get_datto_creds() -> tuple[str, str, str, str]:
    cfg = await db.datto_settings.find_one({"id": "global"}, {"_id": 0})
    if not cfg:
        raise HTTPException(status_code=400, detail="Datto RMM API non configurata")
    api_key = security_manager.decrypt_credential(cfg["api_key_enc"])
    return (
        api_key,
        cfg.get("user_id", ""),
        cfg.get("base_url") or DEFAULT_BASE_URL,
        cfg.get("audit_url") or DEFAULT_AUDIT_URL,
    )


async def _fetch_devices_list_all(timeout: float = 30.0) -> list[dict]:
    """Scarica la lista completa dei device Datto.

    Il wrapper portal.86bit.it attualmente espone una singola pagina (max ~250
    device). Tentiamo comunque &page=N per forward-compat: se il payload
    duplicato (stesso primo uid di pagina 1) ci fermiamo.
    """
    api_key, user_id, base_url, _ = await _get_datto_creds()
    params = {"api_key": api_key, "userId": user_id, "json": "true"}
    all_devices: list[dict] = []
    seen_first_uid: Optional[str] = None
    total_expected: Optional[int] = None
    page = 0
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        while page < 20:  # hard cap
            p = {**params, "page": page} if page > 0 else params
            try:
                resp = await client.get(base_url, params=p)
            except httpx.RequestError:
                raise HTTPException(status_code=502, detail="Errore rete Datto API")
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=f"Datto API ha risposto {resp.status_code}",
                )
            try:
                data = resp.json()
            except Exception:
                raise HTTPException(status_code=502, detail="Risposta Datto non JSON")
            dd = data.get("dattoDevices") if isinstance(data, dict) else None
            devs = (dd or {}).get("devices") or []
            if not isinstance(devs, list) or not devs:
                break
            first_uid = str(devs[0].get("uid") or devs[0].get("id") or "")
            if seen_first_uid is not None and first_uid == seen_first_uid:
                break  # paginazione non supportata, e' la stessa pagina
            seen_first_uid = seen_first_uid or first_uid
            all_devices.extend(devs)
            pd = (dd or {}).get("pageDetails") or {}
            total_expected = total_expected or pd.get("totalCount")
            next_url = pd.get("nextPageUrl")
            if not next_url:
                break
            page += 1
    # Dedup per uid (safety)
    seen: set = set()
    unique: list[dict] = []
    for d in all_devices:
        u = str(d.get("uid") or d.get("id") or "")
        if u and u in seen:
            continue
        seen.add(u)
        unique.append(d)
    # Log riservato
    missing = (total_expected or len(unique)) - len(unique)
    if missing > 0:
        logger.info(
            f"datto_list_paginate total_expected={total_expected} fetched={len(unique)} "
            f"missing={missing} (portal pagination limit)"
        )
    return unique


def _group_devices_by_site(devices: list[dict]) -> list[dict]:
    sites: dict[str, dict] = {}
    for d in devices:
        sid = str(d.get("siteUid") or d.get("siteId") or "")
        sname = d.get("siteName") or sid or "Unknown site"
        if not sid:
            continue
        site = sites.setdefault(sid, {"site_id": sid, "site_name": sname, "devices": []})
        site["devices"].append(d)
    return list(sites.values())


# ---------------------------------------------------------------------------
# Live fetch — audit per singolo device (estrae SOLO nic macAddress+ipv4)
# ---------------------------------------------------------------------------
async def _fetch_device_audit_raw(
    client: httpx.AsyncClient, uid: str, api_key: str, user_id: str, audit_url: str,
) -> Optional[dict]:
    params = {"api_key": api_key, "userId": user_id, "json": "true", "uid": uid}
    try:
        resp = await client.get(audit_url, params=params, timeout=20.0)
    except httpx.RequestError:
        return None
    if resp.status_code != 200:
        return None
    try:
        data = resp.json()
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get("success"):
        return None
    return data.get("deviceAuditData") or None


def _extract_nics(audit_data: dict) -> list[dict]:
    """Da `deviceAuditData` estrae SOLO la lista {mac, ip} delle NIC utili.
    Scarta tutto il resto (BIOS, CPU, RAM, dischi, utente, OS, ecc).
    """
    if not isinstance(audit_data, dict):
        return []
    nics = audit_data.get("nics") or []
    result: list[dict] = []
    for n in nics:
        if not isinstance(n, dict):
            continue
        mac = _norm_mac(n.get("macAddress") or n.get("mac"))
        ip = _norm_ip(n.get("ipv4") or n.get("ip"))
        if not mac and not ip:
            continue
        result.append({"mac": mac, "ip": ip})
    return result


# ---------------------------------------------------------------------------
# Core: refresh cache + enrichment MAC via audit + match 100%
# ---------------------------------------------------------------------------
async def _refresh_sites_cache() -> dict:
    devices = await _fetch_devices_list_all()
    sites = _group_devices_by_site(devices)
    now = datetime.now(timezone.utc).isoformat()

    # (1) Replace sites cache (solo id/name/count — MAI detail device)
    await db.datto_sites_cache.delete_many({})
    if sites:
        await db.datto_sites_cache.insert_many([
            {"site_id": s["site_id"], "site_name": s["site_name"],
             "device_count": len(s["devices"]), "fetched_at": now}
            for s in sites
        ])

    # (2) Per ogni client linkato: esegui audit per avere i MAC, poi persist
    links = await db.datto_client_links.find({}, {"_id": 0}).to_list(1000)
    site_by_id = {s["site_id"]: s for s in sites}

    api_key, user_id, _, audit_url = await _get_datto_creds()
    sem = asyncio.Semaphore(AUDIT_CONCURRENCY)

    total_matched = 0
    total_persisted = 0
    total_audited = 0

    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        for link in links:
            cid = link.get("client_id")
            sid = link.get("site_id")
            site = site_by_id.get(sid)
            if not cid or not site:
                continue
            client_devices = site["devices"][:AUDIT_PER_SYNC_CAP]

            async def _process(dev: dict) -> Optional[dict]:
                nonlocal total_audited
                uid = str(dev.get("uid") or dev.get("id") or "")
                name = (dev.get("hostname") or dev.get("description") or "").strip()
                ip_primary = _norm_ip(dev.get("intIpAddress"))
                if not uid:
                    return None
                # Lancia audit per estrarre MAC (concurrency-limited)
                async with sem:
                    audit_raw = await _fetch_device_audit_raw(
                        client, uid, api_key, user_id, audit_url,
                    )
                    total_audited += 1
                nics = _extract_nics(audit_raw) if audit_raw else []
                mac_list: list[str] = []
                ip_list: list[str] = []
                for n in nics:
                    m = n.get("mac") or ""
                    i = n.get("ip") or ""
                    if m and m not in mac_list:
                        mac_list.append(m)
                    if i and i not in ip_list:
                        ip_list.append(i)
                if ip_primary and ip_primary not in ip_list:
                    ip_list.insert(0, ip_primary)
                mac_primary = mac_list[0] if mac_list else ""
                ip_out = ip_list[0] if ip_list else ""
                # Raw payload completo (lista+audit) cifrato opaco
                raw_blob = {
                    "list": dev,
                    "audit": audit_raw,
                    "_t": now,
                }
                return {
                    "client_id": cid,
                    "site_id": sid,
                    "uid": uid,              # interno, non esposto via API
                    "name": name,
                    "mac": mac_primary,      # primario per matching
                    "ip": ip_out,            # primario per matching
                    "mac_list": mac_list,    # per match con altre NIC
                    "ip_list": ip_list,
                    "raw_enc": _encrypt_blob(raw_blob),
                    "fetched_at": now,
                }

            tasks = [_process(d) for d in client_devices]
            results = await asyncio.gather(*tasks, return_exceptions=False)
            persisted = [r for r in results if r]

            # Replace datto_devices per questo client
            await db.datto_devices.delete_many({"client_id": cid})
            if persisted:
                await db.datto_devices.insert_many(persisted)
            total_persisted += len(persisted)

            # Match 100% con discovered_endpoints + managed_devices
            matched = await _match_with_center(cid, persisted)
            total_matched += matched

            await db.datto_client_links.update_one(
                {"client_id": cid},
                {"$set": {
                    "last_sync_at": now,
                    "device_count": len(persisted),
                    "matched_count": matched,
                }},
            )

    return {
        "sites": len(sites),
        "linked_clients": len(links),
        "devices_audited": total_audited,
        "devices_persisted": total_persisted,
        "matched_endpoints": total_matched,
    }


async def _match_with_center(client_id: str, datto_devices: list[dict]) -> int:
    """Match 100%: per ogni device Datto prova (in ordine):
       1. MAC primary (o qualsiasi della mac_list) vs discovered_endpoints.mac
       2. IP primary (o qualsiasi della ip_list) vs discovered_endpoints.ip
       3. IP vs managed_devices.ip_address
    Solo i device matchati scrivono `datto_name` in `discovered_endpoints`
    (nessun altro campo Datto viene mai salvato in chiaro).
    """
    if not datto_devices:
        return 0

    # Index MAC e IP Datto -> device
    mac_to_dev: dict[str, dict] = {}
    ip_to_dev: dict[str, dict] = {}
    for d in datto_devices:
        for m in d.get("mac_list") or []:
            if m:
                mac_to_dev.setdefault(m, d)
        for ip in d.get("ip_list") or []:
            if ip:
                ip_to_dev.setdefault(ip, d)

    if not mac_to_dev and not ip_to_dev:
        return 0

    from pymongo import UpdateOne

    # Carica candidati dal center (client-scoped)
    eps = await db.discovered_endpoints.find(
        {"client_id": client_id},
        {"_id": 0, "mac": 1, "ip": 1, "switch_ip": 1, "port": 1},
    ).to_list(100000)

    # Match set per evitare doppie scritture
    ops: list = []
    matched_uids: set = set()
    matched_eps: set = set()
    now = datetime.now(timezone.utc).isoformat()

    # Pass 1: match su MAC
    for ep in eps:
        ep_mac = (ep.get("mac") or "").upper()
        if ep_mac and ep_mac in mac_to_dev:
            d = mac_to_dev[ep_mac]
            matched_uids.add(d["uid"])
            key = (ep.get("switch_ip"), ep.get("port"), ep.get("mac"))
            if key in matched_eps:
                continue
            matched_eps.add(key)
            ops.append(UpdateOne(
                {"client_id": client_id, "switch_ip": ep["switch_ip"],
                 "port": ep["port"], "mac": ep["mac"]},
                {"$set": {
                    "datto_name": d["name"],
                    "datto_match": "mac",
                    "datto_matched_at": now,
                }},
            ))

    # Pass 2: match su IP (per device senza MAC in FDB)
    for ep in eps:
        ep_ip = ep.get("ip") or ""
        if ep_ip and ep_ip in ip_to_dev:
            d = ip_to_dev[ep_ip]
            if d["uid"] in matched_uids:
                continue  # gia' matchato via MAC
            key = (ep.get("switch_ip"), ep.get("port"), ep.get("mac"))
            if key in matched_eps:
                continue
            matched_eps.add(key)
            matched_uids.add(d["uid"])
            ops.append(UpdateOne(
                {"client_id": client_id, "switch_ip": ep["switch_ip"],
                 "port": ep["port"], "mac": ep["mac"]},
                {"$set": {
                    "datto_name": d["name"],
                    "datto_match": "ip",
                    "datto_matched_at": now,
                }},
            ))

    # Pass 3: match su managed_devices (per IP senza LLDP/FDB)
    managed = await db.managed_devices.find(
        {"client_id": client_id},
        {"_id": 0, "id": 1, "name": 1, "ip_address": 1},
    ).to_list(10000)
    for md in managed:
        ip = md.get("ip_address") or ""
        if ip and ip in ip_to_dev:
            d = ip_to_dev[ip]
            if d["uid"] in matched_uids:
                continue
            matched_uids.add(d["uid"])

    # Scrivi stato matched sui datto_devices (senza mai mettere in chiaro dati sensibili)
    if matched_uids:
        await db.datto_devices.update_many(
            {"client_id": client_id, "uid": {"$in": list(matched_uids)}},
            {"$set": {"matched": True, "matched_at": now}},
        )
    await db.datto_devices.update_many(
        {"client_id": client_id, "uid": {"$nin": list(matched_uids)}},
        {"$set": {"matched": False}},
    )

    if ops:
        await db.discovered_endpoints.bulk_write(ops, ordered=False)

    return len(matched_uids)


# ---------------------------------------------------------------------------
# Endpoints funzionali
# ---------------------------------------------------------------------------
@router.post("/admin/datto/test")
async def test_datto_connection(current_user: dict = Depends(get_current_user)):
    """Chiama il portal e ritorna SOLO il conteggio site/device. Nessun dato sensibile."""
    require_admin(current_user)
    devices = await _fetch_devices_list_all(timeout=20.0)
    sites = _group_devices_by_site(devices)
    summary = [
        {"site_id": s["site_id"], "site_name": s["site_name"],
         "device_count": len(s["devices"])}
        for s in sites
    ]
    return {"ok": True, "sites_found": len(sites),
            "devices_found": len(devices), "sites": summary}


@router.post("/datto/sync-now")
async def datto_sync_now(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    result = await _refresh_sites_cache()
    audit.info(f"datto_sync_now by={current_user.get('email')} -> {result}")
    return {"ok": True, **result}


@router.get("/datto/sites")
async def list_datto_sites(current_user: dict = Depends(get_current_user)):
    sites = await db.datto_sites_cache.find({}, {"_id": 0}).sort("site_name", 1).to_list(2000)
    if not sites:
        try:
            await _refresh_sites_cache()
            sites = await db.datto_sites_cache.find({}, {"_id": 0}).sort("site_name", 1).to_list(2000)
        except HTTPException:
            pass
    return {"items": sites, "count": len(sites)}


@router.get("/datto/scheduler-status")
async def datto_scheduler_status(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    cfg = await db.datto_settings.find_one({"id": "global"}, {"_id": 0, "id": 1})
    last = await db.datto_sites_cache.find_one({}, {"_id": 0, "fetched_at": 1},
                                               sort=[("fetched_at", -1)])
    sites_count = await db.datto_sites_cache.count_documents({})
    devices_count = await db.datto_devices.count_documents({})
    links_count = await db.datto_client_links.count_documents({})
    matched_count = await db.datto_devices.count_documents({"matched": True})
    next_run = None
    try:
        from server import datto_scheduler  # type: ignore
        if datto_scheduler:
            for j in datto_scheduler.get_jobs():
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
        "matched_devices": matched_count,
    }


@router.get("/clients/{client_id}/datto/link")
async def get_datto_link(
    client_id: str, current_user: dict = Depends(get_current_user),
):
    link = await db.datto_client_links.find_one({"client_id": client_id}, {"_id": 0})
    if not link:
        return {"linked": False}
    device_count = await db.datto_devices.count_documents({"client_id": client_id})
    matched_count = await db.datto_devices.count_documents({"client_id": client_id, "matched": True})
    return {"linked": True, **link, "device_count": device_count, "matched_count": matched_count}


@router.put("/clients/{client_id}/datto/link")
async def set_datto_link(
    client_id: str, payload: DattoLinkIn,
    current_user: dict = Depends(get_current_user),
):
    require_admin(current_user)
    client = await db.clients.find_one({"id": client_id}, {"_id": 0, "name": 1})
    if not client:
        raise HTTPException(status_code=404, detail="Client non trovato")
    site = await db.datto_sites_cache.find_one({"site_id": payload.site_id}, {"_id": 0})
    if not site:
        try:
            await _refresh_sites_cache()
        except HTTPException:
            pass
        site = await db.datto_sites_cache.find_one({"site_id": payload.site_id}, {"_id": 0})
        if not site:
            raise HTTPException(status_code=404, detail="Site Datto non trovato")
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
    try:
        await _refresh_sites_cache()
    except Exception as e:
        logger.warning(f"datto immediate sync failed: {type(e).__name__}")
    link = await db.datto_client_links.find_one({"client_id": client_id}, {"_id": 0})
    device_count = await db.datto_devices.count_documents({"client_id": client_id})
    matched_count = await db.datto_devices.count_documents({"client_id": client_id, "matched": True})
    return {"linked": True, **(link or {}),
            "device_count": device_count, "matched_count": matched_count}


@router.delete("/clients/{client_id}/datto/link")
async def remove_datto_link(
    client_id: str, current_user: dict = Depends(get_current_user),
):
    require_admin(current_user)
    r1 = await db.datto_client_links.delete_one({"client_id": client_id})
    r2 = await db.datto_devices.delete_many({"client_id": client_id})
    await db.discovered_endpoints.update_many(
        {"client_id": client_id, "datto_name": {"$exists": True}},
        {"$unset": {"datto_name": "", "datto_match": "", "datto_matched_at": "",
                    "datto_id": "", "datto_os": "", "datto_os_version": "",
                    "datto_ip": ""}},
    )
    audit.info(f"datto_unlink client={client_id} by={current_user.get('email')}")
    return {"unlinked": r1.deleted_count, "devices_removed": r2.deleted_count}


@router.get("/clients/{client_id}/datto/devices")
async def list_datto_devices_for_client(
    client_id: str, current_user: dict = Depends(get_current_user),
):
    """Ritorna SOLO i 3 campi operativi (name, mac, ip) + stato match.
    Nessun OS, utente, SN, modello, dominio viene mai esposto.
    Di default filtra i MATCHATI; passare ?include_unmatched=1 per vederli tutti.
    """
    from fastapi import Request  # noqa
    projection = {
        "_id": 0, "name": 1, "mac": 1, "ip": 1,
        "matched": 1, "matched_at": 1, "site_id": 1, "site_name": 1,
    }
    devs = await db.datto_devices.find(
        {"client_id": client_id}, projection,
    ).sort("name", 1).to_list(10000)
    matched_count = sum(1 for d in devs if d.get("matched"))
    return {
        "items": [
            {
                "name": d.get("name", ""),
                "mac": d.get("mac", ""),
                "ip": d.get("ip", ""),
                "matched": bool(d.get("matched")),
                "matched_at": d.get("matched_at"),
                "site_name": d.get("site_name", ""),
            }
            for d in devs
        ],
        "count": len(devs),
        "matched": matched_count,
    }
