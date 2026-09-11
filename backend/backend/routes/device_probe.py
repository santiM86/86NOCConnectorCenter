"""
Web Console Path Probe — Diagnostic endpoint.

Scansiona una lista di path web comuni (login, frame, webui, ecc.) via connector
e restituisce una matrice indicando quali rispondono con body valido.
Utile per device come HP 5130 Comware o simili dove il path di login non è ovvio.

POST /api/diag/web-console-probe
  body: { device_ip, port?, scheme?, extra_paths?: [str], auth?: { user, pass } }
  -> { results: [{path, status_code, body_size, title, content_type, ok}], best_path }
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional, List
import asyncio
import base64
import re
import logging

from database import db
from deps import get_current_user
from routes.web_console_live import _proxy_via_connector

router = APIRouter(prefix="/api/diag", tags=["diag"])
logger = logging.getLogger(__name__)

DEFAULT_PATHS = [
    "/",
    "/login.html",
    "/login",
    "/frame/login.html",        # Fortinet / alcuni H3C
    "/web/frame.html",           # HPE Comware 5130/5500 moderne
    "/webui/",                   # UniFi, MikroTik webfig
    "/webnm/index.html",         # HPE IMC / Comware legacy
    "/index.html",
    "/admin/",
    "/home.asp",                 # TP-Link / D-Link
    "/web/login.html",           # Aruba OS-CX
    "/ui/",                      # Fortinet alt
]


@router.post("/web-console-probe")
async def web_console_probe(body: dict, current_user: dict = Depends(get_current_user)):
    """Per ogni path candidato esegue una GET via connector e riporta esito.

    Autz: admin, security_admin, superadmin, operator.
    """
    if current_user.get("role") not in ("admin", "security_admin", "superadmin", "operator"):
        raise HTTPException(status_code=403, detail="Ruolo admin/operator richiesto")

    device_ip = (body or {}).get("device_ip", "").strip()
    if not device_ip:
        raise HTTPException(status_code=400, detail="device_ip required")

    # Port / scheme: usa override utente, poi profilo, poi default 443/https
    md = await db.managed_devices.find_one({"ip": device_ip}, {"_id": 0, "client_id": 1, "web_console_port": 1, "web_console_scheme": 1})
    ps = await db.device_poll_status.find_one({"device_ip": device_ip}, {"_id": 0, "client_id": 1, "web_console_port": 1, "web_console_scheme": 1})
    if not md and not ps:
        raise HTTPException(status_code=404, detail="Device non trovato tra managed_devices")

    client_id = (md or ps or {}).get("client_id")
    port = int(body.get("port") or (md or {}).get("web_console_port") or (ps or {}).get("web_console_port") or 443)
    scheme = (body.get("scheme") or (md or {}).get("web_console_scheme") or (ps or {}).get("web_console_scheme") or ("https" if port in (443, 5001, 8443, 4443) else "http"))

    extra_paths = body.get("extra_paths") or []
    if not isinstance(extra_paths, list):
        extra_paths = []
    paths = list(dict.fromkeys(DEFAULT_PATHS + [str(p) for p in extra_paths if str(p).startswith("/")]))

    # Opzionale: Basic Auth (per switch Comware con HTTP auth)
    auth = body.get("auth") or {}
    req_headers = {}
    if auth.get("user"):
        creds = f"{auth.get('user')}:{auth.get('pass','')}"
        req_headers["Authorization"] = "Basic " + base64.b64encode(creds.encode("utf-8")).decode("ascii")

    # Session dedicato per non sporcare cookie jar live
    import uuid
    session_id = f"probe-{uuid.uuid4().hex[:12]}"

    async def _probe(path: str):
        try:
            status_code, ct, body_bytes, resp_headers = await asyncio.wait_for(
                _proxy_via_connector(
                    client_id, device_ip, port, scheme, path, "GET",
                    session_id, b"", req_headers,
                ),
                timeout=8.0,
            )
            title = ""
            try:
                preview = body_bytes[:8192].decode("utf-8", errors="replace")
                m = re.search(r"<title[^>]*>(.*?)</title>", preview, re.IGNORECASE | re.DOTALL)
                if m:
                    title = re.sub(r"\s+", " ", m.group(1)).strip()[:120]
            except Exception:
                pass
            # Has WWW-Authenticate?
            www_auth = None
            for k, v in (resp_headers or {}).items():
                if k.lower() == "www-authenticate":
                    www_auth = v
                    break
            return {
                "path": path,
                "status_code": status_code,
                "content_type": (ct or "").split(";")[0].strip() or None,
                "body_size": len(body_bytes),
                "title": title or None,
                "www_authenticate": www_auth,
                "ok": (200 <= status_code < 400) and len(body_bytes) >= 200,
            }
        except asyncio.TimeoutError:
            return {"path": path, "status_code": 0, "body_size": 0, "title": None, "ok": False, "error": "connector_timeout"}
        except HTTPException as he:
            return {"path": path, "status_code": he.status_code, "body_size": 0, "title": None, "ok": False, "error": he.detail}
        except Exception as e:
            return {"path": path, "status_code": 0, "body_size": 0, "title": None, "ok": False, "error": str(e)[:180]}

    # Parallela, ma massimo 8 concorrenti per ridurre wall-clock
    sem = asyncio.Semaphore(8)

    async def _run(p):
        async with sem:
            return await _probe(p)

    results = await asyncio.gather(*[_run(p) for p in paths])

    # Best path: max body_size tra ok + titolo popolato, altrimenti primo ok
    ok_results = [r for r in results if r.get("ok")]
    ok_with_title = [r for r in ok_results if r.get("title")]
    best = None
    if ok_with_title:
        best = sorted(ok_with_title, key=lambda r: -r["body_size"])[0]
    elif ok_results:
        best = sorted(ok_results, key=lambda r: -r["body_size"])[0]

    return {
        "device_ip": device_ip,
        "port": port,
        "scheme": scheme,
        "total_paths": len(paths),
        "ok_count": len(ok_results),
        "results": sorted(results, key=lambda r: (-r.get("body_size", 0), r["path"])),
        "best_path": best["path"] if best else None,
        "best_title": best.get("title") if best else None,
    }


@router.post("/apply-web-console-path")
async def apply_web_console_path(body: dict, current_user: dict = Depends(get_current_user)):
    """Salva il path scelto dalla probe nel device managed."""
    if current_user.get("role") not in ("admin", "security_admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Ruolo admin richiesto")
    device_ip = (body or {}).get("device_ip", "").strip()
    path = (body or {}).get("path", "").strip()
    if not device_ip or not path or not path.startswith("/"):
        raise HTTPException(status_code=400, detail="device_ip e path (che inizia con /) sono richiesti")

    res = await db.managed_devices.update_one(
        {"ip": device_ip},
        {"$set": {"web_console_path": path}}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Device non trovato")
    return {"ok": True, "device_ip": device_ip, "web_console_path": path}
