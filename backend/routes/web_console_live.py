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


async def _validate_session_token(session_id: str, device_ip: str, port: int) -> dict:
    """Valida il session_id come capability token. Restituisce il token doc o 401."""
    now = datetime.now(timezone.utc)
    tok = await db.web_console_tokens.find_one(
        {"session_id": session_id, "device_ip": device_ip, "port": port},
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


def _inject_html_support(body: bytes, base_href: str) -> bytes:
    """Inserisce <base href=...> nel <head> + interceptor minimal."""
    try:
        html = body.decode("utf-8", "replace")
    except Exception:
        return body

    # Rimuovi <base> originali del device (conflitto con il nostro)
    html = re.sub(r"<base\b[^>]*>", "", html, flags=re.IGNORECASE)
    base_tag = f'<base href="{base_href}">'

    # Inject <base> come prima cosa dentro <head>
    if re.search(r"<head[^>]*>", html, re.IGNORECASE):
        html = re.sub(r"(<head[^>]*>)", r"\1" + base_tag, html, count=1, flags=re.IGNORECASE)
    elif re.search(r"<html[^>]*>", html, re.IGNORECASE):
        html = re.sub(r"(<html[^>]*>)", r"\1<head>" + base_tag + "</head>", html, count=1, flags=re.IGNORECASE)
    else:
        html = base_tag + html

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

    # Inject <base> tag solo se HTML
    if content_type and ("text/html" in content_type.lower() or "xhtml" in content_type.lower()):
        base_href = _build_base_href(session_id, device_ip, port)
        body = _inject_html_support(body, base_href)

    # Headers da propagare al browser (bianco-listati)
    pass_headers = {}
    safe_to_pass = {"cache-control", "etag", "last-modified", "expires", "vary"}
    for k, v in (resp_headers or {}).items():
        if k.lower() in safe_to_pass:
            pass_headers[k] = v
    pass_headers["X-Argus-Proxy"] = "v1"

    return Response(
        content=body,
        status_code=status_code,
        media_type=content_type,
        headers=pass_headers,
    )
