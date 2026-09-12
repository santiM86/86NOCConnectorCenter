"""TP-Link Omada Open API (client_credentials) — sola lettura.

Flusso: POST {base}/openapi/authorize/token?grant_type=client_credentials {omadacId, client_id, client_secret}
→ accessToken; chiamate GET {base}/openapi/v1/{omadacId}/... con header "Authorization: AccessToken=<token>".
Sync ogni 5 min: siti → device (gateway/switch/AP) → porte switch (link/velocità/PoE → memoria porte).
Collezioni: omada_settings (creds cifrate, id=global), omada_sites_cache, omada_devices, omada_client_links.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from database import db
from deps import get_current_user, require_admin
from security import security_manager

logger = logging.getLogger("omada")
router = APIRouter(prefix="/api", tags=["omada"])
_TOKENS: dict = {}  # controller_id → {"value","exp"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mask(s: str) -> str:
    return "********" if not s or len(s) < 8 else f"{s[:4]}****{s[-4:]}"


class OmadaError(RuntimeError):
    def __init__(self, code: Any, msg: str):
        super().__init__(f"Omada {code}: {msg}")
        self.code, self.msg = code, msg


async def _creds(ctrl_id: str) -> dict:
    cfg = await db.omada_settings.find_one({"id": ctrl_id}, {"_id": 0})
    if not cfg or not cfg.get("client_secret_enc"):
        raise HTTPException(status_code=503, detail="Controller Omada non configurato: inserisci le credenziali Open API in Impostazioni → Omada.")
    try:
        secret = security_manager.decrypt_credential(cfg["client_secret_enc"])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Client Secret Omada non decifrabile ({e}): ri-salvalo dalle Impostazioni.")
    return {"id": ctrl_id, "name": cfg.get("name") or ctrl_id, "base_url": (cfg.get("base_url") or "").rstrip("/"), "omadac_id": cfg.get("omadac_id"),
            "client_id": cfg.get("client_id"), "client_secret": secret}


async def _token(ctrl_id: str, force: bool = False) -> str:
    t = _TOKENS.get(ctrl_id) or {}
    if not force and t.get("value") and time.time() < t.get("exp", 0) - 90:
        return t["value"]
    c = await _creds(ctrl_id)
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0)) as cl:
        r = await cl.post(f"{c['base_url']}/openapi/authorize/token", params={"grant_type": "client_credentials"},
                          json={"omadacId": c["omadac_id"], "client_id": c["client_id"], "client_secret": c["client_secret"]})
    try:
        body = r.json()
    except ValueError:
        raise OmadaError(r.status_code, (r.text or "risposta non JSON")[:200])
    if r.status_code >= 400 or int(body.get("errorCode", 0) or 0) != 0:
        raise OmadaError(body.get("errorCode", r.status_code), body.get("msg") or (r.text or "")[:200])
    res = body.get("result") or body
    tok = res.get("accessToken") or res.get("access_token")
    if not tok:
        raise OmadaError("no_token", "il controller non ha restituito accessToken")
    _TOKENS[ctrl_id] = {"value": tok, "exp": time.time() + int(res.get("expiresIn") or 3600)}
    return tok


async def _get(ctrl_id: str, path: str, params: Optional[dict] = None, timeout: float = 25.0) -> Any:
    c = await _creds(ctrl_id)
    for attempt in (0, 1):
        tok = await _token(ctrl_id, force=attempt == 1)
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0)) as cl:
            r = await cl.get(f"{c['base_url']}/openapi/v1/{c['omadac_id']}{path}", params=params,
                             headers={"Authorization": f"AccessToken={tok}", "Accept": "application/json"})
        if r.status_code == 401 and attempt == 0:
            continue
        try:
            body = r.json()
        except ValueError:
            raise OmadaError(r.status_code, (r.text or "risposta non JSON")[:200])
        code = int(body.get("errorCode", 0) or 0) if isinstance(body, dict) else 0
        if code in (-44112, -44113, -44114, -44116, -44118) and attempt == 0:  # token scaduto / non valido
            continue
        if r.status_code >= 400 or code != 0:
            raise OmadaError(code or r.status_code, (body.get("msg") if isinstance(body, dict) else None) or (r.text or "")[:200])
        return body.get("result", body) if isinstance(body, dict) else body
    raise OmadaError("auth", "autenticazione fallita")


async def _paged(ctrl_id: str, path: str, page_size: int = 200) -> list:
    out, page = [], 1
    while True:
        res = await _get(ctrl_id, path, {"page": page, "pageSize": page_size})
        data = res.get("data") if isinstance(res, dict) else res
        out.extend(data or [])
        if not isinstance(res, dict) or len(data or []) < page_size or len(out) >= int(res.get("totalRows") or 0):
            return out
        page += 1


def _dev_type(t: str) -> str:
    t = (t or "").lower()
    return "firewall" if t.startswith("gateway") or t == "gw" else "switch" if t.startswith("switch") else "access_point" if t in ("ap", "eap") or "ap" in t else "other"


# ==================== Settings (multi-controller: una riga per organizzazione Omada) ====================
class OmadaControllerIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    base_url: str = Field(min_length=8)
    omadac_id: str = Field(min_length=3)
    client_id: str = Field(min_length=3)
    client_secret: Optional[str] = None
    enabled: bool = True


def _ctrl_view(cfg: dict) -> dict:
    return {k: v for k, v in cfg.items() if k != "client_secret_enc"} | {"client_secret_masked": _mask(cfg.get("client_secret_hint") or "")}


@router.get("/omada/settings")
async def get_settings(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    ctrls = [c async for c in db.omada_settings.find({"id": {"$ne": "global"}}, {"_id": 0}).sort("name", 1)]
    out = []
    for c in ctrls:
        out.append(_ctrl_view(c) | {"sites": await db.omada_sites_cache.count_documents({"controller_id": c["id"]}),
                                   "devices": await db.omada_devices.count_documents({"controller_id": c["id"]})})
    return {"controllers": out, "configured": bool(out), "links": await db.omada_client_links.count_documents({})}


@router.post("/omada/controllers")
async def add_controller(body: OmadaControllerIn, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    if not body.client_secret:
        raise HTTPException(status_code=422, detail="Client Secret obbligatorio per un nuovo controller")
    cid = f"ctrl-{uuid.uuid4().hex[:8]}"
    doc = {"id": cid, "name": body.name.strip(), "base_url": body.base_url.strip().rstrip("/"), "omadac_id": body.omadac_id.strip(), "client_id": body.client_id.strip(),
           "client_secret_enc": security_manager.encrypt_credential(body.client_secret.strip()),
           "client_secret_hint": body.client_secret.strip()[:4] + "x" * 8 + body.client_secret.strip()[-4:],
           "enabled": body.enabled, "created_at": _now_iso(), "updated_at": _now_iso(), "updated_by": current_user.get("email")}
    await db.omada_settings.insert_one(dict(doc))
    return _ctrl_view(doc)


@router.put("/omada/controllers/{ctrl_id}")
async def update_controller(ctrl_id: str, body: OmadaControllerIn, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    upd = {"name": body.name.strip(), "base_url": body.base_url.strip().rstrip("/"), "omadac_id": body.omadac_id.strip(), "client_id": body.client_id.strip(),
           "enabled": body.enabled, "updated_at": _now_iso(), "updated_by": current_user.get("email")}
    if body.client_secret:
        upd["client_secret_enc"] = security_manager.encrypt_credential(body.client_secret.strip())
        upd["client_secret_hint"] = body.client_secret.strip()[:4] + "x" * 8 + body.client_secret.strip()[-4:]
    res = await db.omada_settings.update_one({"id": ctrl_id}, {"$set": upd})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="Controller non trovato")
    _TOKENS.pop(ctrl_id, None)
    return {"ok": True}


@router.delete("/omada/controllers/{ctrl_id}")
async def delete_controller(ctrl_id: str, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    await db.omada_settings.delete_one({"id": ctrl_id})
    await db.omada_sites_cache.delete_many({"controller_id": ctrl_id})
    await db.omada_devices.delete_many({"controller_id": ctrl_id})
    await db.omada_client_links.delete_many({"controller_id": ctrl_id})
    _TOKENS.pop(ctrl_id, None)
    return {"ok": True}


@router.post("/omada/controllers/{ctrl_id}/test")
async def test_connection(ctrl_id: str, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    try:
        await _token(ctrl_id, force=True)
        sites = await _paged(ctrl_id, "/sites")
        await db.omada_settings.update_one({"id": ctrl_id}, {"$set": {"last_test_ok": _now_iso(), "last_error": None}})
        return {"ok": True, "sites": [{"site_id": s.get("siteId"), "name": s.get("name"), "region": s.get("region")} for s in sites]}
    except (OmadaError, httpx.HTTPError) as e:
        await db.omada_settings.update_one({"id": ctrl_id}, {"$set": {"last_error": str(e)[:300]}})
        raise HTTPException(status_code=400, detail=f"Connessione Omada fallita: {e}")


# ==================== Sync ====================
async def _sync_switch_ports(ctrl_id: str, site_id: str, dev: dict, client_id: Optional[str]) -> int:
    mac = dev.get("mac")
    try:
        ports = await _get(ctrl_id, f"/sites/{site_id}/switches/{mac}/ports")
    except OmadaError as e:
        logger.debug(f"omada ports {mac}: {e}")
        return 0
    ports = ports.get("data") if isinstance(ports, dict) else ports
    rows = []
    for p in ports or []:
        try:
            idx = int(p.get("port") or p.get("lanPort") or 0)
        except (TypeError, ValueError):
            continue
        st = p.get("portStatus") or p
        link_up = bool(st.get("linkStatus") in (1, True, "1")) or str(st.get("linkStatus", "")).lower() in ("up", "1", "true")
        speed_map = {0: 0, 1: 10, 2: 100, 3: 1000, 4: 2500, 5: 10000}
        speed = st.get("linkSpeed")
        speed_mbps = speed_map.get(speed, speed if isinstance(speed, int) and speed > 10 else 0) if link_up else 0
        rows.append({"idx": idx, "name": p.get("name") or f"Port {idx}", "oper": 1 if link_up else 2,
                     "admin": 1 if (p.get("disable") in (None, False, 0)) else 2, "speed_mbps": speed_mbps,
                     "poe_watt": float(st.get("poePower") or 0) if st.get("poe") not in (False, None, 0) else 0.0,
                     "poe_admin": 1 if st.get("poe") not in (False, None, 0) else 2,
                     "poe_status": 3 if float(st.get("poePower") or 0) > 0 else (2 if st.get("poe") not in (False, None, 0) else 1),
                     "descr": p.get("name") or "", "profile": p.get("profileName")})
    if not rows or not dev.get("ip"):
        return 0
    if client_id:
        try:
            from routes.connector import store_switch_ports
            await store_switch_ports(client_id, [{"local_ip": dev["ip"], "local_name": dev.get("name"), "ports": rows, "source": "omada"}])
        except Exception as e:  # noqa: BLE001
            logger.debug(f"omada store_switch_ports {dev.get('ip')}: {e}")
    return len(rows)


async def _sync_controller(ctrl: dict) -> dict:
    ctrl_id = ctrl["id"]
    t0 = time.time()
    stats = {"sites": 0, "devices": 0, "ports": 0, "errors": 0}
    try:
        sites = await _paged(ctrl_id, "/sites")
    except (OmadaError, httpx.HTTPError, HTTPException) as e:
        await db.omada_settings.update_one({"id": ctrl_id}, {"$set": {"last_error": str(e)[:300], "last_sync_at": _now_iso()}})
        return {"error": str(e)}
    links = {l["site_id"]: l async for l in db.omada_client_links.find({"controller_id": ctrl_id}, {"_id": 0})}
    now = _now_iso()
    for s in sites:
        sid = s.get("siteId")
        await db.omada_sites_cache.update_one({"controller_id": ctrl_id, "site_id": sid}, {"$set": {
            "controller_id": ctrl_id, "controller_name": ctrl.get("name"), "site_id": sid, "name": s.get("name"), "region": s.get("region"),
            "timezone": s.get("timeZone"), "scenario": s.get("scenario"), "updated_at": now}}, upsert=True)
        stats["sites"] += 1
        link = links.get(sid)
        try:
            devs = await _paged(ctrl_id, f"/sites/{sid}/devices")
        except (OmadaError, httpx.HTTPError) as e:
            stats["errors"] += 1
            logger.warning(f"omada devices {ctrl.get('name')}/{s.get('name')}: {e}")
            continue
        for d in devs:
            mac = (d.get("mac") or "").upper().replace("-", ":")
            dtype = _dev_type(d.get("type"))
            status = d.get("status")
            online = (isinstance(status, int) and status in (1, 14, 15, 16)) or str(status).lower() in ("connected", "online", "1")
            doc = {"controller_id": ctrl_id, "controller_name": ctrl.get("name"), "site_id": sid, "site_name": s.get("name"), "mac": mac,
                   "name": d.get("name"), "model": d.get("model"), "type_raw": d.get("type"), "device_type": dtype, "ip": d.get("ip"),
                   "public_ip": d.get("publicIp") or d.get("wanIp"), "firmware": d.get("firmwareVersion"), "status_raw": status,
                   "online_status": "ONLINE" if online else "OFFLINE", "uptime": d.get("uptime"), "cpu": d.get("cpuUtil"), "mem": d.get("memUtil"),
                   "clients": d.get("clientNum"), "last_seen": d.get("lastSeen"), "client_id": (link or {}).get("client_id"),
                   "client_name": (link or {}).get("client_name"), "updated_at": now}
            await db.omada_devices.update_one({"controller_id": ctrl_id, "site_id": sid, "mac": mac}, {"$set": doc}, upsert=True)
            stats["devices"] += 1
            if dtype == "switch" and online:
                stats["ports"] += await _sync_switch_ports(ctrl_id, sid, {**d, "mac": d.get("mac")}, (link or {}).get("client_id"))
    await db.omada_settings.update_one({"id": ctrl_id}, {"$set": {"last_sync_at": now, "last_sync_stats": stats, "last_error": None,
                                                                  "last_sync_duration_s": round(time.time() - t0, 1)}})
    return stats


async def omada_sync_tick() -> dict:
    out = {}
    async for ctrl in db.omada_settings.find({"id": {"$ne": "global"}, "enabled": True, "client_secret_enc": {"$exists": True}}, {"_id": 0}):
        out[ctrl.get("name") or ctrl["id"]] = await _sync_controller(ctrl)
    return out or {"skipped": True}


@router.post("/omada/sync")
async def sync_now(ctrl_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    if ctrl_id:
        ctrl = await db.omada_settings.find_one({"id": ctrl_id}, {"_id": 0})
        if not ctrl:
            raise HTTPException(status_code=404, detail="Controller non trovato")
        return await _sync_controller(ctrl)
    return await omada_sync_tick()


# ==================== Siti / device / link ====================
@router.get("/omada/sites")
async def list_sites(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    links = {(l.get("controller_id"), l["site_id"]): l async for l in db.omada_client_links.find({}, {"_id": 0})}
    out = []
    async for s in db.omada_sites_cache.find({}, {"_id": 0}).sort([("controller_name", 1), ("name", 1)]):
        l = links.get((s.get("controller_id"), s["site_id"])) or {}
        out.append({**s, "linked_client_id": l.get("client_id"), "linked_client_name": l.get("client_name"),
                    "devices": await db.omada_devices.count_documents({"controller_id": s.get("controller_id"), "site_id": s["site_id"]})})
    return {"sites": out}


@router.get("/omada/devices")
async def list_devices(client_id: Optional[str] = None, site_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    q: dict = {}
    if client_id:
        q["client_id"] = client_id
    if site_id:
        q["site_id"] = site_id
    if current_user.get("role") != "admin":
        q["client_id"] = current_user.get("client_id")
    return {"devices": [d async for d in db.omada_devices.find(q, {"_id": 0}).sort([("site_name", 1), ("device_type", 1), ("name", 1)])]}


@router.get("/omada/discover-gateways")
async def discover_gateways(current_user: dict = Depends(get_current_user)):
    """Gateway Omada (da cache sync) per il wizard Nuovo Cliente — stesso formato di /zyxel/discover-gateways."""
    require_admin(current_user)
    out = []
    async for d in db.omada_devices.find({"device_type": "firewall"}, {"_id": 0}):
        out.append({"org_id": d.get("controller_id"), "org_name": f"Omada · {d.get('controller_name') or ''}", "site_id": d["site_id"], "site_name": d.get("site_name"), "dev_id": d["mac"],
                    "name": d.get("name"), "model": d.get("model"), "mac": d["mac"], "online_status": d.get("online_status"),
                    "public_ip": d.get("public_ip"), "lan_ip": d.get("ip"), "linked_client_id": d.get("client_id"), "linked_client_name": d.get("client_name"), "vendor": "omada"})
    return {"gateways": out}


class LinkIn(BaseModel):
    site_id: str
    controller_id: Optional[str] = None


@router.put("/clients/{client_id}/omada/link")
async def link_client(client_id: str, body: LinkIn, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    cl = await db.clients.find_one({"id": client_id}, {"_id": 0, "name": 1})
    if not cl:
        raise HTTPException(status_code=404, detail="Cliente non trovato")
    sq = {"site_id": body.site_id} | ({"controller_id": body.controller_id} if body.controller_id else {})
    site = await db.omada_sites_cache.find_one(sq, {"_id": 0})
    ctrl_id = body.controller_id or (site or {}).get("controller_id")
    doc = {"client_id": client_id, "client_name": cl["name"], "controller_id": ctrl_id, "site_id": body.site_id, "site_name": (site or {}).get("name"),
           "linked_at": _now_iso(), "by": current_user.get("email")}
    await db.omada_client_links.update_one({"controller_id": ctrl_id, "site_id": body.site_id}, {"$set": doc}, upsert=True)
    await db.omada_devices.update_many({"controller_id": ctrl_id, "site_id": body.site_id}, {"$set": {"client_id": client_id, "client_name": cl["name"]}})
    return doc


@router.delete("/clients/{client_id}/omada/link/{site_id}")
async def unlink_client(client_id: str, site_id: str, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    await db.omada_client_links.delete_one({"client_id": client_id, "site_id": site_id})
    await db.omada_devices.update_many({"site_id": site_id}, {"$unset": {"client_id": "", "client_name": ""}})
    return {"ok": True}


@router.get("/clients/{client_id}/omada/link")
async def get_links(client_id: str, current_user: dict = Depends(get_current_user)):
    return {"links": [l async for l in db.omada_client_links.find({"client_id": client_id}, {"_id": 0})]}
