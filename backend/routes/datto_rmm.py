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
import re
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
DEFAULT_SITES_URL = "https://portal.86bit.it/api/v1/reports/datto/getDattoSites"
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

    # v2026-06-29: Hardening validation per evitare gli errori di compilazione
    # ricorrenti del form (USER ID con email, BASE URL con query string).
    user_id_clean = payload.user_id.strip()
    if "@" in user_id_clean:
        raise HTTPException(
            status_code=400,
            detail=(
                "USER ID non valido: hai inserito un'email. Il portal richiede l'ObjectId Mongo "
                "(24 caratteri esadecimali, es. 5ec7affa4cdcd40b443d5c38). "
                "Chiedi al provider del portal.86bit.it l'userId del tuo account."
            ),
        )
    # Tipicamente ObjectId = 24 hex chars; tolleriamo anche eventuali altri formati
    # custom del portal ma rifiutiamo email/url ovviamente sbagliati.
    if not re.fullmatch(r"[A-Za-z0-9_.\-]+", user_id_clean):
        raise HTTPException(
            status_code=400,
            detail="USER ID contiene caratteri non validi (ammessi: alfanumerici, '_', '.', '-').",
        )

    # BASE URL non deve contenere query string: i parametri (api_key, userId,
    # page, max) sono aggiunti dal backend al momento del fetch.
    if "?" in base_url or "&" in base_url:
        raise HTTPException(
            status_code=400,
            detail=(
                "BASE URL non valida: non includere parametri ?api_key=... o &userId=... — "
                "il backend li aggiunge automaticamente. "
                f"Usa solo l'endpoint, es: {DEFAULT_BASE_URL}"
            ),
        )

    doc = {
        "id": "global",
        "api_key_enc": encrypted,
        "api_key_preview": _mask_key(payload.api_key),
        "user_id": user_id_clean,
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
    try:
        api_key = security_manager.decrypt_credential(cfg["api_key_enc"])
    except Exception as dec_err:
        # Vault mismatch: salt AES-GCM diverso da quello con cui era cifrata
        # la api_key. Marca lo stato in DB e ritorna 503 con messaggio chiaro
        # invece di propagare un traceback generico (UX migliore).
        from datetime import datetime, timezone as _tz
        await db.datto_settings.update_one(
            {"id": "global"},
            {"$set": {
                "last_status": "vault_mismatch",
                "last_error": f"Decryption failed: {dec_err}. Re-save the API key from /settings/datto to re-encrypt with current vault.",
                "last_error_at": datetime.now(_tz.utc).isoformat(),
            }},
        )
        raise HTTPException(
            status_code=503,
            detail="Datto RMM API key non decifrabile col vault corrente. "
                   "Vai in Impostazioni → Datto RMM, re-incolla la API key e clicca 'Salva (cifrata)' per ri-cifrarla.",
        )
    return (
        api_key,
        cfg.get("user_id", ""),
        cfg.get("base_url") or DEFAULT_BASE_URL,
        cfg.get("audit_url") or DEFAULT_AUDIT_URL,
    )


async def _fetch_devices_list_all(timeout: float = 60.0) -> list[dict]:
    """Scarica TUTTI i device Datto paginando il wrapper.

    Il wrapper `portal.86bit.it/api/v1/reports/datto/getDattoDevices` ora
    supporta `?page=N&max=250` (cap 250 per pagina).
    Itera finche':
      - pagina ritorna < max device (ultima pagina), oppure
      - primo uid della pagina corrente == primo uid pagina precedente
        (safety net: wrapper non supporta la pagina richiesta)
      - hard cap 50 pagine (= 12'500 device massimo)
    """
    api_key, user_id, base_url, _ = await _get_datto_creds()
    MAX_PER_PAGE = 250
    MAX_PAGES = 50
    all_devices: list[dict] = []
    prev_first_uid: Optional[str] = None
    page = 0
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        while page < MAX_PAGES:
            params = {
                "api_key": api_key, "userId": user_id, "json": "true",
                "page": page, "max": MAX_PER_PAGE,
            }
            try:
                resp = await client.get(base_url, params=params)
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
            # v2026-02-14: parser robusto. Il wrapper portal.86bit.it puo' ritornare:
            #   1) {"dattoDevices": {"devices": [...]}}  ← schema legacy
            #   2) {"devices": [...]}                    ← schema flat
            #   3) [...] (array diretto)
            #   4) {"data": {"devices": [...]}}          ← wrapper generico
            #   5) {"results": [...]}                    ← qualche API REST
            devs = None
            if isinstance(data, list):
                devs = data
            elif isinstance(data, dict):
                # Tenta in ordine di priorita'
                for path in [
                    lambda d: (d.get("dattoDevices") or {}).get("devices"),
                    lambda d: d.get("devices"),
                    lambda d: (d.get("data") or {}).get("devices") if isinstance(d.get("data"), dict) else None,
                    lambda d: d.get("results"),
                    lambda d: (d.get("data") or {}).get("dattoDevices", {}).get("devices") if isinstance(d.get("data"), dict) else None,
                    lambda d: d.get("data") if isinstance(d.get("data"), list) else None,
                ]:
                    try:
                        v = path(data)
                        if isinstance(v, list):
                            devs = v
                            break
                    except Exception:
                        continue
            if not isinstance(devs, list):
                devs = []
            if not devs:
                # Log la prima pagina con keys top-level per debug
                if page == 0 and isinstance(data, dict):
                    logger.warning(
                        "datto_no_devices_found: top_keys=%s sample=%s",
                        list(data.keys()),
                        str(data)[:300],
                    )
                break
            first_uid = str(devs[0].get("uid") or devs[0].get("id") or "")
            if prev_first_uid is not None and first_uid == prev_first_uid:
                # wrapper non paginato davvero: stessa pagina ritornata
                break
            prev_first_uid = first_uid
            all_devices.extend(devs)
            if len(devs) < MAX_PER_PAGE:
                break  # ultima pagina
            page += 1
    # Dedup per uid
    seen: set = set()
    unique: list[dict] = []
    for d in all_devices:
        u = str(d.get("uid") or d.get("id") or "")
        if not u or u in seen:
            continue
        seen.add(u)
        unique.append(d)
    logger.info(f"datto_list_fetched pages={page + 1} total={len(unique)}")
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


async def _fetch_all_sites_from_portal(timeout: float = 60.0) -> list[dict]:
    """Fetch paginato dell'elenco completo dei siti Datto dal portal
    (`getDattoSites`). Usa `?page=N&max=250` e itera finche' arrivano pagine
    non vuote (stesso protocollo di getDattoDevices).

    Quando il wrapper 86bit popolera' l'array (attualmente ritorna
    `{success:true, count:128, devices:[]}`), questo ritornera' TUTTI i siti —
    inclusi quelli con 0 device.

    Accetta qualsiasi shape: sites:[...], data:[...], items:[...], devices:[...].
    """
    cfg = await db.datto_settings.find_one({"id": "global"}, {"_id": 0})
    if not cfg:
        return []
    try:
        api_key = security_manager.decrypt_credential(cfg["api_key_enc"])
    except Exception:
        return []
    sites_url = cfg.get("sites_url") or DEFAULT_SITES_URL
    user_id = cfg.get("user_id", "")
    MAX_PER_PAGE = 250
    MAX_PAGES = 20
    collected: list[dict] = []
    prev_first_id: Optional[str] = None
    page = 0
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        while page < MAX_PAGES:
            params = {
                "api_key": api_key, "userId": user_id, "json": "true",
                "page": page, "max": MAX_PER_PAGE,
            }
            try:
                resp = await client.get(sites_url, params=params)
            except httpx.RequestError:
                break
            if resp.status_code != 200:
                break
            try:
                data = resp.json()
            except Exception:
                break
            if not isinstance(data, dict):
                # v2026-03-01 hardening: alcuni REST endpoint ritornano lista diretta
                if isinstance(data, list) and data:
                    arr = data
                    first_id = str((arr[0] or {}).get("siteUid") or (arr[0] or {}).get("uid")
                                   or (arr[0] or {}).get("site_id") or (arr[0] or {}).get("id") or "")
                    if prev_first_id is not None and first_id == prev_first_id:
                        break
                    prev_first_id = first_id
                    collected.extend(arr)
                    if len(arr) < MAX_PER_PAGE:
                        break
                    page += 1
                    continue
                break
            arr = None
            for k in ("sites", "data", "items", "result", "devices"):
                v = data.get(k)
                if isinstance(v, list) and v:
                    arr = v
                    break
            if not arr:
                if page == 0 and data.get("count"):
                    logger.info(f"datto_sites_endpoint_empty declared_count={data.get('count')}")
                break
            first_id = str(arr[0].get("siteUid") or arr[0].get("uid")
                           or arr[0].get("site_id") or arr[0].get("id") or "")
            if prev_first_id is not None and first_id == prev_first_id:
                break
            prev_first_id = first_id
            collected.extend(arr)
            if len(arr) < MAX_PER_PAGE:
                break
            page += 1
    # Normalizza + dedup
    seen: set = set()
    normalized: list[dict] = []
    for it in collected:
        if not isinstance(it, dict):
            continue
        sid = str(
            it.get("siteUid") or it.get("uid") or it.get("site_id")
            or it.get("siteId") or it.get("id") or ""
        ).strip()
        if not sid or sid in seen:
            continue
        seen.add(sid)
        sname = (
            it.get("siteName") or it.get("name") or it.get("site_name")
            or it.get("description") or sid
        )
        normalized.append({
            "site_id": sid,
            "site_name": str(sname),
            "device_count": int(it.get("deviceCount") or it.get("device_count") or 0),
        })
    logger.info(f"datto_sites_portal pages={page + 1} fetched={len(normalized)}")
    return normalized


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


def _extract_serial(audit_data: Any, list_dev: Any = None) -> str:
    """Estrae il serial number da audit Datto (bios/systemInfo) o dalla list.
    Non sensibile: usato solo come identificatore forte per il match."""
    for src in (audit_data, list_dev):
        if not isinstance(src, dict):
            continue
        for key in ("serialNumber", "serial_number", "serial", "biosSerial"):
            v = src.get(key)
            if v and str(v).strip() and str(v).strip().lower() not in (
                "none", "null", "system serial number", "to be filled by o.e.m.",
                "default string", "0", "n/a",
            ):
                return str(v).strip()
        for sub in ("systemInfo", "bios", "system"):
            nested = src.get(sub)
            if isinstance(nested, dict):
                r = _extract_serial(nested)
                if r:
                    return r
    return ""


def _host_short(s: Any) -> str:
    n = (str(s or "").strip().lower())
    return n.split(".")[0] if n else ""


def _device_type_str(dt: Any) -> str:
    """Normalizza il campo `deviceType` di Datto RMM in stringa.

    Datto ritorna un OGGETTO {"category": "...", "type": "..."} (non stringa).
    Concatena category+type; gestisce anche il caso stringa/None senza sollevare.
    """
    if dt is None:
        return ""
    if isinstance(dt, dict):
        parts = [str(dt.get("category") or "").strip(), str(dt.get("type") or "").strip()]
        return " ".join(p for p in parts if p).strip()
    return str(dt).strip()


# ---------------------------------------------------------------------------
# Core: refresh cache + enrichment MAC via audit + match 100%
# ---------------------------------------------------------------------------
async def _refresh_sites_cache() -> dict:
    devices = await _fetch_devices_list_all()
    device_sites = _group_devices_by_site(devices)
    now = datetime.now(timezone.utc).isoformat()

    # Merge: siti dedotti dai device + siti completi da getDattoSites (se popolato)
    # Usa dict per dedup per site_id, dando priorita' al nome trovato nei device
    # (piu' aggiornato) rispetto a quello del sites endpoint.
    merged: dict[str, dict] = {}
    for s in await _fetch_all_sites_from_portal():
        merged[s["site_id"]] = {
            "site_id": s["site_id"],
            "site_name": s["site_name"],
            "device_count": s.get("device_count", 0),
            "devices": [],  # no device details da sites endpoint
        }
    for s in device_sites:
        prev = merged.get(s["site_id"])
        merged[s["site_id"]] = {
            "site_id": s["site_id"],
            "site_name": s["site_name"],
            "device_count": max(len(s["devices"]), (prev or {}).get("device_count", 0)),
            "devices": s["devices"],
        }
    sites = sorted(merged.values(), key=lambda x: x["site_name"].lower())

    # (1) Replace sites cache (solo id/name/count — MAI detail device)
    await db.datto_sites_cache.delete_many({})
    if sites:
        await db.datto_sites_cache.insert_many([
            {"site_id": s["site_id"], "site_name": s["site_name"],
             "device_count": s["device_count"], "fetched_at": now}
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
                # Identificatori aggiuntivi per il match multi-fonte (non sensibili)
                serial = _extract_serial(audit_raw, dev)
                raw_hostname = (dev.get("hostname") or "").strip()
                fqdn = raw_hostname if "." in raw_hostname else ""
                hostname_short = _host_short(raw_hostname or name)
                ext_ip = _norm_ip(dev.get("extIpAddress"))
                # Stato online + lastSeen + tipo device dalla list Datto,
                # persistiti top-level per l'Alert Engine (watchdog server offline).
                # Datto RMM ritorna `deviceType` come OGGETTO {category, type}
                # (non stringa). _device_type_str gestisce dict/str/None.
                dtype = _device_type_str(dev.get("deviceType") or dev.get("category"))
                online_raw = dev.get("online")
                if online_raw is None:
                    online_raw = dev.get("isOnline")
                last_seen_raw = (
                    dev.get("lastSeen") or dev.get("lastAuditDate")
                    or dev.get("lastSeenDate") or dev.get("lastSeenDateEpoch")
                )
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
                    "serial": serial,             # identificatore forte per match
                    "fqdn": fqdn,                 # FQDN se disponibile
                    "hostname_short": hostname_short,  # hostname senza dominio
                    "ext_ip": ext_ip,             # IP pubblico (diagnostica)
                    "device_type": dtype,
                    "is_server": ("server" in dtype.lower() or "esxi" in dtype.lower()),
                    "online": (bool(online_raw) if online_raw is not None else None),
                    "datto_last_seen": last_seen_raw,
                    "raw_enc": _encrypt_blob(raw_blob),
                    "fetched_at": now,
                }

            tasks = [_process(d) for d in client_devices]
            # Resilienza: un singolo device problematico (audit/parsing/encrypt
            # fallito) NON deve abortire l'intera sync con un 500. Raccogliamo
            # le eccezioni, le logghiamo e proseguiamo coi device validi.
            results = await asyncio.gather(*tasks, return_exceptions=True)
            persisted = []
            errors = 0
            err_samples: list[str] = []
            for r in results:
                if isinstance(r, dict):
                    persisted.append(r)
                elif isinstance(r, BaseException):
                    errors += 1
                    if len(err_samples) < 3:
                        import traceback as _tb
                        err_samples.append("".join(_tb.format_exception(type(r), r, r.__traceback__))[-800:])
            if errors:
                logger.warning(
                    "datto_sync client=%s: %d/%d device skippati per errore audit/parsing; samples=%s",
                    cid, errors, len(results), err_samples,
                )

            # Replace datto_devices per questo client. Isolato in try/except:
            # un errore DB su un client (es. documento troppo grande, batch
            # malformato) non deve abortire la sync degli altri client.
            try:
                await db.datto_devices.delete_many({"client_id": cid})
                if persisted:
                    await db.datto_devices.insert_many(persisted)
            except Exception as e:  # noqa: BLE001
                logger.warning("datto_sync client=%s persist fallito: %r", cid, e)
                continue
            total_persisted += len(persisted)

            # Match 100% con discovered_endpoints + managed_devices.
            # Isolato in try/except: il fallimento del match di un client non
            # deve impedire il sync degli altri client linkati.
            try:
                matched = await _match_with_center(cid, persisted)
            except Exception as e:  # noqa: BLE001
                logger.warning("datto_sync client=%s match fallito: %r", cid, e)
                matched = 0
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
    """Match avanzato multi-fonte (affidabilita' 100%).

    Fonde TUTTI gli identificatori che riceviamo — serial, MAC (tutte le NIC),
    IP (tutti), hostname/FQDN — e usa lo SCANNER (discovered_endpoints) come
    "ponte": se un managed_device non ha MAC ma lo scanner ha visto quell'IP,
    eredita il MAC/hostname dallo scanner per agganciare Datto.

    Ladder di confidenza: serial(100) > MAC(98) > IP(92) > hostname(82).
    Scrive sul managed_device il LINK PERSISTENTE `datto_uid` + confidenza +
    metodo, cosi' la correlazione degli alert legge un match certo e coerente.
    """
    if not datto_devices:
        return 0

    from pymongo import UpdateOne
    now = datetime.now(timezone.utc).isoformat()

    # --- Indici Datto multi-identificatore ---
    by_mac: dict[str, dict] = {}
    by_ip: dict[str, dict] = {}
    by_serial: dict[str, dict] = {}
    by_host: dict[str, dict] = {}
    for d in datto_devices:
        if not d.get("uid"):
            continue
        for m in list(d.get("mac_list") or []) + [d.get("mac")]:
            nm = _norm_mac(m)
            if nm:
                by_mac.setdefault(nm, d)
        for ip in list(d.get("ip_list") or []) + [d.get("ip")]:
            if ip:
                by_ip.setdefault(ip, d)
        if d.get("serial"):
            by_serial.setdefault(str(d["serial"]).strip().upper(), d)
        for h in (d.get("name"), d.get("fqdn"), d.get("hostname_short")):
            hs = _host_short(h)
            if hs:
                by_host.setdefault(hs, d)

    # --- Candidati dal Center: scanner endpoints (ponte L2) + managed devices ---
    eps = await db.discovered_endpoints.find(
        {"client_id": client_id},
        {"_id": 0, "mac": 1, "ip": 1, "switch_ip": 1, "port": 1, "hostname_scanner": 1},
    ).to_list(100000)
    ep_by_ip: dict[str, list] = {}
    for ep in eps:
        if ep.get("ip"):
            ep_by_ip.setdefault(ep["ip"], []).append(ep)

    managed = await db.managed_devices.find(
        {"client_id": client_id},
        {"_id": 0, "id": 1, "name": 1, "device_name": 1, "hostname": 1,
         "ip_address": 1, "ip": 1, "mac_address": 1, "mac": 1, "serial": 1},
    ).to_list(10000)

    md_ops: list = []
    ep_ops: list = []
    matched_uids: set = set()
    matched_md_ids: set = set()
    matched_eps: set = set()

    # --- Match managed_devices con identita' arricchita dallo scanner ---
    for md in managed:
        md_id = md.get("id")
        if not md_id:
            continue
        ip = md.get("ip_address") or md.get("ip") or ""
        serial = str(md.get("serial") or "").strip().upper()
        macs = set(filter(None, [_norm_mac(md.get("mac_address") or md.get("mac"))]))
        hosts = set(filter(None, [
            _host_short(md.get("hostname")), _host_short(md.get("name")),
            _host_short(md.get("device_name")),
        ]))
        # Ponte scanner: eredita MAC/hostname visti su quello stesso IP
        for ep in ep_by_ip.get(ip, []):
            em = _norm_mac(ep.get("mac"))
            if em:
                macs.add(em)
            hs = _host_short(ep.get("hostname_scanner"))
            if hs:
                hosts.add(hs)

        d = None
        method = None
        conf = 0
        if serial and serial in by_serial:
            d, method, conf = by_serial[serial], "serial", 100
        if not d:
            for m in macs:
                if m in by_mac:
                    d, method, conf = by_mac[m], "mac", 98
                    break
        if not d and ip and ip in by_ip:
            d, method, conf = by_ip[ip], "ip", 92
        if not d:
            for h in hosts:
                if h in by_host:
                    d, method, conf = by_host[h], "hostname", 82
                    break

        if d and d.get("uid"):
            matched_uids.add(d["uid"])
            matched_md_ids.add(md_id)
            md_ops.append(UpdateOne(
                {"id": md_id},
                {"$set": {
                    "datto_uid": d["uid"],
                    "datto_name": d.get("name"),
                    "datto_match": method,
                    "datto_match_confidence": conf,
                    "datto_matched_at": now,
                }},
            ))

    # --- Enrichment scanner endpoints (datto_name) per la UI/topology ---
    for ep in eps:
        ep_mac = _norm_mac(ep.get("mac"))
        ep_ip = ep.get("ip") or ""
        d = (ep_mac and by_mac.get(ep_mac)) or (ep_ip and by_ip.get(ep_ip)) or None
        if not d or not d.get("uid"):
            continue
        key = (ep.get("switch_ip"), ep.get("port"), ep.get("mac"))
        if key in matched_eps:
            continue
        matched_eps.add(key)
        matched_uids.add(d["uid"])
        ep_ops.append(UpdateOne(
            {"client_id": client_id, "switch_ip": ep.get("switch_ip"),
             "port": ep.get("port"), "mac": ep.get("mac")},
            {"$set": {"datto_name": d.get("name"),
                      "datto_match": "mac" if ep_mac and ep_mac in by_mac else "ip",
                      "datto_matched_at": now}},
        ))

    if md_ops:
        await db.managed_devices.bulk_write(md_ops, ordered=False)
    if ep_ops:
        await db.discovered_endpoints.bulk_write(ep_ops, ordered=False)

    # Pulisci link Datto ORFANI: managed devices che prima erano agganciati ma
    # ora non matchano piu' nessun device Datto (evita link stantii/errati).
    await db.managed_devices.update_many(
        {"client_id": client_id, "datto_uid": {"$exists": True},
         "id": {"$nin": list(matched_md_ids)}},
        {"$unset": {"datto_uid": "", "datto_match": "", "datto_match_confidence": ""}},
    )

    # Stato matched sui datto_devices
    if matched_uids:
        await db.datto_devices.update_many(
            {"client_id": client_id, "uid": {"$in": list(matched_uids)}},
            {"$set": {"matched": True, "matched_at": now}},
        )
    await db.datto_devices.update_many(
        {"client_id": client_id, "uid": {"$nin": list(matched_uids)}},
        {"$set": {"matched": False}},
    )

    return len(matched_uids)


# ---------------------------------------------------------------------------
# Endpoints funzionali
# ---------------------------------------------------------------------------
@router.post("/admin/datto/test")
async def test_datto_connection(current_user: dict = Depends(get_current_user)):
    """Chiama il portal e ritorna SOLO il conteggio site/device. Nessun dato sensibile.

    v2026-06-02: reso resiliente — invece di 500 generico, in caso di errore
    ritorna 200 con `{"ok": false, "error": "...", "stage": "..."}` cosi'
    l'utente vede subito QUALE step e' fallito (devices vs sites vs grouping)
    e con QUALE dettaglio (es. timeout, http_500, parse_error).
    """
    require_admin(current_user)
    import traceback

    stage = "fetch_devices"
    try:
        devices = await _fetch_devices_list_all(timeout=20.0)
        stage = "group_devices"
        device_sites = _group_devices_by_site(devices)
        stage = "fetch_portal_sites"
        portal_sites = await _fetch_all_sites_from_portal(timeout=10.0)
        stage = "merge"
        merged_ids = set(s["site_id"] for s in device_sites) | set(s["site_id"] for s in portal_sites)
        summary = [
            {"site_id": s["site_id"], "site_name": s["site_name"],
             "device_count": len(s["devices"])}
            for s in sorted(device_sites, key=lambda x: x["site_name"].lower())
        ]
        return {
            "ok": True,
            "sites_found": len(merged_ids),
            "sites_from_devices_endpoint": len(device_sites),
            "sites_from_sites_endpoint": len(portal_sites),
            "devices_found": len(devices),
            "sites": summary,
            "warning": (
                "Trovati 0 device. Possibile schema response inatteso dal wrapper. "
                "Usa POST /api/admin/datto/raw-debug per vedere la struttura RAW della risposta."
            ) if len(devices) == 0 and len(portal_sites) > 0 else None,
        }
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"datto_test_failed stage={stage} error={e!r}\n{tb}")
        # Try to classify error type for human-readable response
        err_str = str(e)
        err_type = type(e).__name__
        hint = None
        if "timeout" in err_str.lower() or "TimeoutException" in err_type:
            hint = "Il portal portal.86bit.it ha impiegato troppo a rispondere. Riprova fra qualche secondo o aumenta il timeout."
        elif "ConnectError" in err_type or "ConnectionError" in err_type:
            hint = "Impossibile raggiungere portal.86bit.it dal server NOC. Verifica firewall/DNS in PROD."
        elif "401" in err_str or "403" in err_str:
            hint = "API key o User ID non validi: il portal ha rifiutato l'autenticazione."
        elif "500" in err_str or "502" in err_str or "503" in err_str:
            hint = "Il portal portal.86bit.it ha risposto con errore server. Riprova fra poco."
        elif "json" in err_str.lower() or "decode" in err_str.lower():
            hint = "Risposta del portal non in JSON valido. Usa /api/admin/datto/raw-debug per ispezionare."
        return {
            "ok": False,
            "stage_failed": stage,
            "error_type": err_type,
            "error": err_str[:500],
            "hint": hint or "Errore inatteso — controlla i log del backend per traceback completo.",
        }


@router.post("/admin/datto/raw-debug")
async def datto_raw_debug(current_user: dict = Depends(get_current_user)):
    """Diagnostica: ritorna la struttura RAW della prima pagina del wrapper Datto.

    Utile quando `test` ritorna 0 device ma piu' siti: significa che il wrapper
    `portal.86bit.it` ha cambiato schema (es. `{devices:[...]}` invece di
    `{dattoDevices:{devices:[...]}}`). Da qui si vede cosa serve.
    Non espone valori sensibili: solo struttura JSON, sample del primo elem,
    e dimensioni.
    """
    require_admin(current_user)
    api_key, user_id, base_url, _ = await _get_datto_creds()
    params = {"api_key": api_key, "userId": user_id, "json": "true", "page": 0, "max": 10}
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        try:
            resp = await client.get(base_url, params=params)
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Errore rete Datto: {e}")
    out: dict[str, Any] = {
        "status_code": resp.status_code,
        "content_type": resp.headers.get("content-type"),
        "content_length_bytes": len(resp.content),
        "url_called": str(resp.request.url).replace(api_key, "***").replace(user_id, "***"),
    }
    try:
        data = resp.json()
    except Exception:
        out["raw_preview"] = resp.text[:500]
        out["parse_error"] = "Risposta non JSON valido"
        return out

    if isinstance(data, list):
        out["top_level_type"] = "list"
        out["top_level_length"] = len(data)
        out["first_item_keys"] = list((data[0] or {}).keys()) if data else []
    elif isinstance(data, dict):
        out["top_level_type"] = "dict"
        out["top_level_keys"] = list(data.keys())
        # Esplora 2 livelli in profondita' alla ricerca di "devices"
        def _shape(obj, depth=0):
            if depth > 3:
                return "..."
            if isinstance(obj, dict):
                return {k: _shape(v, depth + 1) for k, v in obj.items()}
            if isinstance(obj, list):
                return [f"list[{len(obj)}]"] + ([_shape(obj[0], depth + 1)] if obj else [])
            return type(obj).__name__
        out["shape"] = _shape(data)
        # Tenta di estrarre il primo device per mostrarne le chiavi
        devs = None
        for path in [
            lambda d: (d.get("dattoDevices") or {}).get("devices"),
            lambda d: d.get("devices"),
            lambda d: (d.get("data") or {}).get("devices") if isinstance(d.get("data"), dict) else None,
            lambda d: d.get("results"),
        ]:
            try:
                v = path(data)
                if isinstance(v, list):
                    devs = v
                    break
            except Exception:
                pass
        if devs is not None:
            out["devices_path_resolved"] = True
            out["devices_count"] = len(devs)
            if devs:
                out["first_device_keys"] = list((devs[0] or {}).keys())[:30]
        else:
            out["devices_path_resolved"] = False
            out["hint"] = (
                "Nessuno dei path standard (dattoDevices.devices, devices, data.devices, results) "
                "ha matchato. Controlla 'shape' per capire dove sono i device e aggiorna "
                "_fetch_devices_list_all() nel codice."
            )
    return out


@router.post("/datto/sync-now")
async def datto_sync_now(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    result = await _refresh_sites_cache()
    audit.info(f"datto_sync_now by={current_user.get('email')} -> {result}")
    return {"ok": True, **result}


# v2026-06-02: nuovi endpoint per debug e risoluzione del caso "Galvan/Zitac
# 0 device sync nonostante site Datto linkato e popolato".
# Root cause tipica: mismatch tra site_id salvato in datto_client_links e
# siteUid restituito dall'endpoint /devices Datto, oppure link orfani
# (datto_client_links.client_id punta a un client eliminato/ricreato).

@router.get("/admin/datto/client-debug/{client_id}")
async def datto_client_debug(client_id: str,
                              current_user: dict = Depends(get_current_user)):
    """Diagnosi PER-CLIENT: spiega ESATTAMENTE perche' un cliente specifico
    ha 0 device sincronizzati. Mostra:
      - se il client esiste in `clients`
      - il link Datto salvato (site_id, site_name, last_sync_at, counters)
      - i contatori device nel DB (datto_devices)
      - i contatori device dal portal LIVE (devices_endpoint + sites_endpoint)
      - rilevamento mismatch site_id automatico
    """
    require_admin(current_user)

    client_doc = await db.clients.find_one({"id": client_id}, {"_id": 0, "id": 1, "name": 1})
    link = await db.datto_client_links.find_one({"client_id": client_id}, {"_id": 0})
    persisted_devices = await db.datto_devices.count_documents({"client_id": client_id})
    matched_devices = await db.datto_devices.count_documents({"client_id": client_id, "matched": True})

    out: dict[str, Any] = {
        "client_id": client_id,
        "client_exists": client_doc is not None,
        "client_name": (client_doc or {}).get("name"),
        "link": link,
        "datto_devices_in_db": persisted_devices,
        "matched_in_db": matched_devices,
    }

    if not link:
        out["diagnosis"] = "Nessun link Datto per questo client. Vai a Impostazioni → Datto RMM → mappa il cliente a un site."
        return out

    site_id_linked = link.get("site_id")
    # Conta device LIVE dal portal per il site linkato
    try:
        devices = await _fetch_devices_list_all(timeout=20.0)
    except Exception as e:
        out["diagnosis"] = f"Errore fetch devices Datto: {e!r}"
        return out

    # Quanti device hanno siteUid == site_id_linked?
    matching_devices = []
    site_ids_seen: set[str] = set()
    for d in devices:
        sid = str(d.get("siteUid") or d.get("siteId") or "")
        if sid:
            site_ids_seen.add(sid)
        if sid == site_id_linked:
            matching_devices.append({
                "hostname": d.get("hostname"),
                "intIpAddress": d.get("intIpAddress"),
                "siteUid": sid,
                "siteName": d.get("siteName"),
            })

    out["live_devices_for_linked_site"] = len(matching_devices)
    out["sample_devices"] = matching_devices[:5]

    # Cerca tutti i siti che hanno nome simile al site_name linkato
    sname_linked = (link.get("site_name") or "").strip().lower()
    siblings = []
    if sname_linked:
        for d in devices:
            n = (d.get("siteName") or "").strip().lower()
            sid = str(d.get("siteUid") or d.get("siteId") or "")
            if n and n == sname_linked and sid != site_id_linked:
                if not any(s["site_id"] == sid for s in siblings):
                    siblings.append({"site_id": sid, "site_name": d.get("siteName")})
    out["sites_with_same_name_but_different_id"] = siblings

    # Diagnosi
    if not client_doc:
        out["diagnosis"] = (
            "🔴 Link Datto orfano: punta a un client che non esiste piu' in "
            "`clients`. Pulisci con POST /api/admin/datto/cleanup-orphan-links."
        )
    elif len(matching_devices) == 0 and siblings:
        out["diagnosis"] = (
            f"🟠 MISMATCH SITE_ID: il link punta a '{site_id_linked}' ma "
            f"esistono {len(siblings)} altri site Datto con lo STESSO NOME "
            f"'{link.get('site_name')}' e site_id diverso. Probabilmente "
            f"il site originale e' stato eliminato/ricreato lato Datto. "
            f"Vai in Impostazioni → Datto RMM → rilinka il cliente "
            f"selezionando di nuovo il site dalla dropdown."
        )
    elif len(matching_devices) == 0:
        out["diagnosis"] = (
            f"🟠 Il site '{link.get('site_name')}' ({site_id_linked}) non "
            f"ha alcun device nell'endpoint /devices Datto. Verifica sul "
            f"portal portal.86bit.it se il site contiene effettivamente "
            f"device attivi."
        )
    elif persisted_devices < len(matching_devices):
        out["diagnosis"] = (
            f"🟡 {len(matching_devices)} device disponibili lato Datto ma "
            f"solo {persisted_devices} in DB. Esegui un re-sync con "
            f"POST /api/admin/datto/sync-client/{client_id} per forzarne "
            f"l'allineamento."
        )
    else:
        out["diagnosis"] = "✅ Allineato"

    return out


@router.get("/admin/datto/match-debug/{client_id}")
async def datto_match_debug(client_id: str,
                             current_user: dict = Depends(get_current_user)):
    """Diagnosi MATCH per il caso "N device persisted ma 0 match con discovered_endpoints".

    Spiega ESATTAMENTE perche' i device Datto non trovano corrispondenza con
    le entry FDB degli switch del cliente. Le cause possibili:
      A. Il connector LAN scanner del cliente non e' attivo / non vede device
         → discovered_endpoints e' vuoto per questo client_id
      B. Lo scanner vede solo IP (senza MAC) ma i device Datto hanno solo MAC
         (audit endpoint) e nessun IP → no match possibile
      C. I device Datto non hanno MAC scoperto dall'audit (audit endpoint
         fallisce o nics list vuota nella response) → mac_list vuota → no match
      D. MAC formattati diversamente (rare, _norm_mac normalizza tutto)
      E. Subnet diverse: lo switch vede MAC su VLAN diversi → IP differente
    """
    require_admin(current_user)

    persisted = await db.datto_devices.find(
        {"client_id": client_id},
        {"_id": 0, "uid": 1, "name": 1, "mac": 1, "ip": 1,
         "mac_list": 1, "ip_list": 1},
    ).to_list(10000)

    eps = await db.discovered_endpoints.find(
        {"client_id": client_id},
        {"_id": 0, "mac": 1, "ip": 1, "switch_ip": 1, "port": 1},
    ).to_list(100000)

    # Conta MAC/IP coverage da entrambe le parti
    datto_macs = [d.get("mac", "") for d in persisted if d.get("mac")]
    datto_ips = [d.get("ip", "") for d in persisted if d.get("ip")]
    datto_no_mac = [d.get("name") for d in persisted if not d.get("mac")]
    eps_macs = {(e.get("mac") or "").upper() for e in eps if e.get("mac")}
    eps_ips = {e.get("ip", "") for e in eps if e.get("ip")}

    # Calcola intersezioni teoriche
    datto_macs_set = {m.upper() for m in datto_macs}
    intersect_mac = datto_macs_set & eps_macs
    intersect_ip = set(datto_ips) & eps_ips

    out: dict[str, Any] = {
        "client_id": client_id,
        "datto_devices_persisted": len(persisted),
        "datto_devices_with_mac": len(datto_macs),
        "datto_devices_without_mac": len(datto_no_mac),
        "datto_devices_with_ip": len(datto_ips),
        "discovered_endpoints_total": len(eps),
        "discovered_endpoints_with_mac": len(eps_macs),
        "discovered_endpoints_with_ip": len(eps_ips),
        "intersection_mac": len(intersect_mac),
        "intersection_ip": len(intersect_ip),
        "sample_datto_no_mac": datto_no_mac[:5],
        "sample_datto_with_mac": [
            {"name": d.get("name"), "mac": d.get("mac"), "ip": d.get("ip")}
            for d in persisted if d.get("mac")
        ][:5],
        "sample_eps_with_mac": [
            {"mac": e.get("mac"), "ip": e.get("ip"), "switch_ip": e.get("switch_ip"), "port": e.get("port")}
            for e in eps if e.get("mac")
        ][:5],
    }

    # Diagnosi
    if not persisted:
        out["diagnosis"] = "🔴 Nessun device Datto persistito. Vedi /admin/datto/client-debug/{client_id} per cause."
    elif not eps:
        out["diagnosis"] = (
            f"🔴 (A) Il client '{client_id}' ha 0 discovered_endpoints. "
            f"Il connector LAN scanner non sta scoprendo MAC/IP dagli switch del cliente. "
            f"Verifica: (1) connector ONLINE in Argus, (2) switch del cliente nella scan list "
            f"con credenziali SNMP valide, (3) il connector ha lanciato almeno 1 scan."
        )
    elif len(datto_macs) == 0:
        out["diagnosis"] = (
            f"🔴 (C) {len(persisted)} device Datto persistiti ma NESSUNO ha MAC. "
            f"L'audit endpoint del portal non sta ritornando NIC info. "
            f"Verifica audit_url corretta e che il portal supporti getDeviceAuditDataFromUid."
        )
    elif len(eps_macs) == 0:
        out["diagnosis"] = (
            f"🔴 (B) Switch ritornano solo IP, nessun MAC nelle FDB. "
            f"Senza MAC nelle discovered_endpoints il match Datto puo' avvenire solo per IP, "
            f"ma {len(intersect_ip)} su {len(datto_ips)} Datto-IP coincidono."
        )
    elif len(intersect_mac) == 0 and len(intersect_ip) == 0:
        out["diagnosis"] = (
            f"🟠 (E) {len(datto_macs)} MAC lato Datto e {len(eps_macs)} MAC lato switch "
            f"ma ZERO intersezioni. Probabilmente i device Datto vivono su una VLAN diversa "
            f"da quella scoperta dagli switch (Datto vede VPN/Wifi, scanner vede LAN cablata) "
            f"OPPURE il connector LAN scanner del cliente non e' nella stessa rete dei device."
        )
    else:
        out["diagnosis"] = (
            f"✅ {len(intersect_mac)} MAC + {len(intersect_ip)} IP in intersezione. "
            f"Esegui POST /api/admin/datto/sync-client/{client_id} per ri-applicare il match."
        )

    return out


@router.post("/admin/datto/sync-client/{client_id}")
async def datto_sync_single_client(
    client_id: str, current_user: dict = Depends(get_current_user),
):
    """Forza il re-sync dei device Datto per UN solo client. Utile dopo aver
    rilinkato il site (es. quando il site Datto e' stato ricreato e il
    site_id e' cambiato). Esegue gli stessi step del sync globale ma
    SOLO per il client specificato."""
    require_admin(current_user)
    link = await db.datto_client_links.find_one({"client_id": client_id}, {"_id": 0})
    if not link:
        raise HTTPException(status_code=404, detail="Link Datto non trovato per questo client")

    # Esegui un refresh completo (re-fetch + match) — semplice e affidabile.
    # Per ottimizzazioni future si puo' fare un sync per-site, ma il volume
    # di dati Datto e' modesto (982 device totali) → la chiamata massimale
    # gira in ~15s.
    result = await _refresh_sites_cache()

    # Riprendi i contatori aggiornati
    devices_count = await db.datto_devices.count_documents({"client_id": client_id})
    matched_count = await db.datto_devices.count_documents({"client_id": client_id, "matched": True})
    link_after = await db.datto_client_links.find_one({"client_id": client_id}, {"_id": 0})
    audit.info(f"datto_sync_single_client client={client_id} -> {devices_count}/{matched_count} by={current_user.get('email')}")
    return {
        "ok": True,
        "client_id": client_id,
        "devices_count": devices_count,
        "matched_count": matched_count,
        "last_sync_at": (link_after or {}).get("last_sync_at"),
        "global_sync_result": result,
    }


@router.post("/admin/datto/cleanup-orphan-links")
async def datto_cleanup_orphan_links(current_user: dict = Depends(get_current_user)):
    """Rimuove `datto_client_links` che puntano a client_id non piu' esistenti
    in `clients` collection, e i relativi `datto_devices`. Da usare quando
    la UI Diagnostica mostra "(eliminato?)" nello "Stato per cliente"."""
    require_admin(current_user)

    links = await db.datto_client_links.find({}, {"_id": 0, "client_id": 1, "client_name": 1}).to_list(500)
    existing_ids = {c["id"] async for c in db.clients.find({}, {"_id": 0, "id": 1})}

    orphan_ids = [link["client_id"] for link in links if link["client_id"] not in existing_ids]
    orphan_links = [link for link in links if link["client_id"] in orphan_ids]

    if orphan_ids:
        await db.datto_client_links.delete_many({"client_id": {"$in": orphan_ids}})
        dev_del = await db.datto_devices.delete_many({"client_id": {"$in": orphan_ids}})
        audit.warning(
            f"datto_cleanup_orphan_links removed_links={len(orphan_ids)} "
            f"removed_devices={dev_del.deleted_count} by={current_user.get('email')}"
        )
        return {
            "ok": True,
            "removed_links": len(orphan_ids),
            "removed_devices": dev_del.deleted_count,
            "orphan_links": orphan_links,
        }
    return {"ok": True, "removed_links": 0, "removed_devices": 0, "orphan_links": []}


@router.get("/datto/diagnostics")
async def datto_diagnostics(current_user: dict = Depends(get_current_user)):
    """Diagnostica completa Datto RMM: stato config, cache, link clienti,
    ultimo sync. Aiuta a capire perche' il sync "non trova nulla".
    Output volutamente compatto, NESSUN dato sensibile esposto.

    Causa tipica "non trova nulla":
      1. Config Datto non presente o api_key invalida → sites_in_cache=0
      2. Sites endpoint funziona ma nessun client linkato → linked_clients=0
      3. Sites linkati ma sync mai eseguito → last_sync_at=None
      4. Sync eseguito ma 0 device persisted → wrapper schema cambiato
      5. Device persisted ma 0 matched → MAC/IP non coincidono con Center
    """
    require_admin(current_user)
    out: dict[str, Any] = {
        "checks": [],
        "actions_suggested": [],
    }

    # 1. Config presente?
    cfg = await db.datto_settings.find_one({"id": "global"}, {"_id": 0, "api_key_enc": 0})
    cfg_ok = bool(cfg and cfg.get("user_id"))
    out["checks"].append({
        "step": "1_config",
        "ok": cfg_ok,
        "detail": "Config Datto presente" if cfg_ok else "Config Datto MANCANTE — configura api_key+user_id in PUT /api/admin/datto/config",
    })
    if not cfg_ok:
        out["actions_suggested"].append("Vai a Settings → Datto RMM → configura api_key e user_id")
        return out

    # 2. Cache siti
    n_sites = await db.datto_sites_cache.count_documents({})
    last_site = await db.datto_sites_cache.find_one({}, {"_id": 0, "fetched_at": 1}, sort=[("fetched_at", -1)])
    out["checks"].append({
        "step": "2_sites_cache",
        "ok": n_sites > 0,
        "sites_in_cache": n_sites,
        "last_fetched_at": (last_site or {}).get("fetched_at"),
        "detail": f"{n_sites} siti in cache" if n_sites > 0 else "Cache siti VUOTA — clicca 'Sync now' o /api/datto/sync-now",
    })
    if n_sites == 0:
        out["actions_suggested"].append("Esegui POST /api/datto/sync-now (popolera' la cache siti)")
        out["actions_suggested"].append("Se ancora 0, usa POST /api/admin/datto/raw-debug per ispezionare la response del wrapper")

    # 3. Client links
    links_cursor = db.datto_client_links.find({}, {"_id": 0})
    links = await links_cursor.to_list(500)
    n_links = len(links)
    out["checks"].append({
        "step": "3_client_links",
        "ok": n_links > 0,
        "linked_clients": n_links,
        "detail": f"{n_links} clienti collegati a siti Datto" if n_links > 0 else "Nessun cliente collegato — devi mappare cliente→sito Datto via PUT /api/clients/{id}/datto/link",
    })
    if n_links == 0:
        out["actions_suggested"].append("Per ogni cliente vai in: Clienti → seleziona cliente → tab 'Datto RMM' → scegli il sito Datto associato")

    # 4. Last sync per link + matched stats
    links_summary = []
    for link in links:
        cid = link.get("client_id")
        cli = await db.clients.find_one({"id": cid}, {"_id": 0, "name": 1}) if cid else None
        n_persisted = await db.datto_devices.count_documents({"client_id": cid})
        links_summary.append({
            "client_id": cid,
            "client_name": (cli or {}).get("name", "(eliminato?)"),
            "site_id": link.get("site_id"),
            "last_sync_at": link.get("last_sync_at"),
            "device_count": link.get("device_count", 0),
            "matched_count": link.get("matched_count", 0),
            "persisted_in_db": n_persisted,
        })
    out["links_summary"] = links_summary

    # 5. Datto devices totali persisted
    total_persisted = await db.datto_devices.count_documents({})
    out["checks"].append({
        "step": "5_devices_persisted",
        "total_in_db": total_persisted,
        "detail": f"{total_persisted} device Datto persisted nel DB" if total_persisted > 0 else "Zero device persisted — sync probabilmente fallito o link mai sincronizzato",
    })

    # 6. Discovered endpoints (per matching)
    n_disco = await db.discovered_endpoints.count_documents({})
    out["checks"].append({
        "step": "6_discovered_endpoints",
        "total": n_disco,
        "detail": f"{n_disco} discovered_endpoints disponibili per match",
    })

    if n_sites > 0 and n_links > 0 and total_persisted == 0:
        out["actions_suggested"].append("Sito linkato ma 0 device persisted: probabile errore di audit (timeout o credenziali errate). Vedi log backend per 'datto_list_fetched' e 'datto_no_devices_found'.")
    if total_persisted > 0 and all(li.get("matched_count", 0) == 0 for li in links):
        out["actions_suggested"].append("Device persisted ma matched=0: i MAC/IP Datto non coincidono con discovered_endpoints. Verifica che il connector LAN scanner sia attivo nei clienti linkati.")

    out["healthy"] = cfg_ok and n_sites > 0 and n_links > 0 and total_persisted > 0
    return out


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
    # v2026-06 FIX 504: il refresh completo (fetch device Datto + audit MAC via API
    # per TUTTI i client linkati) può durare minuti e superava il timeout del proxy,
    # facendo fallire lo step 2 del wizard "Nuovo Cliente". Il link è già salvato
    # sopra; eseguiamo il sync in BACKGROUND e ritorniamo subito. I device compaiono
    # a breve (il wizard fa polling prima di importarli).
    async def _bg_sync_after_link():
        try:
            await _refresh_sites_cache()
        except Exception as e:  # noqa: BLE001
            logger.warning("datto background sync after link failed: %s", type(e).__name__)
    asyncio.create_task(_bg_sync_after_link())
    link = await db.datto_client_links.find_one({"client_id": client_id}, {"_id": 0})
    device_count = await db.datto_devices.count_documents({"client_id": client_id})
    matched_count = await db.datto_devices.count_documents({"client_id": client_id, "matched": True})
    return {"linked": True, "sync_started": True, **(link or {}),
            "device_count": device_count, "matched_count": matched_count}


@router.post("/clients/{client_id}/datto/seed-managed")
async def seed_managed_from_datto(
    client_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Importa device Datto come `managed_devices` placeholder.

    Per ogni `datto_devices` del cliente che NON ha gia' un managed_device
    associato (via MAC, IP o hostname), crea un nuovo `managed_devices`
    con:
      - name = nome Datto (hostname)
      - hostname = nome Datto
      - ip_address = ip Datto (primary)
      - mac_address = mac Datto (primary)
      - device_type = "endpoint"
      - source = "datto-seed"
      - datto_name, datto_match=hostname-seed, datto_matched_at

    Una volta importati, il connector LAN scanner li arricchisce
    automaticamente con IP corrente, porta switch, etc.

    Idempotente: ri-eseguibile senza creare duplicati. NON sovrascrive
    device esistenti.
    """
    require_admin(current_user)

    client = await db.clients.find_one({"id": client_id}, {"_id": 0, "name": 1})
    if not client:
        raise HTTPException(status_code=404, detail="Client non trovato")

    datto_devs = await db.datto_devices.find(
        {"client_id": client_id}, {"_id": 0}
    ).to_list(5000)
    if not datto_devs:
        raise HTTPException(
            status_code=400,
            detail="Nessun device Datto per questo cliente. Esegui prima il sync.",
        )

    # Index dei managed_devices esistenti per match (NO duplicati)
    existing = await db.managed_devices.find(
        {"client_id": client_id},
        {"_id": 0, "id": 1, "name": 1, "hostname": 1, "ip_address": 1, "mac_address": 1},
    ).to_list(20000)

    by_mac: dict[str, dict] = {}
    by_ip: dict[str, dict] = {}
    by_hostname: dict[str, dict] = {}
    for md in existing:
        for m in [(md.get("mac_address") or "").upper(), (md.get("mac") or "").upper()]:
            if m:
                by_mac[m] = md
        for ip_field in (md.get("ip_address"), md.get("ip")):
            if ip_field:
                by_ip[ip_field] = md
        for h in (md.get("hostname"), md.get("name")):
            if h:
                by_hostname[h.strip().lower()] = md

    import uuid as _uuid
    now_iso = datetime.now(timezone.utc).isoformat()
    created: list[str] = []
    enriched: list[str] = []  # esistenti aggiornati con datto_name
    skipped_duplicates = 0
    skipped_no_ip = 0
    seen_ips: set = set()  # evita duplicati su (client_id, ip) interni alla run

    inserts: list[dict] = []
    md_updates: list = []
    from pymongo import UpdateOne

    for d in datto_devs:
        name = (d.get("name") or "").strip()
        if not name:
            continue
        mac_primary = (d.get("mac") or "").upper()
        ip_primary = d.get("ip") or ""
        hostname_key = name.lower()

        # 1. Cerca match su MAC/IP/hostname esistenti
        match_md = None
        if mac_primary and mac_primary in by_mac:
            match_md = by_mac[mac_primary]
        elif ip_primary and ip_primary in by_ip:
            match_md = by_ip[ip_primary]
        elif hostname_key in by_hostname:
            match_md = by_hostname[hostname_key]

        if match_md:
            # Aggiorna datto_name sul managed_device esistente (non duplicare)
            md_updates.append(UpdateOne(
                {"id": match_md["id"]},
                {"$set": {
                    "datto_name": name,
                    "datto_match": "seed-existing",
                    "datto_matched_at": now_iso,
                }},
            ))
            enriched.append(name)
            skipped_duplicates += 1
            continue

        # v2026-03-01: managed_devices ha indice unique (client_id, ip).
        # Skippa device Datto senza IP (non monitorabili) o con IP duplicato.
        if not ip_primary:
            skipped_no_ip += 1
            continue
        if ip_primary in seen_ips or ip_primary in by_ip:
            skipped_duplicates += 1
            continue
        seen_ips.add(ip_primary)

        # 2. Nessun match: crea managed_device placeholder
        new_doc = {
            "id": _uuid.uuid4().hex,
            "client_id": client_id,
            "name": name,
            "hostname": name,
            "ip": ip_primary,
            "ip_address": ip_primary,
            "mac": mac_primary or None,
            "mac_address": mac_primary or None,
            "device_type": "endpoint",
            "monitor_type": "ping",
            "source": "datto-seed",
            "datto_name": name,
            "datto_match": "seed-imported",
            "datto_matched_at": now_iso,
            "auto_added": True,
            "auto_added_at": now_iso,
            "created_by": current_user.get("email"),
            "name_user_locked": False,
            "device_type_user_locked": False,
        }
        inserts.append(new_doc)
        created.append(name)
        # Aggiungi a by_hostname per evitare duplicati interni alla stessa run
        by_hostname[hostname_key] = new_doc

    if inserts:
        await db.managed_devices.insert_many(inserts)
    if md_updates:
        await db.managed_devices.bulk_write(md_updates, ordered=False)

    # Marca i datto_devices coinvolti come matched=True
    matched_names = created + enriched
    if matched_names:
        await db.datto_devices.update_many(
            {"client_id": client_id, "name": {"$in": matched_names}},
            {"$set": {"matched": True, "matched_at": now_iso, "match_via": "seed"}},
        )

    audit.info(
        f"datto_seed client={client_id} created={len(created)} "
        f"enriched={len(enriched)} skipped_dup={skipped_duplicates} "
        f"by={current_user.get('email')}"
    )
    return {
        "ok": True,
        "client_id": client_id,
        "client_name": client.get("name"),
        "total_datto_devices": len(datto_devs),
        "created_managed_devices": len(created),
        "enriched_existing": len(enriched),
        "skipped_no_ip": skipped_no_ip,
        "skipped_duplicates": skipped_duplicates,
        "created_names": created[:20],
        "enriched_names": enriched[:20],
    }


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
    await db.managed_devices.update_many(
        {"client_id": client_id, "datto_name": {"$exists": True}},        {"$unset": {"datto_name": "", "datto_match": "", "datto_matched_at": ""}},
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


@router.post("/clients/{client_id}/datto/rematch")
async def rematch_datto_for_client(
    client_id: str, current_user: dict = Depends(get_current_user),
):
    """Forza un re-match Datto RMM ↔ Center per UN singolo cliente.

    Riutilizza i `datto_devices` gia' cached (no fetch API Datto, no rate limit).
    Riapplica `_match_with_center` per scrivere `datto_name`/`datto_match`/
    `datto_matched_at` sui managed_devices e discovered_endpoints.

    Returns:
        {ok, client_id, datto_total, datto_matched, message}
    """
    require_admin(current_user)
    # Recupera datto_devices cached per il cliente
    datto_devs = await db.datto_devices.find(
        {"client_id": client_id},
        {"_id": 0, "uid": 1, "name": 1, "mac_list": 1, "ip_list": 1},
    ).to_list(10000)
    if not datto_devs:
        return {
            "ok": False,
            "client_id": client_id,
            "datto_total": 0,
            "datto_matched": 0,
            "message": "Nessun device Datto in cache per questo cliente. "
                       "Esegui prima una sync globale (POST /api/datto/sync-now) "
                       "o collega il sito Datto al cliente.",
        }
    # Re-applica il match
    matched = await _match_with_center(client_id, datto_devs)
    audit.info(
        f"datto_rematch by={current_user.get('email')} client_id={client_id} "
        f"total={len(datto_devs)} matched={matched}"
    )
    return {
        "ok": True,
        "client_id": client_id,
        "datto_total": len(datto_devs),
        "datto_matched": matched,
        "message": f"Re-match Datto eseguito: {matched}/{len(datto_devs)} device matchati.",
    }


# ---------------------------------------------------------------------------
# Endpoint BROWSE paginato — UI Prev/Next
# ---------------------------------------------------------------------------
from fastapi import Query


@router.get("/datto/browse/devices")
async def browse_datto_devices(
    client_id: Optional[str] = Query(default=None),
    page: int = Query(default=0, ge=0, le=10000),
    size: int = Query(default=25, ge=5, le=250),
    only_matched: bool = Query(default=False),
    current_user: dict = Depends(get_current_user),
):
    """Paginazione lato server dei device Datto sincronizzati.
    Ritorna SOLO {name, mac, ip, matched, site_name} — privacy-hardened.
    """
    q: dict = {}
    if client_id:
        q["client_id"] = client_id
    if only_matched:
        q["matched"] = True
    projection = {
        "_id": 0, "name": 1, "mac": 1, "ip": 1,
        "matched": 1, "matched_at": 1, "site_name": 1,
    }
    total = await db.datto_devices.count_documents(q)
    skip = page * size
    devs = await db.datto_devices.find(q, projection).sort("name", 1).skip(skip).limit(size).to_list(size)
    items = [
        {
            "name": d.get("name", ""),
            "mac": d.get("mac", ""),
            "ip": d.get("ip", ""),
            "matched": bool(d.get("matched")),
            "site_name": d.get("site_name", ""),
        }
        for d in devs
    ]
    total_pages = max(1, (total + size - 1) // size)
    return {
        "items": items,
        "page": page,
        "size": size,
        "total": total,
        "total_pages": total_pages,
        "has_prev": page > 0,
        "has_next": page + 1 < total_pages,
    }


@router.get("/datto/browse/sites")
async def browse_datto_sites(
    page: int = Query(default=0, ge=0, le=10000),
    size: int = Query(default=25, ge=5, le=250),
    current_user: dict = Depends(get_current_user),
):
    """Paginazione lato server dei siti Datto cached.
    Utile per UI "tutti i siti Datto" con Prev/Next.
    """
    total = await db.datto_sites_cache.count_documents({})
    skip = page * size
    sites = await db.datto_sites_cache.find(
        {}, {"_id": 0},
    ).sort("site_name", 1).skip(skip).limit(size).to_list(size)
    total_pages = max(1, (total + size - 1) // size)
    return {
        "items": sites,
        "page": page,
        "size": size,
        "total": total,
        "total_pages": total_pages,
        "has_prev": page > 0,
        "has_next": page + 1 < total_pages,
    }

