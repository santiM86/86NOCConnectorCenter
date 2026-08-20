"""
Downdetector Enterprise API (Ookla) v2 — client OAuth2.

Fonte crowdsourced ufficiale per la correlazione outage: segnalazioni utenti in
tempo reale su operatori/servizi. A PAGAMENTO (Enterprise). Credenziali
client_id + client_secret salvate cifrate in db.settings (fallback env).

Auth: POST {base}/tokens?grant_type=client_credentials con HTTP Basic
(client_id:client_secret) → JWT (expires_in ~3600). Poi Bearer sulle chiamate.
Status company: success (ok) | warning (possibili problemi) | danger (problemi).
"""
import os
import time
import asyncio
import logging
from typing import Optional

logger = logging.getLogger("downdetector")

DD_BASE = os.environ.get("DD_BASE_URL", "https://downdetectorapi.com/v2").rstrip("/")

# keyword operatore → slug Downdetector
_SLUGS = {
    "telecom italia": "tim", "tim": "tim", "ibsnaz": "tim",
    "vodafone": "vodafone", "fastweb": "fastweb",
    "wind": "windtre", "windtre": "windtre",
    "iliad": "iliad", "sky": "sky", "open fiber": "open-fiber",
    "openfiber": "open-fiber", "tiscali": "tiscali", "eolo": "eolo",
    "linkem": "linkem", "aruba": "aruba",
}

_token_cache = {"token": None, "exp": 0.0}
_token_lock = asyncio.Lock()


async def get_creds() -> tuple:
    """(client_id, client_secret) da DB cifrato, fallback env."""
    try:
        from database import db
        from security import security_manager
        cid = await db.settings.find_one({"key": "downdetector_client_id"}, {"_id": 0, "value": 1})
        csec = await db.settings.find_one({"key": "downdetector_client_secret"}, {"_id": 0, "value": 1})
        if cid and cid.get("value") and csec and csec.get("value"):
            return (security_manager.decrypt_credential(cid["value"]),
                    security_manager.decrypt_credential(csec["value"]))
    except Exception as e:  # noqa: BLE001
        logger.debug("dd creds DB lookup failed: %s", e)
    return (os.environ.get("DD_CLIENT_ID"), os.environ.get("DD_CLIENT_SECRET"))


async def is_configured() -> bool:
    cid, csec = await get_creds()
    return bool(cid and csec)


async def status_info() -> dict:
    """Stato configurazione (senza esporre le credenziali)."""
    from_db = False
    try:
        from database import db
        d = await db.settings.find_one({"key": "downdetector_client_id"}, {"_id": 0, "value": 1})
        from_db = bool(d and d.get("value"))
    except Exception:
        from_db = False
    cid, csec = await get_creds()
    configured = bool(cid and csec)
    masked = ("…" + cid[-4:]) if cid and len(cid) >= 4 else None
    return {"configured": configured, "source": ("db" if from_db else ("env" if configured else None)),
            "masked_client_id": masked}


async def _get_token(client, cid: str, csec: str) -> Optional[str]:
    if _token_cache["token"] and time.time() < _token_cache["exp"] - 300:
        return _token_cache["token"]
    async with _token_lock:
        if _token_cache["token"] and time.time() < _token_cache["exp"] - 300:
            return _token_cache["token"]
        r = await client.post(f"{DD_BASE}/tokens", params={"grant_type": "client_credentials"},
                              auth=(cid, csec), headers={"Accept": "application/json"})
        r.raise_for_status()
        body = r.json()
        tok = body.get("access_token")
        if not tok:
            return None
        _token_cache["token"] = tok
        _token_cache["exp"] = time.time() + int(body.get("expires_in", 3600))
        return tok


async def _dd_get(client, token: str, path: str, **params) -> object:
    r = await client.get(f"{DD_BASE}/{path.lstrip('/')}",
                         params={k: v for k, v in params.items() if v is not None},
                         headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    if r.status_code == 401:
        _token_cache["token"] = None; _token_cache["exp"] = 0
    r.raise_for_status()
    return r.json()


def _slug_for(isp_name: Optional[str]) -> Optional[str]:
    n = (isp_name or "").lower()
    return next((s for kw, s in _SLUGS.items() if kw in n), None)


async def check_downdetector(isp_name: Optional[str], country_iso: str = "IT") -> dict:
    """Ritorna lo stato Downdetector per l'operatore.
    {configured, ok, status(success|warning|danger|unknown), problem(bool),
     company, total_reports, url, error}"""
    cid, csec = await get_creds()
    if not (cid and csec):
        return {"configured": False, "ok": None, "status": None, "problem": False}
    import httpx
    out = {"configured": True, "ok": None, "status": "unknown", "problem": False,
           "company": None, "total_reports": None, "url": None, "error": None}
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            token = await _get_token(client, cid, csec)
            if not token:
                out["error"] = "token non ottenuto"; out["ok"] = False; return out
            fields = "id,name,slug,country_iso,country_id,site_id,status,baseline_current,stats_24"
            # 1) prova per slug noto, 2) fallback ricerca per nome
            company = None
            slug = _slug_for(isp_name)
            if slug:
                try:
                    res = await _dd_get(client, token, f"slugs/{slug}/companies", fields=fields)
                    cands = res if isinstance(res, list) else (res.get("data") or res.get("companies") or [])
                    company = next((c for c in cands if (c.get("country_iso") or "").upper() == country_iso.upper()), None) or (cands[0] if cands else None)
                except Exception:
                    company = None
            if not company and isp_name:
                res = await _dd_get(client, token, "companies/search", name=isp_name, fields=fields)
                cands = res if isinstance(res, list) else (res.get("data") or res.get("companies") or [])
                company = next((c for c in cands if (c.get("country_iso") or "").upper() == country_iso.upper()), None) or (cands[0] if cands else None)
            if not company:
                out["ok"] = True; out["error"] = "operatore non trovato su Downdetector"; return out
            st = (company.get("status") or "unknown").lower()
            out.update({
                "ok": True, "status": st, "problem": st in ("warning", "danger"),
                "company": company.get("name"),
                "total_reports": (company.get("stats_24") or {}).get("sum") if isinstance(company.get("stats_24"), dict) else company.get("baseline_current"),
                "url": f"https://downdetector.it/stato/{company.get('slug')}/" if company.get("slug") else None,
            })
            return out
    except Exception as e:  # noqa: BLE001
        logger.debug("check_downdetector failed: %s", e)
        out["ok"] = False; out["error"] = str(e)
        return out
