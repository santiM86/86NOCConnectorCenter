"""
Web Console V4 — Cloud proxy popup-window (NOT iframe).
Architettura: token JWT firmato + URL rewrite full-page + cookie jar server-side.

Flusso:
1. Frontend: POST /api/console-v4/request-session {device_ip} -> {url, token, expires_at}
2. Frontend: window.open(url, '_blank')  (browser apre nuova tab, NO iframe)
3. Browser GET /api/console-v4/s/{token}/ -> backend proxy HTTP/HTTPS al device
4. Backend riscrive URL assoluti in HTML/JS/CSS response per mantenerli within /s/{token}/
5. Cookie del device salvati in sessione server-side per token (evita cross-origin cookie hell)
6. Basic/Digest Auth passthrough: il browser vede il dialog nativo del device
7. Token scade -> 401 con pagina "Sessione scaduta"

Routing device:
- Se credential.external_url presente -> proxy HTTPS diretto (da cloud)
- Altrimenti -> via connector long-polling (riusa event bus web_proxy esistente)
"""
from fastapi import APIRouter, Request, HTTPException, Response, Depends
from fastapi.responses import HTMLResponse
from typing import Optional
from datetime import datetime, timezone, timedelta
import os
import jwt
import uuid
import logging
import re
import httpx

from database import db
from deps import get_current_user

router = APIRouter(prefix="/api/console-v4", tags=["web-console-v4"])
logger = logging.getLogger(__name__)
audit = logging.getLogger("audit")

SECRET_KEY = os.environ.get("JWT_SECRET", "argus-console-v4-fallback-secret")
ALGORITHM = "HS256"
SESSION_TTL_MINUTES = 60

# In-memory cookie jar per session token (semplice, non distribuito)
# In caso di multi-instance backend si puo' migrare su Redis o MongoDB TTL collection
_SESSION_COOKIES: dict[str, dict[str, str]] = {}


def _make_token(*, device_ip: str, client_id: Optional[str], user_email: str, base_url: str) -> tuple[str, datetime]:
    """Firma un token JWT per una sessione console."""
    exp = datetime.now(timezone.utc) + timedelta(minutes=SESSION_TTL_MINUTES)
    payload = {
        "sid": str(uuid.uuid4()),
        "dip": device_ip,
        "cid": client_id,
        "usr": user_email,
        "base": base_url,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return token, exp


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=410, detail="Sessione scaduta")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token invalido")


# ======================== REQUEST SESSION ========================

@router.post("/request-session")
async def request_session(body: dict, request: Request, current_user: dict = Depends(get_current_user)):
    """Crea un token firmato e ritorna URL popup per nuova tab."""
    device_ip = (body or {}).get("device_ip", "").strip()
    if not device_ip:
        raise HTTPException(status_code=400, detail="device_ip required")

    # Authz: device deve esistere in Vault o managed_devices
    cred = await db.device_credentials.find_one({"device_ip": device_ip}, {"_id": 0})
    md = await db.managed_devices.find_one({"ip": device_ip}, {"_id": 0})
    ps = await db.device_poll_status.find_one({"device_ip": device_ip}, {"_id": 0})

    client_id = None
    if cred: client_id = cred.get("client_id")
    if not client_id and md: client_id = md.get("client_id")
    if not client_id and ps: client_id = ps.get("client_id")

    if not cred and not md and not ps:
        raise HTTPException(status_code=404, detail="Device non registrato nel Vault o tra i managed devices")

    # Determine base URL with priority:
    # 1. cred.external_url (Vault explicit override) — ha sempre la priorità
    # 2. managed_devices.web_console_{port,scheme,path} (scritti dal profilo applicato)
    # 3. cred.port (Vault port) + scheme inferito
    # 4. Fallback: 443/https
    external_url = (cred or {}).get("external_url", "").strip() if cred else ""

    # Step 2: leggi valori dal profilo (via managed_devices/device_poll_status)
    # Priorita': managed_devices > device_poll_status
    md_port = (md or {}).get("web_console_port")
    md_scheme = (md or {}).get("web_console_scheme")
    md_path = (md or {}).get("web_console_path") or "/"
    ps_port = (ps or {}).get("web_console_port")
    ps_scheme = (ps or {}).get("web_console_scheme")

    profile_port = md_port or ps_port
    profile_scheme = md_scheme or ps_scheme

    if external_url:
        base_url = external_url.rstrip("/")
        transport = "direct"
    elif profile_port:
        # Profilo device vendor applicato → usa configurazione profilo
        scheme = profile_scheme or ("https" if profile_port in (443, 5001, 8443, 4443) else "http")
        base_url = f"{scheme}://{device_ip}:{profile_port}"
        if md_path and md_path != "/":
            base_url = base_url + md_path.rstrip("/")
        transport = "direct"
    else:
        # Fallback Vault / default
        port = (cred or {}).get("port") or 443 if cred else 443
        scheme = "https" if port == 443 else ("http" if port == 80 else "https")
        base_url = f"{scheme}://{device_ip}:{port}"
        transport = "connector"

    token, exp = _make_token(
        device_ip=device_ip,
        client_id=client_id,
        user_email=current_user.get("email"),
        base_url=base_url,
    )

    # Audit log
    audit.info(f"[AUDIT] web_console_session_created | user={current_user.get('email')} | device={device_ip} | transport={transport}")

    # Store session meta for later audit
    await db.console_sessions.insert_one({
        "id": str(uuid.uuid4()),
        "sid": jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])["sid"],
        "device_ip": device_ip,
        "client_id": client_id,
        "user_email": current_user.get("email"),
        "transport": transport,
        "base_url": base_url,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": exp.isoformat(),
    })

    # Return relative path — frontend will prefix with window.location.origin
    # This avoids Host-header issues when backend is behind an ingress/proxy
    # whose internal host differs from the public URL
    relative_path = f"/api/console-v4/s/{token}/"

    return {
        "url": relative_path,  # frontend concatenates window.location.origin
        "token": token,
        "expires_at": exp.isoformat(),
        "transport": transport,
        "base_url": base_url,
    }


# ======================== PROXY ========================

# Headers che NON devono essere inoltrati
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
    "content-encoding", "content-length",  # httpx gestisce da se'
}

# Headers di risposta device da strippare per non bloccare l'embedding
STRIP_RESPONSE_HEADERS = {
    "x-frame-options", "content-security-policy", "content-security-policy-report-only",
    "strict-transport-security",  # HSTS rompe se serviamo sotto dominio diverso
    "public-key-pins", "x-xss-protection",
}


def _rewrite_html(body: bytes, prefix: str, device_base_url: str) -> bytes:
    """Riscrive URL assoluti in HTML/JS/CSS per puntare al proxy."""
    try:
        text = body.decode("utf-8", errors="replace")
    except Exception:
        return body
    # 1) Inject <base> tag per forzare tutti i path relativi a passare dal proxy
    base_tag = f'<base href="{prefix}/">'
    # Inserisci dopo <head> se esiste
    head_match = re.search(r'<head[^>]*>', text, re.IGNORECASE)
    if head_match:
        text = text[:head_match.end()] + base_tag + text[head_match.end():]

    # 2) Riscrivi URL assoluti che puntano al device (es. https://ilo.example:17990/login)
    # Trasforma: https?://HOST(:PORT)?/path -> {prefix}/path
    esc_base = re.escape(device_base_url.rstrip("/"))
    text = re.sub(rf"({esc_base})(/|\"|'|\\s)", lambda m: prefix + m.group(2), text)

    # 3) Prefisso per path assoluti root-relative (/login -> {prefix}/login)
    # ATTENZIONE: non toccare /api/console-v4/... che sono già nostri
    # Manteniamo solo href/src/action/url("...") che iniziano con '/' e non con '//' o '/api/console-v4'
    def _fix_root_rel(match):
        attr = match.group(1)
        quote = match.group(2)
        path = match.group(3)
        if path.startswith("//") or path.startswith("/api/console-v4/"):
            return match.group(0)
        return f'{attr}={quote}{prefix}{path}{quote}'
    text = re.sub(r'\b(href|src|action|data-url)=(["\'])(/[^"\'\s>]+)\2', _fix_root_rel, text, flags=re.IGNORECASE)

    # 4) JS: window.location.href = "/..." -> "{prefix}/..."
    text = re.sub(r'(location\.(?:href|pathname)\s*=\s*["\'])(/)', rf'\1{prefix}/', text)

    return text.encode("utf-8", errors="replace")


@router.api_route("/s/{token}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@router.api_route("/s/{token}/", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@router.api_route("/s/{token}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def proxy(token: str, request: Request, path: str = ""):
    """Core proxy: riceve richiesta browser, inoltra al device, riscrive risposta."""
    try:
        payload = _decode_token(token)
    except HTTPException as e:
        if e.status_code == 410:
            return HTMLResponse(
                "<html><body style='font-family:system-ui;padding:40px;background:#0d1117;color:#fff'>"
                "<h2>Sessione scaduta</h2><p>Chiudi questa tab e apri una nuova sessione dal center.</p>"
                "</body></html>", status_code=410
            )
        raise

    device_ip = payload["dip"]
    base_url = payload["base"]
    sid = payload["sid"]
    prefix = f"/api/console-v4/s/{token}"

    # Build target URL
    target = f"{base_url}/{path}" if path else f"{base_url}/"
    if request.url.query:
        target += f"?{request.url.query}"

    # Prepare headers (strip hop-by-hop)
    fwd_headers = {}
    for k, v in request.headers.items():
        if k.lower() in HOP_BY_HOP or k.lower() in {"host", "origin", "referer"}:
            continue
        fwd_headers[k] = v
    # Fix Host header to device.
    # IMPORTANT: HTTP.sys / IIS (HPE iLO 5+/6+, Windows-based admin pages, alcuni
    # firmware Comware) e altri server enterprise rifiutano `Host` con porta
    # esplicita quando questa coincide con la default per lo scheme — errore
    # "HTTP Error 400. The request URL is invalid". Stripping della porta default
    # per uniformarsi al canonical Host RFC 7230 §5.4.
    from urllib.parse import urlparse as _urlparse
    parsed = _urlparse(base_url)
    _hostname = parsed.hostname or parsed.netloc.split(":")[0]
    _port = parsed.port
    _scheme = parsed.scheme
    if _port and not (
        (_scheme == "https" and _port == 443)
        or (_scheme == "http" and _port == 80)
    ):
        fwd_headers["Host"] = f"{_hostname}:{_port}"
    else:
        fwd_headers["Host"] = _hostname

    # Cookie jar: use stored cookies if any
    cookie_jar = _SESSION_COOKIES.get(sid, {})
    if cookie_jar:
        fwd_headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookie_jar.items())

    # Body
    body_bytes = await request.body() if request.method in ("POST", "PUT", "PATCH") else None

    # Execute with verify=False for self-signed (enterprise LAN + WAN with port-forward)
    try:
        async with httpx.AsyncClient(verify=False, timeout=30.0, follow_redirects=False) as client:
            r = await client.request(
                request.method, target,
                headers=fwd_headers, content=body_bytes,
                auth=None,  # Lasciamo passare Authorization header from browser nativamente
            )
    except httpx.ConnectError as ce:
        return HTMLResponse(
            f"<html><body style='font-family:system-ui;padding:40px;background:#0d1117;color:#fff'>"
            f"<h2>Device non raggiungibile</h2><p><code>{target}</code></p>"
            f"<p style='color:#888'>Errore: {ce}</p>"
            f"<p>Verifica che l'IP/URL sia corretto, la porta aperta, e il firewall permetta il traffico.</p>"
            f"</body></html>", status_code=502
        )
    except Exception as e:
        logger.error(f"console-v4 proxy error for {target}: {e}")
        return HTMLResponse(f"<html><body>Errore proxy: {e}</body></html>", status_code=502)

    # Update cookie jar from Set-Cookie headers
    for ck in r.headers.get_list("set-cookie") if hasattr(r.headers, "get_list") else []:
        m = re.match(r"^([^=]+)=([^;]*)", ck)
        if m:
            cookie_jar[m.group(1)] = m.group(2)
    _SESSION_COOKIES[sid] = cookie_jar

    # Build response headers (strip hop-by-hop + problematic)
    out_headers = {}
    for k, v in r.headers.items():
        kl = k.lower()
        if kl in HOP_BY_HOP or kl in STRIP_RESPONSE_HEADERS or kl == "set-cookie":
            continue
        out_headers[k] = v

    # Handle redirects: rewrite Location to go through proxy
    if 300 <= r.status_code < 400 and "location" in r.headers:
        loc = r.headers["location"]
        if loc.startswith("http://") or loc.startswith("https://"):
            # Absolute redirect — strip device base and prefix with proxy
            if loc.startswith(base_url):
                new_loc = prefix + loc[len(base_url):]
            else:
                new_loc = prefix + "/__external__?u=" + loc
        elif loc.startswith("/"):
            new_loc = prefix + loc
        else:
            new_loc = loc
        out_headers["location"] = new_loc
        return Response(content=b"", status_code=r.status_code, headers=out_headers)

    # Rewrite HTML/CSS/JS bodies
    ct = (r.headers.get("content-type") or "").lower()
    body_out = r.content
    if "text/html" in ct or "application/xhtml" in ct:
        body_out = _rewrite_html(body_out, prefix, base_url)
    elif "text/css" in ct:
        # Rewrite url(/path) and url(https://device/path) in CSS
        try:
            text = body_out.decode("utf-8", errors="replace")
            text = re.sub(r'url\((["\']?)(/)', rf'url(\1{prefix}/', text)
            text = re.sub(re.escape(base_url.rstrip("/")) + r'(/[^)"\'\s]+)', rf'{prefix}\1', text)
            body_out = text.encode("utf-8")
        except Exception:
            pass
    # Note: text/javascript rewriting is risky (false positives); limited to string literals would need AST parser

    return Response(content=body_out, status_code=r.status_code, headers=out_headers, media_type=r.headers.get("content-type"))


# ======================== ADMIN: LIST SESSIONS / REVOKE ========================

@router.get("/sessions")
async def list_sessions(current_user: dict = Depends(get_current_user)):
    """Admin: elenco sessioni console attive (audit)."""
    now_iso = datetime.now(timezone.utc).isoformat()
    cursor = db.console_sessions.find(
        {"expires_at": {"$gte": now_iso}},
        {"_id": 0}
    ).sort("created_at", -1).limit(100)
    items = [s async for s in cursor]
    return {"active": len(items), "items": items}


@router.post("/revoke/{sid}")
async def revoke_session(sid: str, current_user: dict = Depends(get_current_user)):
    """Admin: revoca forzata sessione (rimuove da cookie jar + marca expired)."""
    if current_user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin only")
    _SESSION_COOKIES.pop(sid, None)
    await db.console_sessions.update_one(
        {"sid": sid},
        {"$set": {"expires_at": datetime.now(timezone.utc).isoformat(), "revoked_by": current_user.get("email")}}
    )
    audit.info(f"[AUDIT] web_console_session_revoked | user={current_user.get('email')} | sid={sid}")
    return {"ok": True}
