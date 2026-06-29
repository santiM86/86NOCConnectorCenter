"""
86bit Portal — Datto RMM Sites Integration
==========================================
Integrazione con l'API del portal proprietario 86bit (`portal.86bit.it`) che
espone i siti Datto RMM in forma JSON normalizzata.

Endpoint upstream:
    GET https://portal.86bit.it/api/v1/reports/datto/getDattoSites
        ?api_key=<API_KEY>&userId=<USER_ID>&fetchLive=true

Risposta:
    {
      "success": true,
      "sites": {
        "pageDetails": {"count": 153, "totalCount": 153, ...},
        "sites": [
          {
            "id": 187117, "uid": "...", "accountUid": "pin4dcc0001",
            "name": "Managed", "description": "...",
            "onDemand": false, "splashtopAutoInstall": true,
            "devicesStatus": {
              "numberOfDevices": 25,
              "numberOfOnlineDevices": 17,
              "numberOfOfflineDevices": 8
            },
            "autotaskCompanyName": null, "autotaskCompanyId": null,
            "portalUrl": "https://pinotage.rmm.datto.com/site/187135"
          },
          ...
        ]
      }
    }

Storage:
- `portal86_datto_config` (singleton `_id="global"`):
    api_url, api_key_enc (AES-GCM), user_id_enc (AES-GCM), enabled,
    last_polled_at, last_poll_status, last_poll_error, last_sites_count
- Le credenziali sono SEMPRE cifrate via `security_manager.encrypt_credential`
  (vault AES-GCM con master key del backend).
- Decrypt fallisce con messaggio `vault_mismatch` invece di propagare
  `cryptography.exceptions.InvalidTag` (stessa policy degli altri poller).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from database import db
from deps import get_current_user, require_admin
from security import security_manager

logger = logging.getLogger("portal86_datto")
audit = logging.getLogger("audit")

router = APIRouter(prefix="/api", tags=["portal86-datto"])

GLOBAL_CONFIG_ID = "global"
DEFAULT_API_URL = "https://portal.86bit.it/api/v1/reports/datto/getDattoSites"
HTTP_TIMEOUT = 30.0


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class Portal86DattoConfigIn(BaseModel):
    api_url: str = Field(default=DEFAULT_API_URL)
    api_key: str = Field(..., min_length=8, description="API key del portal 86bit")
    user_id: str = Field(..., min_length=4, description="userId MongoDB ObjectId del portal")
    enabled: bool = Field(default=True)


class Portal86DattoConfigOut(BaseModel):
    api_url: str
    api_key_masked: str
    user_id_masked: str
    enabled: bool
    configured: bool = False
    last_polled_at: Optional[str] = None
    last_poll_status: Optional[str] = None
    last_poll_error: Optional[str] = None
    last_sites_count: Optional[int] = None


def _mask(s: str, keep: int = 4) -> str:
    if not s:
        return "(non configurato)"
    if len(s) <= keep:
        return "*" * len(s)
    return "*" * (len(s) - keep) + s[-keep:]


# ---------------------------------------------------------------------------
# Config endpoints
# ---------------------------------------------------------------------------
@router.get("/admin/portal86-datto/config", response_model=Portal86DattoConfigOut)
async def get_portal86_datto_config(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    cfg = await db.portal86_datto_config.find_one({"_id": GLOBAL_CONFIG_ID})
    if not cfg:
        return Portal86DattoConfigOut(
            api_url=DEFAULT_API_URL,
            api_key_masked="(non configurato)",
            user_id_masked="(non configurato)",
            enabled=True,
            configured=False,
        )

    # Decrypt safely (vault_mismatch tolerant)
    try:
        api_key = security_manager.decrypt_credential(cfg.get("api_key_enc", ""))
    except Exception:
        api_key = ""
    try:
        user_id = security_manager.decrypt_credential(cfg.get("user_id_enc", ""))
    except Exception:
        user_id = ""

    return Portal86DattoConfigOut(
        api_url=cfg.get("api_url") or DEFAULT_API_URL,
        api_key_masked=_mask(api_key, keep=4),
        user_id_masked=_mask(user_id, keep=6),
        enabled=cfg.get("enabled", True),
        configured=bool(cfg.get("api_key_enc") and cfg.get("user_id_enc")),
        last_polled_at=cfg.get("last_polled_at"),
        last_poll_status=cfg.get("last_poll_status"),
        last_poll_error=cfg.get("last_poll_error"),
        last_sites_count=cfg.get("last_sites_count"),
    )


@router.put("/admin/portal86-datto/config")
async def set_portal86_datto_config(
    payload: Portal86DattoConfigIn,
    current_user: dict = Depends(get_current_user),
):
    require_admin(current_user)
    enc_key = security_manager.encrypt_credential(payload.api_key.strip())
    enc_uid = security_manager.encrypt_credential(payload.user_id.strip())
    await db.portal86_datto_config.update_one(
        {"_id": GLOBAL_CONFIG_ID},
        {"$set": {
            "_id": GLOBAL_CONFIG_ID,
            "api_url": payload.api_url.strip() or DEFAULT_API_URL,
            "api_key_enc": enc_key,
            "user_id_enc": enc_uid,
            "enabled": payload.enabled,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": current_user.get("email"),
        }},
        upsert=True,
    )
    audit.warning(f"PORTAL86_DATTO_CONFIG_SET by={current_user.get('email')}")
    return {"saved": True}


@router.delete("/admin/portal86-datto/config")
async def delete_portal86_datto_config(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    await db.portal86_datto_config.delete_one({"_id": GLOBAL_CONFIG_ID})
    audit.warning(f"PORTAL86_DATTO_CONFIG_DELETED by={current_user.get('email')}")
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Live fetch
# ---------------------------------------------------------------------------
async def _fetch_sites(api_url: str, api_key: str, user_id: str) -> tuple[int, Any]:
    """Chiama portal.86bit.it; ritorna (http_status, json|str_error)."""
    params = {"api_key": api_key, "userId": user_id, "fetchLive": "true"}
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, verify=True) as client:
            r = await client.get(api_url, params=params)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, r.text
    except httpx.HTTPError as e:
        return 0, f"Connection error: {e}"


async def _load_decrypted_config() -> dict:
    """Carica + decrypt config, sollevando HTTPException su errori chiari."""
    cfg = await db.portal86_datto_config.find_one({"_id": GLOBAL_CONFIG_ID})
    if not cfg or not cfg.get("api_key_enc") or not cfg.get("user_id_enc"):
        raise HTTPException(status_code=400, detail="portal86-datto non configurato. PUT /api/admin/portal86-datto/config prima.")
    if not cfg.get("enabled", True):
        raise HTTPException(status_code=400, detail="portal86-datto disabilitato. Abilita in configurazione.")
    try:
        api_key = security_manager.decrypt_credential(cfg["api_key_enc"])
    except Exception as e:
        await db.portal86_datto_config.update_one(
            {"_id": GLOBAL_CONFIG_ID},
            {"$set": {
                "last_poll_status": "vault_mismatch",
                "last_poll_error": f"decrypt api_key: {e}. Re-save the config from the UI to re-encrypt.",
                "enabled": False,
            }},
        )
        raise HTTPException(status_code=500, detail="vault_mismatch: chiave AES-GCM ruotata. Re-salva la config dalla UI.")
    try:
        user_id = security_manager.decrypt_credential(cfg["user_id_enc"])
    except Exception as e:
        await db.portal86_datto_config.update_one(
            {"_id": GLOBAL_CONFIG_ID},
            {"$set": {
                "last_poll_status": "vault_mismatch",
                "last_poll_error": f"decrypt user_id: {e}. Re-save the config from the UI to re-encrypt.",
                "enabled": False,
            }},
        )
        raise HTTPException(status_code=500, detail="vault_mismatch: chiave AES-GCM ruotata. Re-salva la config dalla UI.")
    return {
        "api_url": cfg.get("api_url") or DEFAULT_API_URL,
        "api_key": api_key,
        "user_id": user_id,
    }


@router.post("/admin/portal86-datto/test-connection")
async def test_portal86_datto_connection(current_user: dict = Depends(get_current_user)):
    """Test live: chiama portal.86bit.it, salva stato e ritorna preview siti."""
    require_admin(current_user)
    decrypted = await _load_decrypted_config()
    now_iso = datetime.now(timezone.utc).isoformat()
    code, body = await _fetch_sites(decrypted["api_url"], decrypted["api_key"], decrypted["user_id"])
    if code != 200:
        err = body if isinstance(body, str) else str(body)[:400]
        await db.portal86_datto_config.update_one(
            {"_id": GLOBAL_CONFIG_ID},
            {"$set": {
                "last_polled_at": now_iso,
                "last_poll_status": f"http_{code}",
                "last_poll_error": err,
            }},
        )
        raise HTTPException(status_code=502, detail=f"upstream HTTP {code}: {err}")

    if not isinstance(body, dict) or not body.get("success"):
        err = str(body)[:400]
        await db.portal86_datto_config.update_one(
            {"_id": GLOBAL_CONFIG_ID},
            {"$set": {
                "last_polled_at": now_iso,
                "last_poll_status": "invalid_response",
                "last_poll_error": err,
            }},
        )
        raise HTTPException(status_code=502, detail=f"risposta upstream non valida: {err}")

    sites_obj = body.get("sites") or {}
    sites_list = sites_obj.get("sites") or []
    count = (sites_obj.get("pageDetails") or {}).get("count") or len(sites_list)

    await db.portal86_datto_config.update_one(
        {"_id": GLOBAL_CONFIG_ID},
        {"$set": {
            "last_polled_at": now_iso,
            "last_poll_status": "success",
            "last_poll_error": None,
            "last_sites_count": count,
        }},
    )

    # Anteprima: primi 5 siti con campi essenziali
    preview = []
    for s in sites_list[:5]:
        ds = s.get("devicesStatus") or {}
        preview.append({
            "id": s.get("id"),
            "uid": s.get("uid"),
            "name": s.get("name"),
            "accountUid": s.get("accountUid"),
            "devices_total": ds.get("numberOfDevices") or 0,
            "devices_online": ds.get("numberOfOnlineDevices") or 0,
            "devices_offline": ds.get("numberOfOfflineDevices") or 0,
            "portalUrl": s.get("portalUrl"),
        })
    return {"success": True, "count": count, "preview": preview}


@router.get("/portal86-datto/sites")
async def list_portal86_datto_sites(
    current_user: dict = Depends(get_current_user),
    limit: int = 0,
):
    """Fetch live dei siti Datto via portal.86bit.it.

    `limit=0` (default) ritorna tutti i siti; valori >0 troncano la lista
    a quella dimensione (utile per anteprime UI).
    """
    decrypted = await _load_decrypted_config()
    code, body = await _fetch_sites(decrypted["api_url"], decrypted["api_key"], decrypted["user_id"])
    if code != 200 or not isinstance(body, dict) or not body.get("success"):
        err = body if isinstance(body, str) else str(body)[:400]
        raise HTTPException(status_code=502, detail=f"upstream HTTP {code}: {err}")

    sites_obj = body.get("sites") or {}
    sites_list = sites_obj.get("sites") or []
    page = sites_obj.get("pageDetails") or {}

    if limit and limit > 0:
        sites_list = sites_list[:limit]

    # Compatta per ridurre payload UI (rimuove campi null/proxySettings)
    compact = []
    for s in sites_list:
        ds = s.get("devicesStatus") or {}
        compact.append({
            "id": s.get("id"),
            "uid": s.get("uid"),
            "accountUid": s.get("accountUid"),
            "name": s.get("name"),
            "description": s.get("description"),
            "onDemand": bool(s.get("onDemand")),
            "splashtopAutoInstall": bool(s.get("splashtopAutoInstall")),
            "devicesStatus": {
                "total": ds.get("numberOfDevices") or 0,
                "online": ds.get("numberOfOnlineDevices") or 0,
                "offline": ds.get("numberOfOfflineDevices") or 0,
            },
            "autotaskCompanyName": s.get("autotaskCompanyName"),
            "autotaskCompanyId": s.get("autotaskCompanyId"),
            "portalUrl": s.get("portalUrl"),
        })

    return {
        "success": True,
        "count": page.get("count") or len(compact),
        "totalCount": page.get("totalCount") or len(compact),
        "sites": compact,
    }
