"""
Web Console LIVE catch-all proxy.
Arch: browser iframe src -> catch-all endpoint -> connector long-poll -> device

Il browser riceve HTML con <base> tag che punta a questo endpoint, quindi
tutti i path relativi (CSS/JS/img/XHR) vengono proxati naturalmente.
"""
from fastapi import APIRouter, Request, HTTPException, Response, Depends
import uuid
import asyncio
import base64
import logging
import re
from datetime import datetime, timezone, timedelta

from database import db
from deps import get_current_user

router = APIRouter(prefix="/api", tags=["web_console_live"])
logger = logging.getLogger(__name__)
audit = logging.getLogger("audit")

# Event bus condiviso col router web_proxy esistente
from routes.web_proxy import _get_response_event, _response_events  # noqa: E402

LONG_POLL_SEC = 30
VALID_METHODS = {"GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "PATCH"}
SESSION_TTL_HOURS = 8


async def _authz_device(current_user: dict, device_ip: str) -> str:
    """Verifica che l'utente possa accedere al device. Restituisce client_id."""
    md = await db.managed_devices.find_one({"ip": device_ip}, {"_id": 0, "client_id": 1})
    if md:
        client_id = md["client_id"]
    else:
        ps = await db.device_poll_status.find_one({"device_ip": device_ip}, {"_id": 0, "client_id": 1})
        if not ps:
            raise HTTPException(status_code=403, detail="Device not authorized")
        client_id = ps["client_id"]

    role = current_user.get("role", "viewer")
    if role == "viewer":
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if role not in ("admin", "superadmin", "operator"):
        allowed_clients = set(current_user.get("client_ids") or [])
        if client_id not in allowed_clients:
            raise HTTPException(status_code=403, detail="Access denied for this client")
    return client_id


@router.post("/web-console/session")
async def create_web_console_session(request: Request, current_user: dict = Depends(get_current_user)):
    """Crea una sessione web console bindata a (user, client, device, port).
    Il session_id e' il capability token: chi possiede quel UUID puo' accedere al proxy.
    """
    body = await request.json()
    device_ip = str(body.get("device_ip", "")).strip()
    port = int(body.get("port", 0) or 0)
    if not device_ip or not port:
        raise HTTPException(status_code=400, detail="device_ip and port required")

    client_id = await _authz_device(current_user, device_ip)
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    await db.web_console_tokens.insert_one({
        "session_id": session_id,
        "user_email": current_user.get("email", ""),
        "user_role": current_user.get("role", ""),
        "client_id": client_id,
        "device_ip": device_ip,
        "port": port,
        "created_at": now,
        "expires_at": now + timedelta(hours=SESSION_TTL_HOURS),
    })
    audit.info(f"[AUDIT] web_console_session_open | user={current_user.get('email')} | device={device_ip}:{port} | session={session_id}")
    return {
        "session_id": session_id,
        "iframe_url": f"/api/web-proxy/live/{session_id}/{device_ip}/{port}/",
        "expires_in_seconds": SESSION_TTL_HOURS * 3600,
    }


@router.delete("/web-console/session/{session_id}")
async def revoke_web_console_session(session_id: str, current_user: dict = Depends(get_current_user)):
    """Revoca esplicita della sessione web console (best-effort: il TTL index la purgerebbe comunque)."""
    res = await db.web_console_tokens.delete_one({
        "session_id": session_id,
        "user_email": current_user.get("email", ""),
    })
    audit.info(f"[AUDIT] web_console_session_close | user={current_user.get('email')} | session={session_id} | deleted={res.deleted_count}")
    return {"revoked": res.deleted_count > 0}


@router.get("/web-console/debug/{session_id}")
async def web_console_debug(session_id: str, current_user: dict = Depends(get_current_user)):
    """Diagnostica live: ritorna gli ultimi 20 response del connector per questa sessione,
    con content-type originale, status, size, primi 512 byte (esc). Utile per debug
    iframe bianco / icona file rotto / contenuto strano.
    """
    tok = await db.web_console_tokens.find_one(
        {"session_id": session_id},
        {"_id": 0, "user_email": 1, "device_ip": 1, "port": 1},
    )
    if not tok:
        raise HTTPException(status_code=404, detail="Session not found")
    # Authz: owner o admin/superadmin
    if tok.get("user_email") != current_user.get("email") and current_user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Not session owner")

    cursor = db.web_proxy_requests.find(
        {"session_id": session_id},
        {"_id": 0, "request_id": 1, "path": 1, "method": 1, "created_at": 1, "status": 1, "response": 1},
    ).sort("created_at", -1).limit(20)
    rows = []
    async for r in cursor:
        resp = r.get("response") or {}
        body_preview = ""
        body_b64 = resp.get("body_b64")
        if body_b64:
            try:
                raw = base64.b64decode(body_b64)
                body_preview = raw[:512].decode("utf-8", "replace")
            except Exception:
                body_preview = "<binary decode error>"
        elif resp.get("body"):
            body_preview = str(resp["body"])[:512]
        rh = resp.get("response_headers") or {}
        rows.append({
            "request_id": r.get("request_id", "")[:8],
            "method": r.get("method"),
            "path": r.get("path"),
            "status": r.get("status"),
            "http_status": resp.get("status_code"),
            "content_type": resp.get("content_type") or rh.get("Content-Type") or rh.get("content-type"),
            "content_encoding": rh.get("Content-Encoding") or rh.get("content-encoding"),
            "content_disposition": rh.get("Content-Disposition") or rh.get("content-disposition"),
            "x_frame_options": rh.get("X-Frame-Options") or rh.get("x-frame-options"),
            "body_size": len(base64.b64decode(body_b64)) if body_b64 else len(resp.get("body") or ""),
            "body_preview_first_512": body_preview,
            "created_at": r.get("created_at"),
        })
    return {"session": tok, "recent_requests": rows}


async def _validate_session_token(session_id: str, device_ip: str, port: int) -> dict:
    """Valida il session_id come capability token bindato al device_ip.
    Il port NON e' piu' vincolante: un device puo' fare redirect verso port diversa
    (es. iLO HP: 443 → 5001) e il token deve restare valido. L'authz e' a livello
    di (user, client, device) e la porta e' solo un parametro della request."""
    now = datetime.now(timezone.utc)
    tok = await db.web_console_tokens.find_one(
        {"session_id": session_id, "device_ip": device_ip},
        {"_id": 0},
    )
    if not tok:
        raise HTTPException(status_code=401, detail="Invalid or expired web console session")
    exp = tok.get("expires_at")
    if isinstance(exp, str):
        try:
            exp = datetime.fromisoformat(exp.replace("Z", "+00:00"))
        except Exception:
            exp = None
    if isinstance(exp, datetime) and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp is not None and exp < now:
        raise HTTPException(status_code=401, detail="Web console session expired")
    return tok


def _build_base_href(session_id: str, device_ip: str, port: int) -> str:
    return f"/api/web-proxy/live/{session_id}/{device_ip}/{port}/"


def _rewrite_absolute_urls(text: str, session_id: str, device_ip: str) -> str:
    """Riscrive URL assoluti verso il device (https://10.x.x.x:port/...) nel body
    trasformandoli in path LIVE proxati. Supporta anche port diverse (iLO 443→5001)."""
    # Pattern: http[s]://{device_ip}(:port)?/path
    ip_esc = re.escape(device_ip)
    pattern = re.compile(
        rf"\bhttps?://{ip_esc}(?::(\d+))?(/[^\s\"'<>)]*)?",
        re.IGNORECASE,
    )

    def _sub(m: re.Match) -> str:
        port_part = m.group(1)
        path_part = m.group(2) or "/"
        if not port_part:
            scheme_match = m.group(0).lower()
            port_part = "443" if scheme_match.startswith("https") else "80"
        return f"/api/web-proxy/live/{session_id}/{device_ip}/{port_part}{path_part}"

    return pattern.sub(_sub, text)


def _rewrite_root_paths(html: str, session_id: str, device_ip: str, port: int) -> str:
    """Riscrive path assoluti root (che iniziano con /) negli attributi href/src/action
    di HTML. Necessario perche' <base href> NON risolve path assoluti root — il browser
    li risolve contro l'origine corrente (argus.86bit.it) invece che contro il device.

    Trasforma:
        href="/css/app.css"  ->  href="/api/web-proxy/live/{sid}/{ip}/{port}/css/app.css"
        src='/img/logo.png'  ->  src='/api/web-proxy/live/{sid}/{ip}/{port}/img/logo.png'
        action="/login"      ->  action="/api/web-proxy/live/{sid}/{ip}/{port}/login"

    NON tocca: path gia' proxati, path relativi, URL assoluti http(s)://, //cdn, #, javascript:, mailto:, data:.
    """
    prefix = f"/api/web-proxy/live/{session_id}/{device_ip}/{port}"
    # attributi: href, src, action, data-src, data-href, formaction, poster, srcset (solo single url — srcset complesso skip)
    # Match: (attr=")(path)("/')  dove path inizia con / ma NON // NON /api/web-proxy/live
    attrs = r"(?:href|src|action|formaction|poster|data-src|data-href|xlink:href)"
    pattern = re.compile(
        rf"""(\s{attrs}\s*=\s*)(["'])(/(?!/|api/web-proxy/live/)[^"']*?)\2""",
        re.IGNORECASE,
    )

    def _sub(m: re.Match) -> str:
        return f"{m.group(1)}{m.group(2)}{prefix}{m.group(3)}{m.group(2)}"

    return pattern.sub(_sub, html)


def _inject_html_support(body: bytes, base_href: str, session_id: str, device_ip: str, port: int) -> bytes:
    """Sanifica HTML per architettura LIVE:
    - Rimuove il `__ARGUS_PROXY__` marker iniettato dal connector (srcDoc-era)
    - Rimuove il Click/Submit/Location interceptor del connector (sovrascrive window.location)
    - Riscrive URL assoluti verso il device (https://{ip}:{port}/...) → path LIVE proxato
    - Inserisce <base href=...> nel <head> per auto-proxy asset relativi
    - Aggiunge interceptor MINIMAL (solo title propagation)
    """
    try:
        html = body.decode("utf-8", "replace")
    except Exception:
        return body

    # 1. Strip marker srcDoc-only
    html = html.replace("__ARGUS_PROXY__", "")

    # 2. Strip connector interceptor (firma: 'argus-proxy-navigate')
    html = re.sub(
        r"<script\b[^>]*>(?:(?!</script>).)*?argus-proxy-navigate(?:(?!</script>).)*?</script>",
        "",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # 3. URL rewriting full: https://{device_ip}(:port)?/... → path LIVE proxato
    html = _rewrite_absolute_urls(html, session_id, device_ip)

    # 3b. Root-path rewriting: href="/css/..." → href="/api/web-proxy/live/.../css/..."
    # (necessario perche' <base> NON risolve path assoluti root nel browser)
    html = _rewrite_root_paths(html, session_id, device_ip, port)

    # 4. Rimuovi <base> originali del device (conflitto con il nostro)
    html = re.sub(r"<base\b[^>]*>", "", html, flags=re.IGNORECASE)
    base_tag = f'<base href="{base_href}">'

    # 5. Inject <base> nel <head>
    if re.search(r"<head[^>]*>", html, re.IGNORECASE):
        html = re.sub(r"(<head[^>]*>)", r"\1" + base_tag, html, count=1, flags=re.IGNORECASE)
    elif re.search(r"<html[^>]*>", html, re.IGNORECASE):
        html = re.sub(r"(<html[^>]*>)", r"\1<head>" + base_tag + "</head>", html, count=1, flags=re.IGNORECASE)
    else:
        html = base_tag + html

    # 6. Interceptor MINIMAL (solo title)
    interceptor = """
<script>
(function(){
  try {
    if (document.title) window.parent.postMessage({type:'argus-title', title: document.title}, '*');
    var ob = new MutationObserver(function(){
      window.parent.postMessage({type:'argus-title', title: document.title}, '*');
    });
    var t = document.querySelector('title');
    if (t) ob.observe(t, {childList:true, subtree:true, characterData:true});
  } catch(e){}
})();
</script>
"""
    if re.search(r"</body>", html, re.IGNORECASE):
        html = re.sub(r"</body>", interceptor + "</body>", html, count=1, flags=re.IGNORECASE)
    else:
        html = html + interceptor

    return html.encode("utf-8", "replace")


async def _proxy_via_connector(
    client_id: str,
    device_ip: str,
    port: int,
    scheme: str,
    path: str,
    method: str,
    session_id: str,
    body_bytes: bytes,
    req_headers: dict,
) -> tuple[int, str, bytes, dict]:
    """Crea request per connector, long-poll response, restituisce (status_code, content_type, body_bytes, resp_headers)."""
    jar_doc = await db.web_proxy_sessions.find_one(
        {"session_id": session_id, "client_id": client_id, "device_ip": device_ip},
        {"_id": 0, "cookies": 1},
    )
    session_cookies = (jar_doc or {}).get("cookies") or {}

    req_id = str(uuid.uuid4())
    req_body_encoding = "text"
    req_body_payload = ""
    if body_bytes:
        try:
            req_body_payload = body_bytes.decode("utf-8")
            req_body_encoding = "text"
        except UnicodeDecodeError:
            req_body_payload = base64.b64encode(body_bytes).decode("ascii")
            req_body_encoding = "base64"

    await db.web_proxy_requests.insert_one({
        "request_id": req_id,
        "session_id": session_id,
        "client_id": client_id,
        "device_ip": device_ip,
        "port": port,
        "scheme": scheme or "",
        "path": path,
        "method": method,
        "request_body": req_body_payload,
        "request_body_encoding": req_body_encoding,
        "request_headers": req_headers,
        "session_cookies": session_cookies,
        "status": "pending",
        "requested_by": "live_proxy",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "response": None,
    })
    # Trigger connector waiter
    from routes.web_proxy import _request_events
    ev_req = _request_events.get(client_id)
    if ev_req is not None:
        ev_req.set()

    # Long-poll response
    ev = _get_response_event(req_id)
    try:
        await asyncio.wait_for(ev.wait(), timeout=LONG_POLL_SEC)
    except asyncio.TimeoutError:
        pass

    doc = await db.web_proxy_requests.find_one({"request_id": req_id}, {"_id": 0})
    _response_events.pop(req_id, None)
    if not doc:
        raise HTTPException(status_code=504, detail="Request lost")

    if doc.get("status") != "completed":
        raise HTTPException(status_code=504, detail="Connector timeout")

    resp = doc.get("response") or {}
    status_code = int(resp.get("status_code") or 200)
    content_type = resp.get("content_type") or "application/octet-stream"
    resp_headers = resp.get("response_headers") or {}

    if resp.get("is_binary") and resp.get("body_b64"):
        body = base64.b64decode(resp["body_b64"])
    elif resp.get("body"):
        body = resp["body"].encode("utf-8", "replace")
    elif resp.get("body_b64"):
        body = base64.b64decode(resp["body_b64"])
    else:
        body = b""

    return status_code, content_type, body, resp_headers


@router.api_route(
    "/web-proxy/live/{session_id}/{device_ip}/{port}",
    methods=["GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "PATCH"],
)
@router.api_route(
    "/web-proxy/live/{session_id}/{device_ip}/{port}/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "PATCH"],
)
async def live_proxy(
    session_id: str,
    device_ip: str,
    port: int,
    request: Request,
    path: str = "",
):
    """Catch-all endpoint per Web Console LIVE. Auth via session_id (capability token)."""
    if request.method not in VALID_METHODS:
        raise HTTPException(status_code=405, detail="Method not allowed")

    # Valida session token (no Bearer auth, capability-based)
    tok = await _validate_session_token(session_id, device_ip, port)
    client_id = tok["client_id"]

    # Costruisci path completo
    full_path = "/" + path
    qs = request.url.query
    if qs:
        full_path = f"{full_path}?{qs}"

    scheme = "https" if port in (443, 8443, 4443) else "http"

    body_bytes = await request.body()
    dropped_headers = {
        "host", "connection", "content-length", "accept-encoding",
        "authorization", "cookie", "origin", "referer", "sec-fetch-site",
        "sec-fetch-mode", "sec-fetch-dest", "sec-fetch-user",
    }
    req_headers = {k: v for k, v in request.headers.items() if k.lower() not in dropped_headers}

    audit.info(
        f"[AUDIT] web_console_live | user={tok.get('user_email')} | "
        f"{request.method} {device_ip}:{port}{full_path} | session={session_id}"
    )

    status_code, content_type, body, resp_headers = await _proxy_via_connector(
        client_id, device_ip, port, scheme, full_path, request.method,
        session_id, body_bytes, req_headers,
    )

    # === CONTENT-TYPE SNIFFING (fix "icona file rotto") ===
    # Alcuni device (iLO vecchi, HP 5130, firewall legacy) rispondono con Content-Type
    # errato (application/octet-stream, application/x-binary, vuoto) anche se il body
    # e' HTML. Il browser vede MIME non renderizzabile -> iframe mostra placeholder
    # "file rotto". Sniffiamo i primi 512 byte per determinare il MIME reale.
    ct_lower = (content_type or "").lower()
    needs_sniff = (
        not content_type
        or "octet-stream" in ct_lower
        or "application/x-binary" in ct_lower
        or "application/unknown" in ct_lower
        or ct_lower.strip() == "application/force-download"
    )
    if needs_sniff and body:
        sniff = body[:512].lstrip()
        sniff_str = sniff[:200].decode("utf-8", "replace").lower()
        if sniff.startswith(b"<!doctype") or sniff.startswith(b"<html") or "<html" in sniff_str or "<!doctype html" in sniff_str:
            content_type = "text/html; charset=utf-8"
        elif sniff.startswith(b"{") or sniff.startswith(b"["):
            content_type = "application/json; charset=utf-8"
        elif sniff.startswith(b"<?xml") or sniff.startswith(b"<svg"):
            content_type = "application/xml; charset=utf-8" if sniff.startswith(b"<?xml") else "image/svg+xml"

    # Inject <base> tag + sanitize + URL rewrite solo se HTML
    ct_lower = (content_type or "").lower()
    if ct_lower and ("text/html" in ct_lower or "xhtml" in ct_lower):
        base_href = _build_base_href(session_id, device_ip, port)
        body = _inject_html_support(body, base_href, session_id, device_ip, port)
    elif ct_lower and ("javascript" in ct_lower or "text/css" in ct_lower or "application/json" in ct_lower):
        # Riscrivi anche dentro JS/CSS/JSON per catturare XHR endpoint assoluti
        try:
            text = body.decode("utf-8", "replace")
            rewritten = _rewrite_absolute_urls(text, session_id, device_ip)
            if rewritten != text:
                body = rewritten.encode("utf-8", "replace")
        except Exception:
            pass

    # === STRIP HEADER CHE FORZANO DOWNLOAD O BLOCCANO IFRAME ===
    # Content-Disposition: attachment -> browser scarica invece di renderizzare
    # X-Frame-Options / Content-Security-Policy frame-ancestors -> blocco iframe
    # Content-Encoding -> body gia' decompresso dal connector, non re-indicare gzip
    drop_resp_headers = {
        "content-disposition", "x-frame-options", "content-security-policy",
        "content-encoding", "transfer-encoding", "content-length",
        "strict-transport-security",
    }

    # Headers da propagare al browser (bianco-listati + debug)
    pass_headers = {}
    safe_to_pass = {"cache-control", "etag", "last-modified", "expires", "vary"}
    for k, v in (resp_headers or {}).items():
        kl = k.lower()
        if kl in drop_resp_headers:
            continue
        if kl == "location":
            # Rewrite Location header per redirect HTTP 3xx verso URL assoluti del device
            new_loc = _rewrite_absolute_urls(str(v), session_id, device_ip)
            pass_headers["Location"] = new_loc
            continue
        if kl in safe_to_pass:
            pass_headers[k] = v
    pass_headers["X-Argus-Proxy"] = "v3"
    pass_headers["X-Argus-Sniff"] = "1" if needs_sniff else "0"
    pass_headers["X-Argus-CT-Orig"] = (resp_headers or {}).get("Content-Type", (resp_headers or {}).get("content-type", ""))[:120]

    return Response(
        content=body,
        status_code=status_code,
        media_type=content_type,
        headers=pass_headers,
    )
