"""Zyxel Nebula (NCC) OpenAPI integration.

Fonte cloud per i dispositivi Zyxel (firewall USG FLEX serie H, switch, AP)
gestiti tramite Nebula Control Center. Invece di interrogare via SNMP ogni
device sulla LAN, Argus legge lo stato e le metriche direttamente dal cloud
Nebula (una sola chiave OpenAPI → tutte le organizzazioni dei clienti).

Sicurezza:
- Chiave API SEMPRE cifrata (AES) in `zyxel_settings`, mai in chiaro nel codice
  ne' nei log ne' esposta al browser.
- Header cloud: `X-ZyxelNebula-API-Key`. Cattura `X-ZyxelNebula-API-RequestId`
  per il tracing dei ticket di supporto.

Riferimento contratto: https://zyxelnetworks.github.io/NebulaOpenAPI/doc/openapi.html
"""
from __future__ import annotations

import os
import asyncio
import random
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from database import db
from deps import get_current_user, require_admin
from security import security_manager

logger = logging.getLogger("zyxel_nebula")
audit = logging.getLogger("audit")

router = APIRouter(prefix="/api", tags=["zyxel-nebula"])

DEFAULT_BASE_URL = os.environ.get("ZYXEL_BASE_URL", "https://api.nebula.zyxel.com/v1/nebula")


# ==================== Models ====================

class ZyxelConfigIn(BaseModel):
    api_key: str = Field(..., min_length=8, max_length=400)
    base_url: Optional[str] = None


class ZyxelConfigOut(BaseModel):
    configured: bool
    api_key_preview: str
    base_url: str
    last_error: Optional[str] = None
    updated_at: Optional[str] = None


class ZyxelLinkIn(BaseModel):
    org_id: str = Field(..., min_length=4, max_length=64)
    site_ids: Optional[list[str]] = None  # None/[] = tutti i siti dell'org


# ==================== Helpers ====================

def _mask_key(api_key: str) -> str:
    if not api_key or len(api_key) < 8:
        return "********"
    return f"{api_key[:4]}****{api_key[-4:]}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _get_creds() -> tuple[str, str]:
    """Ritorna (api_key_plain, base_url). 503 se non configurato / non decifrabile."""
    cfg = await db.zyxel_settings.find_one({"id": "global"}, {"_id": 0})
    if not cfg or not cfg.get("api_key_enc"):
        raise HTTPException(status_code=503, detail="Zyxel Nebula non configurato. Inserisci la chiave OpenAPI in Impostazioni.")
    try:
        api_key = security_manager.decrypt_credential(cfg["api_key_enc"])
    except Exception as dec_err:  # noqa: BLE001
        await db.zyxel_settings.update_one(
            {"id": "global"},
            {"$set": {"last_error": f"Decryption failed: {dec_err}. Ri-salva la chiave API."}},
        )
        raise HTTPException(status_code=503, detail="Chiave API Zyxel non decifrabile: ri-salvala dalle Impostazioni.")
    return api_key, (cfg.get("base_url") or DEFAULT_BASE_URL)


class ZyxelError(RuntimeError):
    def __init__(self, status: int, message: str, request_id: Optional[str]):
        super().__init__(f"Zyxel HTTP {status}: {message} requestId={request_id}")
        self.status = status
        self.request_id = request_id


async def _nebula_request(method: str, path: str, *, timeout: float = 40.0, **kwargs) -> Any:
    """Chiamata autenticata al cloud Nebula con retry/backoff su 429/5xx/transient."""
    api_key, base_url = await _get_creds()
    headers = {
        "X-ZyxelNebula-API-Key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    url = base_url.rstrip("/") + path
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0)) as client:
        for attempt in range(5):
            try:
                r = await client.request(method, url, headers=headers, **kwargs)
                rid = r.headers.get("X-ZyxelNebula-API-RequestId")
                if r.status_code == 401:
                    raise ZyxelError(401, "Chiave API non valida o revocata", rid)
                if r.status_code == 403:
                    raise ZyxelError(403, "L'amministratore della chiave non ha i permessi / licenza Pro Pack mancante", rid)
                if r.status_code == 404:
                    raise ZyxelError(404, "org/site/device non trovato", rid)
                if r.status_code == 429 or r.status_code >= 500:
                    if attempt == 4:
                        raise ZyxelError(r.status_code, (r.text or "")[:300], rid)
                    ra = r.headers.get("Retry-After")
                    delay = float(ra) if ra else (2 ** attempt) + random.random()
                    await asyncio.sleep(min(delay, 30))
                    continue
                if r.status_code >= 400:
                    raise ZyxelError(r.status_code, (r.text or "")[:300], rid)
                data = r.json()
                if isinstance(data, dict) and int(data.get("status", 200)) >= 400:
                    raise ZyxelError(int(data["status"]), data.get("message", "API error"), rid)
                return data
            except httpx.TransportError:
                if attempt == 4:
                    raise
                await asyncio.sleep(min((2 ** attempt) + random.random(), 30))
    raise AssertionError("unreachable")


def _dev_type(nebula_type: str) -> str:
    """Mappa il device type Nebula (GWH/GW/SWH/SW/AP...) al device_type Argus."""
    t = (nebula_type or "").upper()
    if t.startswith("GW"):
        return "firewall"
    if t.startswith("SW"):
        return "switch"
    if t.startswith("AP"):
        return "ap"
    return "network"


def _port_link_status(link_speed) -> str:
    """Deriva lo stato link di una porta dal campo linkSpeed di Nebula.
    linkSpeed vuoto / 'Down' / '0' = porta giu'; qualsiasi velocita' = su."""
    s = str(link_speed or "").strip().lower()
    if not s or s in ("down", "0", "0m", "no link", "disconnected", "n/a", "-"):
        return "down"
    return "up"



# Soglie di alerting per i firewall Zyxel (allineate al profilo zyxel_usg_flex_h).
ZYXEL_THRESHOLDS = {
    "cpu": (70, 90),          # (warn, crit) %
    "mem": (80, 95),          # (warn, crit) %
    "sessions": (50000, 100000),
}
_METRIC_LABEL = {"cpu": "CPU", "mem": "Memoria", "sessions": "Sessioni"}
_METRIC_UNIT = {"cpu": "%", "mem": "%", "sessions": ""}


def _threshold_level(metric: str, value) -> Optional[str]:
    if value is None:
        return None
    warn, crit = ZYXEL_THRESHOLDS[metric]
    v = float(value)
    if v >= crit:
        return "crit"
    if v >= warn:
        return "warn"
    return None


async def _emit_zyxel_alert(dev_doc: dict, severity: str, source_type: str,
                            title: str, message: str, recovery: bool = False) -> None:
    """Emette un alert Zyxel Nebula sui canali configurati (push + Telegram).
    Riusa il pipeline standard dell'Alert Engine (_mk_alert/_dispatch_notification)."""
    try:
        import alert_engine as _ae
        from alert_filter import insert_alert_if_emit
        cfg = await _ae.get_config(db)
        alert = _ae._mk_alert(
            dev_doc.get("client_id", ""), dev_doc.get("client_name", ""),
            dev_doc.get("name") or dev_doc.get("model") or "Zyxel", "",
            dev_doc.get("device_type", "firewall"), severity, source_type, title, message,
        )
        alert["raw_data"] = f"nebula:{dev_doc.get('dev_id','')} mac={dev_doc.get('mac','')} model={dev_doc.get('model','')}"
        if recovery:
            await _ae._emit_recovery_notice(db, cfg, alert)
        else:
            await insert_alert_if_emit(db, alert)
            await _ae._dispatch_notification(db, cfg, alert)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"zyxel alert dispatch failed: {e}")


# ==================== Config CRUD ====================

@router.get("/admin/zyxel/config", response_model=ZyxelConfigOut)
async def get_zyxel_config(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    cfg = await db.zyxel_settings.find_one({"id": "global"}, {"_id": 0})
    if not cfg:
        return ZyxelConfigOut(configured=False, api_key_preview="********", base_url=DEFAULT_BASE_URL)
    return ZyxelConfigOut(
        configured=bool(cfg.get("api_key_enc")),
        api_key_preview=cfg.get("api_key_preview", "********"),
        base_url=cfg.get("base_url") or DEFAULT_BASE_URL,
        last_error=cfg.get("last_error"),
        updated_at=cfg.get("updated_at"),
    )


@router.put("/admin/zyxel/config", response_model=ZyxelConfigOut)
async def put_zyxel_config(payload: ZyxelConfigIn, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    encrypted = security_manager.encrypt_credential(payload.api_key.strip())
    doc = {
        "id": "global",
        "api_key_enc": encrypted,
        "api_key_preview": _mask_key(payload.api_key.strip()),
        "base_url": (payload.base_url or DEFAULT_BASE_URL).strip(),
        "updated_at": _now_iso(),
        "last_error": None,
    }
    await db.zyxel_settings.update_one({"id": "global"}, {"$set": doc}, upsert=True)
    audit.info(f"zyxel_config saved by={current_user.get('email')}")
    return ZyxelConfigOut(
        configured=True, api_key_preview=doc["api_key_preview"],
        base_url=doc["base_url"], updated_at=doc["updated_at"],
    )


@router.delete("/admin/zyxel/config")
async def delete_zyxel_config(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    await db.zyxel_settings.delete_one({"id": "global"})
    await db.zyxel_orgs_cache.delete_many({})
    await db.zyxel_devices.delete_many({})
    audit.info(f"zyxel_config deleted by={current_user.get('email')}")
    return {"deleted": True}


@router.post("/admin/zyxel/test")
async def test_zyxel_connection(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    try:
        orgs = await _nebula_request("GET", "/organizations")
    except ZyxelError as e:
        await db.zyxel_settings.update_one({"id": "global"}, {"$set": {"last_error": str(e)}})
        raise HTTPException(status_code=502, detail=str(e))
    orgs = orgs or []
    pro = [o for o in orgs if (o.get("mode") or "").upper() == "PRO"]
    await db.zyxel_settings.update_one({"id": "global"}, {"$set": {"last_error": None}})
    return {
        "ok": True,
        "org_count": len(orgs),
        "pro_org_count": len(pro),
        "sample": [{"name": o.get("name"), "orgId": o.get("orgId"), "mode": o.get("mode")} for o in orgs[:10]],
    }


# ==================== Browse cloud ====================

@router.get("/zyxel/organizations")
async def list_organizations(refresh: bool = False, current_user: dict = Depends(get_current_user)):
    """Lista organizzazioni Nebula (cache in `zyxel_orgs_cache`)."""
    require_admin(current_user)
    if not refresh:
        cached = await db.zyxel_orgs_cache.find({}, {"_id": 0}).to_list(1000)
        if cached:
            return {"organizations": cached, "cached": True}
    orgs = await _nebula_request("GET", "/organizations") or []
    now = _now_iso()
    docs = [{"org_id": o.get("orgId"), "name": o.get("name"), "mode": o.get("mode"), "fetched_at": now} for o in orgs if o.get("orgId")]
    if docs:
        await db.zyxel_orgs_cache.delete_many({})
        await db.zyxel_orgs_cache.insert_many([dict(d) for d in docs])
    return {"organizations": docs, "cached": False}


@router.get("/zyxel/organizations/{org_id}/sites")
async def list_sites(org_id: str, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    sites = await _nebula_request("GET", f"/organizations/{org_id}/sites") or []
    return {"sites": [{"site_id": s.get("siteId"), "name": s.get("name"),
                       "time_zone": s.get("timeZone"), "device_count": s.get("deviceCount")} for s in sites]}


@router.get("/zyxel/organizations/{org_id}/devices")
async def list_org_devices(org_id: str, current_user: dict = Depends(get_current_user)):
    """Device dell'org, appiattiti (un record per device con il proprio siteId)."""
    require_admin(current_user)
    grouped = await _nebula_request("GET", f"/organizations/{org_id}/sites/devices") or []
    out: list[dict] = []
    for g in grouped:
        sid = g.get("siteId")
        for d in (g.get("devices") or []):
            out.append({
                "site_id": sid, "dev_id": d.get("devId"), "name": d.get("name"),
                "mac": d.get("mac"), "sn": d.get("sn"), "model": d.get("model"),
                "type": d.get("type"), "device_type": _dev_type(d.get("type")),
                "product_info": d.get("productInfo"),
            })
    return {"devices": out}


# ==================== Client link ====================

@router.get("/clients/{client_id}/zyxel/link")
async def get_zyxel_link(client_id: str, current_user: dict = Depends(get_current_user)):
    link = await db.zyxel_client_links.find_one({"client_id": client_id}, {"_id": 0})
    if not link:
        return {"linked": False}
    device_count = await db.zyxel_devices.count_documents({"client_id": client_id})
    return {"linked": True, **link, "device_count": device_count}


@router.put("/clients/{client_id}/zyxel/link")
async def set_zyxel_link(client_id: str, payload: ZyxelLinkIn, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    client = await db.clients.find_one({"id": client_id}, {"_id": 0, "name": 1})
    if not client:
        raise HTTPException(status_code=404, detail="Client non trovato")
    # Risolvi nome org (best-effort dalla cache o dal cloud)
    org = await db.zyxel_orgs_cache.find_one({"org_id": payload.org_id}, {"_id": 0})
    org_name = org.get("name") if org else payload.org_id
    now = _now_iso()
    await db.zyxel_client_links.update_one(
        {"client_id": client_id},
        {"$set": {
            "client_id": client_id, "client_name": client.get("name", ""),
            "org_id": payload.org_id, "org_name": org_name,
            "site_ids": payload.site_ids or [],
            "linked_at": now, "linked_by": current_user.get("email", ""),
        }},
        upsert=True,
    )
    audit.info(f"zyxel_link client={client_id} -> org={payload.org_id} by={current_user.get('email')}")
    # Sync immediato del cliente appena mappato (best-effort)
    try:
        await sync_client_devices(client_id)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"zyxel immediate sync failed client={client_id}: {type(e).__name__}")
    link = await db.zyxel_client_links.find_one({"client_id": client_id}, {"_id": 0})
    device_count = await db.zyxel_devices.count_documents({"client_id": client_id})
    return {"linked": True, **(link or {}), "device_count": device_count}


@router.delete("/clients/{client_id}/zyxel/link")
async def remove_zyxel_link(client_id: str, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    await db.zyxel_client_links.delete_one({"client_id": client_id})
    await db.zyxel_devices.delete_many({"client_id": client_id})
    audit.info(f"zyxel_link removed client={client_id} by={current_user.get('email')}")
    return {"linked": False}


@router.get("/clients/{client_id}/zyxel/devices")
async def list_client_zyxel_devices(client_id: str, current_user: dict = Depends(get_current_user)):
    devs = await db.zyxel_devices.find({"client_id": client_id}, {"_id": 0}).sort("model", 1).to_list(2000)
    return {"devices": devs, "count": len(devs)}


@router.get("/clients/{client_id}/zyxel/devices/{dev_id}/metrics")
async def get_device_metrics(client_id: str, dev_id: str, hours: int = 24,
                             current_user: dict = Depends(get_current_user)):
    """Serie storica CPU/memoria/sessioni di un firewall Zyxel (da zyxel_metrics)."""
    hours = max(1, min(hours, 720))
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    docs = await db.zyxel_metrics.find(
        {"client_id": client_id, "dev_id": dev_id, "observed_at": {"$gte": cutoff}},
        {"_id": 0, "observed_at": 1, "cpu": 1, "mem": 1, "sessions": 1},
    ).sort("observed_at", 1).to_list(10000)
    return {"metrics": docs, "count": len(docs)}


@router.get("/clients/{client_id}/zyxel/devices/{dev_id}/event-logs")
async def get_device_event_logs(client_id: str, dev_id: str, minutes: int = 60, limit: int = 150,
                                current_user: dict = Depends(get_current_user)):
    """Event-log live del firewall Zyxel (on-demand: Nebula ne restituisce migliaia,
    scarichiamo una finestra breve e teniamo i piu' recenti)."""
    dev = await db.zyxel_devices.find_one(
        {"client_id": client_id, "dev_id": dev_id, "device_type": "firewall"},
        {"_id": 0, "site_id": 1},
    )
    if not dev:
        raise HTTPException(status_code=404, detail="Firewall Zyxel non trovato per questo cliente")
    minutes = max(5, min(minutes, 360))
    limit = max(10, min(limit, 500))
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = now_ms - minutes * 60 * 1000
    try:
        logs = await _nebula_request(
            "POST", f"/{dev['site_id']}/gw/event-logs",
            json={"startTimestamp": start_ms, "endTimestamp": now_ms},
        )
    except ZyxelError as e:
        raise HTTPException(status_code=502, detail=f"Nebula event-logs: {e}")
    if not isinstance(logs, list):
        logs = []
    logs.sort(key=lambda x: x.get("timestamp") or 0, reverse=True)
    out = [{
        "timestamp": x.get("timestamp"),
        "category": x.get("category"),
        "message": x.get("message"),
        "src_ip": x.get("srcIpv4"),
        "src_port": x.get("srcPort"),
        "dst_ip": x.get("dstIpv4"),
        "dst_port": x.get("dstPort"),
    } for x in logs[:limit]]
    return {"logs": out, "count": len(out), "total_window": len(logs), "minutes": minutes}


@router.get("/zyxel/links")
async def list_all_links(current_user: dict = Depends(get_current_user)):
    """Tutti i mapping cliente→org + conteggio device sincronizzati."""
    require_admin(current_user)
    links = await db.zyxel_client_links.find({}, {"_id": 0}).to_list(2000)
    for l in links:
        l["device_count"] = await db.zyxel_devices.count_documents({"client_id": l["client_id"]})
    return {"links": links}


@router.get("/zyxel/devices")
async def list_all_zyxel_devices(current_user: dict = Depends(get_current_user)):
    """Flotta Zyxel completa (tutti i clienti mappati) con stato e metriche live."""
    require_admin(current_user)
    devs = await db.zyxel_devices.find({}, {"_id": 0}).sort([("client_name", 1), ("model", 1)]).to_list(5000)
    return {"devices": devs, "count": len(devs)}


# ==================== Sync engine ====================

async def _upsert_firewall_managed_device(client_id: str, client_name: str, doc: dict) -> None:
    """Marca come VITALE il managed_device del firewall (match per MAC o nome) e vi
    aggancia i dettagli Nebula. Non crea IP fittizi: se il firewall non e' ancora
    monitorato con un IP reale resta comunque completo nella vista Zyxel/WAN."""
    try:
        mac = (doc.get("mac") or "").strip().lower().replace("-", ":")
        name = (doc.get("name") or "").strip()
        q = None
        if mac:
            q = {"client_id": client_id, "mac": {"$regex": f"^{mac}$", "$options": "i"}}
            if not await db.managed_devices.find_one(q, {"_id": 0}) and name:
                q = {"client_id": client_id, "name": name}
        elif name:
            q = {"client_id": client_id, "name": name}
        nebula_ref = {
            "dev_id": doc.get("dev_id"), "org_id": doc.get("org_id"), "site_id": doc.get("site_id"),
            "model": doc.get("model"), "sn": doc.get("sn"), "mac": doc.get("mac"),
            "firmware": doc.get("firmware"), "online_status": doc.get("online_status"),
        }
        set_fields = {"is_vital": True, "device_type": "firewall",
                      "nebula_dev_id": doc.get("dev_id"), "nebula": nebula_ref,
                      "nebula_synced_at": doc.get("updated_at")}
        if q:
            await db.managed_devices.update_one(q, {"$set": set_fields})
    except Exception as e:  # noqa: BLE001
        logger.debug(f"upsert firewall vital fallito dev={doc.get('dev_id')}: {e}")


async def sync_client_devices(client_id: str) -> dict:
    """Sincronizza i device Zyxel di UN cliente mappato: inventario + online/firmware +
    metriche live (CPU/mem/sessioni per gateway, traffico per gateway/switch)."""
    link = await db.zyxel_client_links.find_one({"client_id": client_id}, {"_id": 0})
    if not link:
        return {"synced": 0, "reason": "not_linked"}
    org_id = link["org_id"]
    site_filter = set(link.get("site_ids") or [])
    client_name = link.get("client_name") or ""

    grouped = await _nebula_request("GET", f"/organizations/{org_id}/sites/devices") or []
    fw_list = await _nebula_request("GET", f"/organizations/{org_id}/firmware-status") or []
    fw_by_dev = {f.get("devId"): f for f in fw_list}

    # nome siti (per label)
    try:
        sites = await _nebula_request("GET", f"/organizations/{org_id}/sites") or []
    except ZyxelError:
        sites = []
    site_name = {s.get("siteId"): s.get("name") for s in sites}

    now = _now_iso()
    synced = 0
    seen_dev_ids: list[str] = []
    metric_docs: list[dict] = []

    for g in grouped:
        sid = g.get("siteId")
        if site_filter and sid not in site_filter:
            continue
        # stato online per sito (una chiamata copre tutti i device del sito)
        online_map: dict[str, str] = {}
        try:
            for o in (await _nebula_request("GET", f"/{sid}/online-status") or []):
                online_map[o.get("devId")] = o.get("currentStatus")
        except ZyxelError as e:
            logger.debug(f"online-status site={sid}: {e}")

        for d in (g.get("devices") or []):
            dev_id = d.get("devId")
            if not dev_id:
                continue
            ntype = d.get("type")
            dtype = _dev_type(ntype)
            doc: dict[str, Any] = {
                "client_id": client_id, "org_id": org_id, "site_id": sid,
                "client_name": client_name,
                "site_name": site_name.get(sid) or "", "dev_id": dev_id,
                "name": d.get("name"), "mac": d.get("mac"), "sn": d.get("sn"),
                "model": d.get("model"), "nebula_type": ntype, "device_type": dtype,
                "product_info": d.get("productInfo"),
                "online_status": online_map.get(dev_id),
                "updated_at": now,
            }
            fw = fw_by_dev.get(dev_id)
            if fw:
                doc["firmware"] = {
                    "current": fw.get("currentVersion"), "latest": fw.get("latestVersion"),
                    "status": fw.get("status"), "last_upgrade": fw.get("lastUpgradeTime"),
                }

            # Metriche gateway (CPU/mem/sessioni) — solo firewall/gateway ONLINE
            if dtype == "firewall" and online_map.get(dev_id) == "ONLINE":
                try:
                    sysst = await _nebula_request("GET", f"/{sid}/gw/{dev_id}/system-status")
                    if isinstance(sysst, dict):
                        doc["cpu_usage"] = sysst.get("cpuUsage")
                        doc["mem_usage"] = sysst.get("memUsage")
                        doc["sessions"] = sysst.get("sessions")
                        metric_docs.append({
                            "client_id": client_id, "dev_id": dev_id, "observed_at": now,
                            "ts": datetime.now(timezone.utc),
                            "cpu": sysst.get("cpuUsage"), "mem": sysst.get("memUsage"),
                            "sessions": sysst.get("sessions"),
                        })
                except ZyxelError as e:
                    logger.debug(f"system-status dev={dev_id}: {e}")

            # Traffico interfacce (gateway + switch)
            if dtype in ("firewall", "switch") and online_map.get(dev_id) == "ONLINE":
                seg = "gw" if dtype == "firewall" else "sw"
                try:
                    traffic = await _nebula_request("GET", f"/{sid}/{seg}/{dev_id}/traffic-usage")
                    if isinstance(traffic, list):
                        doc["traffic"] = [{
                            "interface": t.get("interface"),
                            "tx": t.get("uplinkTxUsage"),
                            # NB: l'API Nebula usa la chiave 'uplinkRxUage' (refuso lato Zyxel)
                            "rx": t.get("uplinkRxUage", t.get("uplinkRxUsage")),
                        } for t in traffic]
                except ZyxelError as e:
                    logger.debug(f"traffic-usage dev={dev_id}: {e}")

            # Stato PORTE del firewall/switch.
            # Endpoint Nebula CORRETTO: /{sid}/{seg}/{dev_id}/ports-status
            #   - gateway: [{portNumber, portGroup, linkSpeed}]
            #   - switch : [{portNum,    linkSpeed}]
            # Lo stato link non e' esplicito: si deriva da linkSpeed (vuoto/Down = giu').
            if dtype in ("firewall", "switch") and online_map.get(dev_id) == "ONLINE":
                seg = "gw" if dtype == "firewall" else "sw"
                for ep in (f"/{sid}/{seg}/{dev_id}/ports-status",
                           f"/{sid}/{seg}/{dev_id}/port-status"):
                    try:
                        ports = await _nebula_request("GET", ep)
                        if isinstance(ports, list) and ports:
                            doc["ports"] = [{
                                "port": p.get("portNumber") or p.get("portNum") or p.get("port"),
                                "group": p.get("portGroup"),
                                "speed": p.get("linkSpeed") or p.get("speed"),
                                "status": _port_link_status(p.get("linkSpeed") or p.get("speed")),
                            } for p in ports]
                            break
                    except ZyxelError as e:
                        logger.debug(f"ports-status dev={dev_id} ep={ep}: {e}")

            # WAN / IP pubblico + stato linea (solo firewall online).
            # interface-settings → {wan:[{interface,ipv4Type,ipv4Address,ipv4Gateway,enabled}], lan:[...]}
            if dtype == "firewall" and online_map.get(dev_id) == "ONLINE":
                try:
                    ifs = await _nebula_request("GET", f"/{sid}/gw/{dev_id}/interface-settings")
                    if isinstance(ifs, dict):
                        wan_list = ifs.get("wan") or []
                        doc["wan_interfaces"] = [{
                            "interface": w.get("interface"),
                            "enabled": w.get("enabled"),
                            "ipv4_type": w.get("ipv4Type"),
                            "public_ip": w.get("ipv4Address"),
                            "gateway": w.get("ipv4Gateway"),
                            "netmask": w.get("ipv4Netmask"),
                            "dns": w.get("DNSServers") or [],
                            "port_group": w.get("portGroupId"),
                            "vlan": w.get("vlan"),
                        } for w in wan_list]
                        lan_list = ifs.get("lan") or []
                        doc["lan_interfaces"] = [{
                            "interface": l.get("interface"),
                            "enabled": l.get("enabled"),
                            "ipv4_type": l.get("ipv4Type"),
                            "ip": l.get("ipv4Address"),
                            "netmask": l.get("ipv4Netmask"),
                            "port_group": l.get("portGroupId"),
                            "guest_zone": l.get("guestZone"),
                        } for l in lan_list]
                        # IP pubblico "primario" = primo WAN abilitato con indirizzo
                        primary = next(
                            (w for w in doc["wan_interfaces"] if w.get("enabled") and w.get("public_ip")),
                            (doc["wan_interfaces"][0] if doc["wan_interfaces"] else None),
                        )
                        if primary:
                            doc["public_ip"] = primary.get("public_ip")
                            doc["line_state"] = "up" if primary.get("enabled") and primary.get("public_ip") else "down"
                            # Nebula NON espone l'ISP nativamente: lo ricaviamo dall'IP
                            # pubblico via geo-IP (ip-api, cache 30gg). Cosi' l'operatore
                            # vede subito l'operatore della linea sul firewall Nebula.
                            pub = doc.get("public_ip")
                            if pub:
                                try:
                                    from routes.external_monitor import _geoip_cached
                                    geo = await _geoip_cached(pub)
                                    if geo and not geo.get("error"):
                                        doc["isp"] = geo.get("isp") or geo.get("asn_name")
                                        doc["isp_org"] = geo.get("org")
                                        doc["asn"] = geo.get("asn")
                                        doc["asn_name"] = geo.get("asn_name")
                                        doc["geo_country_code"] = geo.get("country_code")
                                except Exception as _ge:
                                    logger.debug(f"geoip nebula {pub}: {_ge}")
                except ZyxelError as e:
                    logger.debug(f"interface-settings dev={dev_id}: {e}")

            # Regole NAT (solo firewall online): virtualServer (port-forwarding) + 1:1.
            if dtype == "firewall" and online_map.get(dev_id) == "ONLINE":
                try:
                    nat = await _nebula_request("GET", f"/{sid}/gw/{dev_id}/nat-settings")
                    if isinstance(nat, dict):
                        vs = nat.get("virtualServer") or []
                        o2o = nat.get("oneToOne") or []
                        doc["nat_rules"] = [{
                            "type": "virtual_server",
                            "name": r.get("description"),
                            "enabled": r.get("enabled"),
                            "interface": r.get("interface"),
                            "protocol": r.get("protocol"),
                            "public_ip": r.get("publicIPv4"),
                            "public_ports": r.get("publicPorts") or [],
                            "server_ip": r.get("serverIPv4"),
                            "server_ports": r.get("serverPorts") or [],
                        } for r in vs] + [{
                            "type": "one_to_one",
                            "name": r.get("name"),
                            "enabled": r.get("enabled"),
                            "interface": r.get("interface"),
                            "public_ip": r.get("publicIPv4"),
                            "server_ip": r.get("privateIPv4"),
                        } for r in o2o]
                except ZyxelError as e:
                    logger.debug(f"nat-settings dev={dev_id}: {e}")

            # Client connessi al firewall (site-level) + stato VPN.
            if dtype == "firewall" and online_map.get(dev_id) == "ONLINE":
                try:
                    cl = await _nebula_request(
                        "POST", f"/{sid}/clients",
                        json=["mac_address", "ipv4", "vlan", "status", "description",
                              "os_hostname", "manufacturer", "last_seen", "connected_device_id"],
                    )
                    if isinstance(cl, list):
                        mine = [c for c in cl if c.get("connectedTo") == dev_id] or cl
                        mine.sort(key=lambda c: (c.get("status") != "ONLINE", str(c.get("ipv4Address") or "")))
                        doc["clients"] = [{
                            "mac": c.get("macAddress"),
                            "ip": c.get("ipv4Address"),
                            "vlan": c.get("vlan"),
                            "status": c.get("status"),
                            "hostname": (c.get("osHostname") or {}).get("hostname") or c.get("description"),
                            "os": (c.get("osHostname") or {}).get("os"),
                            "vendor": c.get("manufacturer"),
                            "last_seen": c.get("lastSeen"),
                        } for c in mine[:500]]
                        doc["clients_online"] = sum(1 for c in doc["clients"] if c["status"] == "ONLINE")
                except ZyxelError as e:
                    logger.debug(f"clients dev={dev_id}: {e}")
                try:
                    vpn = await _nebula_request("GET", f"/{sid}/vpn-status")
                    if isinstance(vpn, dict):
                        doc["vpn_status"] = {
                            "sites": vpn.get("sites") or [],
                            "gateways": vpn.get("gateways") or [],
                            "remote_aps": vpn.get("remoteAps") or [],
                        }
                except ZyxelError as e:
                    logger.debug(f"vpn-status dev={dev_id}: {e}")

            # Firewall Nebula = apparato VITALE + managed_device sempre presente,
            # cosi' compare tra i vitali, in WAN e nel CMDB con tutti i dettagli.
            if dtype == "firewall":
                doc["is_vital"] = True
                await _upsert_firewall_managed_device(client_id, client_name, doc)

            prev = await db.zyxel_devices.find_one(
                {"client_id": client_id, "dev_id": dev_id},
                {"_id": 0, "online_status": 1, "alert_state": 1},
            )
            alert_state = dict((prev or {}).get("alert_state") or {})
            now_status = online_map.get(dev_id)
            label = d.get("name") or d.get("model") or "Zyxel"

            # 1) Offline / recovery
            if now_status and now_status != "ONLINE":
                if not alert_state.get("offline"):
                    await _emit_zyxel_alert(
                        doc, "critical", "zyxel_offline",
                        f"Zyxel OFFLINE: {label} ({client_name})",
                        f"Il dispositivo Zyxel {label} (modello {d.get('model')}, sito "
                        f"{site_name.get(sid) or sid}) risulta OFFLINE su Nebula.",
                    )
                    alert_state["offline"] = True
                    # in offline azzeriamo gli stati soglia (il device e' giu')
                    for _m in ("cpu", "mem", "sessions"):
                        alert_state.pop(_m, None)
            elif now_status == "ONLINE":
                if alert_state.get("offline"):
                    await _emit_zyxel_alert(
                        doc, "low", "zyxel_offline_recovery",
                        f"Zyxel RIPRISTINATO: {label} ({client_name})",
                        f"Il dispositivo Zyxel {label} e' tornato ONLINE su Nebula.",
                        recovery=True,
                    )
                    alert_state["offline"] = False
                # 2) Soglie CPU/Memoria/Sessioni (solo se online, solo firewall con metriche)
                for metric in ("cpu", "mem", "sessions"):
                    val = doc.get({"cpu": "cpu_usage", "mem": "mem_usage", "sessions": "sessions"}[metric])
                    level = _threshold_level(metric, val)
                    prev_level = alert_state.get(metric)
                    if level and level != prev_level:
                        sev = "critical" if level == "crit" else "high"
                        warn, crit = ZYXEL_THRESHOLDS[metric]
                        soglia = crit if level == "crit" else warn
                        await _emit_zyxel_alert(
                            doc, sev, f"zyxel_{metric}",
                            f"Zyxel {_METRIC_LABEL[metric]} {'CRITICA' if level=='crit' else 'ALTA'}: {label}",
                            f"{label} ({client_name}) — {_METRIC_LABEL[metric]} a "
                            f"{val}{_METRIC_UNIT[metric]} (soglia {soglia}{_METRIC_UNIT[metric]}).",
                        )
                        alert_state[metric] = level
                    elif not level and prev_level:
                        await _emit_zyxel_alert(
                            doc, "low", f"zyxel_{metric}_recovery",
                            f"Zyxel {_METRIC_LABEL[metric]} rientrata: {label}",
                            f"{label} ({client_name}) — {_METRIC_LABEL[metric]} rientrata "
                            f"nella norma ({val}{_METRIC_UNIT[metric]}).",
                            recovery=True,
                        )
                        alert_state.pop(metric, None)
            doc["alert_state"] = alert_state

            await db.zyxel_devices.update_one(
                {"client_id": client_id, "dev_id": dev_id},
                {"$set": doc}, upsert=True,
            )
            seen_dev_ids.append(dev_id)
            synced += 1

    # Rimuovi device non piu' presenti nell'org/siti mappati
    if seen_dev_ids:
        await db.zyxel_devices.delete_many({"client_id": client_id, "dev_id": {"$nin": seen_dev_ids}})
    if metric_docs:
        try:
            await db.zyxel_metrics.insert_many(metric_docs)
        except Exception:  # noqa: BLE001
            pass
    await db.zyxel_client_links.update_one({"client_id": client_id}, {"$set": {"last_sync_at": now, "last_sync_count": synced}})
    # Auto-collega i target WAN di questo cliente ai firewall Nebula appena sincronizzati
    try:
        from routes.external_monitor import auto_link_wan_targets_nebula
        await auto_link_wan_targets_nebula(client_id)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"auto-link nebula (client {client_id}) fallito: {e}")
    return {"synced": synced, "org_id": org_id}


@router.post("/zyxel/sync-now")
async def zyxel_sync_now(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    links = await db.zyxel_client_links.find({}, {"_id": 0, "client_id": 1}).to_list(1000)
    total = 0
    errors: list[dict] = []
    for l in links:
        try:
            res = await sync_client_devices(l["client_id"])
            total += res.get("synced", 0)
        except Exception as e:  # noqa: BLE001
            errors.append({"client_id": l["client_id"], "error": str(e)})
    return {"clients": len(links), "devices_synced": total, "errors": errors}


async def nebula_sync_tick() -> None:
    """Tick schedulato: sincronizza tutti i clienti mappati. Best-effort."""
    cfg = await db.zyxel_settings.find_one({"id": "global"}, {"_id": 0})
    if not cfg or not cfg.get("api_key_enc"):
        return
    try:
        # retention 30gg sulle metriche (idempotente)
        await db.zyxel_metrics.create_index("ts", expireAfterSeconds=30 * 24 * 3600)
    except Exception:  # noqa: BLE001
        pass
    links = await db.zyxel_client_links.find({}, {"_id": 0, "client_id": 1}).to_list(1000)
    for l in links:
        try:
            await sync_client_devices(l["client_id"])
        except Exception as e:  # noqa: BLE001
            logger.warning(f"nebula_sync_tick client={l.get('client_id')} err={type(e).__name__}")
        await asyncio.sleep(0.5)  # jitter/pacing tra clienti
