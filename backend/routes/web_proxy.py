"""
Web Console Proxy — Architettura Enterprise B
==============================================

Caratteristiche:
- Binary-safe transport (body in base64 opzionale)
- Supporto metodi HTTP completi (GET/POST/PUT/DELETE/HEAD/OPTIONS)
- Request body (form/JSON) inviato al device
- Cookie jar persistente per sessione device
- Asset proxy (CSS/JS/img) automatico via injected base tag
- Metrics (conteggi, latenza, errori)
- Audit log per ogni richiesta
- Streaming chunked per body > CHUNK_THRESHOLD
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
import uuid
import logging
import asyncio
import base64
from datetime import datetime, timezone, timedelta

from database import db
from deps import get_current_user, validate_api_key

router = APIRouter(prefix="/api", tags=["web_proxy"])
logger = logging.getLogger(__name__)
audit = logging.getLogger("audit")

# ================= Config =================
MAX_BODY_BYTES = 10 * 1024 * 1024       # 10 MB body hard limit
MAX_PATH_LEN = 4096
CLEANUP_MINUTES = 10                     # cleanup requests più vecchi di 10 min
LONG_POLL_MAX_SEC = 60  # v3.8.22: aumentato da 25 a 60 per ridurre traffico HTTP
VALID_METHODS = {"GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "PATCH"}

# ================= Event bus (in-memory, O(clienti) memory) =================
_request_events: dict[str, asyncio.Event] = {}
_request_waiters: dict[str, int] = {}
_response_events: dict[str, asyncio.Event] = {}


def _get_request_event(client_id: str) -> asyncio.Event:
    ev = _request_events.get(client_id)
    if ev is None:
        ev = asyncio.Event()
        _request_events[client_id] = ev
    return ev


def _get_response_event(request_id: str) -> asyncio.Event:
    ev = _response_events.get(request_id)
    if ev is None:
        ev = asyncio.Event()
        _response_events[request_id] = ev
    return ev


# ================= Utilities =================
def _sanitize_for_bson(s):
    """MongoDB/BSON rifiutano stringhe UTF-8 con NUL byte. Pulisce tutto."""
    if s is None:
        return ""
    if not isinstance(s, str):
        s = str(s)
    return s.replace("\x00", "").encode("utf-8", "replace").decode("utf-8", "replace")


def _decode_body(body_raw: str, body_encoding: str) -> bytes:
    """Decodifica il body in base ai possibili formati trasmessi dal Connector."""
    if not body_raw:
        return b""
    if body_encoding == "base64":
        try:
            return base64.b64decode(body_raw, validate=False)
        except Exception:
            return b""
    # text: considero come UTF-8 string (compat back v3.0-v3.1.6)
    return body_raw.encode("utf-8", "replace")


def _encode_body_for_storage(body_bytes: bytes) -> dict:
    """Ritorna dict per MongoDB: preferisce stringa UTF-8 se valida e senza NUL,
    altrimenti base64 per safety."""
    if not body_bytes:
        return {"body_b64": "", "is_binary": False, "size": 0}
    # Prova UTF-8 senza NUL
    has_nul = b"\x00" in body_bytes
    if not has_nul:
        try:
            as_str = body_bytes.decode("utf-8")
            return {"body": as_str, "is_binary": False, "size": len(body_bytes)}
        except UnicodeDecodeError:
            pass
    return {
        "body_b64": base64.b64encode(body_bytes).decode("ascii"),
        "is_binary": True,
        "size": len(body_bytes),
    }


# ================= Metrics =================
async def _record_metric(client_id: str, device_ip: str, duration_ms: int,
                         status_code: int, size_bytes: int, error: str = None):
    """Salva metric per ogni web-proxy call. TTL 30 giorni via index."""
    try:
        await db.web_proxy_metrics.insert_one({
            "client_id": client_id,
            "device_ip": device_ip,
            "duration_ms": duration_ms,
            "status_code": status_code,
            "size_bytes": size_bytes,
            "error": error,
            "timestamp": datetime.now(timezone.utc),
        })
    except Exception as e:
        logger.warning(f"metric insert failed: {e}")


# ================= ROUTES =================

@router.post("/connector/web-proxy/request")
async def create_web_proxy_request(request: Request, current_user: dict = Depends(get_current_user)):
    """Il browser crea una richiesta per un device remoto.
    Body: client_id, device_ip, port, path, method, body (opzionale), body_encoding,
          headers (opzionali), session_id (opzionale per cookie-persistence).
    """
    if current_user.get("role") == "viewer":
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    body = await request.json()
    client_id = body.get("client_id")
    device_ip = body.get("device_ip")
    port = int(body.get("port", 80) or 80)
    path = str(body.get("path", "/") or "/")
    method = str(body.get("method", "GET") or "GET").upper()
    scheme = str(body.get("scheme", "") or "").lower()
    session_id = body.get("session_id") or str(uuid.uuid4())
    request_body = body.get("body", "")
    request_body_encoding = body.get("body_encoding", "text")
    request_headers = body.get("headers") or {}

    if not client_id or not device_ip:
        raise HTTPException(status_code=400, detail="client_id and device_ip required")
    if method not in VALID_METHODS:
        raise HTTPException(status_code=400, detail=f"Method {method} not allowed")
    if len(path) > MAX_PATH_LEN:
        raise HTTPException(status_code=400, detail="Path too long")

    # Verifica device authorized
    device = await db.managed_devices.find_one(
        {"client_id": client_id, "ip": device_ip}, {"_id": 0}
    )
    if not device:
        poll = await db.device_poll_status.find_one(
            {"client_id": client_id, "device_ip": device_ip}, {"_id": 0}
        )
        if not poll:
            raise HTTPException(status_code=403, detail="Device not authorized for this client")

    # Se scheme non specificato, desumi da porta / web_console_scheme
    if not scheme:
        scheme = device.get("web_console_scheme") if device else None
        if not scheme:
            scheme = "https" if port in (443, 8443, 4443) else "http"

    # Recupera cookie jar della sessione (se presente)
    jar_doc = await db.web_proxy_sessions.find_one(
        {"session_id": session_id, "client_id": client_id, "device_ip": device_ip},
        {"_id": 0, "cookies": 1},
    )
    session_cookies = (jar_doc or {}).get("cookies") or {}

    request_id = str(uuid.uuid4())
    await db.web_proxy_requests.insert_one({
        "request_id": request_id,
        "session_id": session_id,
        "client_id": client_id,
        "device_ip": device_ip,
        "port": port,
        "scheme": scheme,
        "path": path,
        "method": method,
        "request_body": request_body,
        "request_body_encoding": request_body_encoding,
        "request_headers": request_headers,
        "session_cookies": session_cookies,
        "status": "pending",
        "requested_by": current_user.get("email", "unknown"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "response": None,
    })
    # Hot-trigger
    ev = _request_events.get(client_id)
    if ev is not None:
        ev.set()

    # ---- v4 bridge: se c'e' un agent v4 connesso per questo client,
    # invia la richiesta direttamente via WS (asincrono). L'agent
    # rispondera' con la response che salviamo in DB esattamente come
    # farebbe il legacy long-poll. Questo abilita la Web Console LIVE
    # con il nuovo agent Go senza long-polling.
    try:
        from routes.agent_ws import REGISTRY as _AGENT_REGISTRY  # noqa: WPS433
        v4_conns = [c for c in _AGENT_REGISTRY.list() if c.client_id == client_id]
        if v4_conns:
            asyncio.create_task(_dispatch_to_agent_v4(
                v4_conns[0], request_id, client_id, device_ip, port, scheme,
                path, method, request_body, request_body_encoding,
                request_headers, session_cookies, session_id,
            ))
    except Exception as _e:  # noqa: BLE001
        logger.warning("agent v4 bridge dispatch failed: %s", _e)

    audit.info(
        f"[AUDIT] web_proxy_request | user={current_user.get('email')} | "
        f"method={method} | device={device_ip}:{port}{path} | client={client_id} | session={session_id}"
    )
    return {"request_id": request_id, "session_id": session_id, "status": "pending"}


async def _dispatch_to_agent_v4(
    conn, request_id: str, client_id: str, device_ip: str, port: int,
    scheme: str, path: str, method: str, request_body: str,
    body_encoding: str, request_headers: dict, session_cookies: dict,
    session_id: str,
):
    """Invia la web_proxy request a un agent v4 (WebSocket) e salva la
    response nel DB. Idempotente rispetto al long-polling: se l'agent
    risponde dopo che il legacy connector ha gia' completato la richiesta,
    l'update non avra' effetti (status gia' 'completed')."""
    try:
        reply = await conn.send_command(
            "web_proxy",
            {
                "request_id": request_id,
                "session_id": session_id,
                "device_ip": device_ip,
                "port": port,
                "scheme": scheme,
                "path": path,
                "method": method,
                "request_body": request_body,
                "request_body_encoding": body_encoding,
                "request_headers": request_headers or {},
                "session_cookies": session_cookies or {},
            },
            timeout=30.0,
        )
        if not reply.get("ok"):
            await db.web_proxy_requests.update_one(
                {"request_id": request_id, "status": {"$ne": "completed"}},
                {"$set": {
                    "status": "error",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "response": {"error": reply.get("error", "agent error")},
                }},
            )
            return
        result = reply.get("result") or {}
        await db.web_proxy_requests.update_one(
            {"request_id": request_id, "status": {"$ne": "completed"}},
            {"$set": {
                "status": "completed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "response": {
                    "status_code": result.get("status_code", 200),
                    "content_type": result.get("content_type", ""),
                    "body": result.get("body", ""),
                    "body_encoding": result.get("body_encoding", "text"),
                    "response_headers": result.get("response_headers", {}),
                    "cookies": result.get("cookies", {}),
                    "duration_ms": result.get("duration_ms", 0),
                    "via": "agent-v4-ws",
                },
            }},
        )
        # Persisti cookie per la session (per i request successivi)
        cookies = result.get("cookies") or {}
        if cookies:
            await db.web_proxy_sessions.update_one(
                {"session_id": session_id, "client_id": client_id, "device_ip": device_ip},
                {"$set": {"cookies": cookies, "updated_at": datetime.now(timezone.utc).isoformat()}},
                upsert=True,
            )
        # Notifica response listener
        ev = _get_response_event(request_id)
        if ev is not None:
            ev.set()
    except asyncio.TimeoutError:
        logger.warning("agent v4 web_proxy timeout request_id=%s", request_id)
        await db.web_proxy_requests.update_one(
            {"request_id": request_id, "status": {"$ne": "completed"}},
            {"$set": {
                "status": "error",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "response": {"error": "agent timeout"},
            }},
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("agent v4 web_proxy dispatch failed: %s", e)


@router.get("/connector/web-proxy/pending")
async def get_pending_web_proxy_requests(request: Request, wait: int = 0):
    """Connector endpoint. Long-polling per ricevere richieste.
    Risposta include: method, path, body (se presente), session_cookies, request_headers.
    """
    client_data = await validate_api_key(request)
    client_id = client_data["id"]

    async def _fetch():
        return await db.web_proxy_requests.find(
            {"client_id": client_id, "status": "pending"}, {"_id": 0}
        ).sort("created_at", 1).to_list(5)

    requests_list = await _fetch()

    if not requests_list and wait > 0:
        wait_clamped = min(int(wait), LONG_POLL_MAX_SEC)
        ev = _get_request_event(client_id)
        ev.clear()
        _request_waiters[client_id] = _request_waiters.get(client_id, 0) + 1
        try:
            await asyncio.wait_for(ev.wait(), timeout=wait_clamped)
        except asyncio.TimeoutError:
            pass
        finally:
            _request_waiters[client_id] = max(0, _request_waiters.get(client_id, 1) - 1)
            if _request_waiters.get(client_id, 0) == 0:
                _request_events.pop(client_id, None)
                _request_waiters.pop(client_id, None)
        requests_list = await _fetch()

    # Mark as in_progress atomically
    for req in requests_list:
        await db.web_proxy_requests.update_one(
            {"request_id": req["request_id"]}, {"$set": {"status": "in_progress"}}
        )
    return {"requests": requests_list}


@router.post("/connector/web-proxy/response")
async def submit_web_proxy_response(request: Request):
    """Connector posta la response del device.
    Campi attesi:
      - request_id (required)
      - status_code (int)
      - content_type (str)
      - body (str)             -- se body_encoding=text
      - body_b64 (str)         -- se body_encoding=base64
      - body_encoding          -- "text" (default) | "base64"
      - title (str, opz)
      - error (str, opz)
      - response_headers (dict, opz)
      - response_cookies (dict, opz)
      - duration_ms (int, opz)
    """
    client_data = await validate_api_key(request)
    body = await request.json()
    request_id = body.get("request_id")
    if not request_id:
        raise HTTPException(status_code=400, detail="request_id required")

    # Recupera il request doc per sapere session_id
    req_doc = await db.web_proxy_requests.find_one(
        {"request_id": request_id, "client_id": client_data["id"]},
        {"_id": 0, "session_id": 1, "device_ip": 1, "created_at": 1}
    )
    if not req_doc:
        raise HTTPException(status_code=404, detail="request_id not found")

    # Decode body in base64 o text
    encoding = str(body.get("body_encoding", "text") or "text").lower()
    if encoding == "base64":
        body_b64_in = body.get("body_b64", "") or body.get("body", "")
        body_bytes = _decode_body(body_b64_in, "base64")
    else:
        body_text_in = body.get("body", "") or ""
        body_bytes = _decode_body(body_text_in, "text")

    if len(body_bytes) > MAX_BODY_BYTES:
        body_bytes = body_bytes[:MAX_BODY_BYTES]

    body_stored = _encode_body_for_storage(body_bytes)

    try:
        status_code = int(body.get("status_code", 0))
    except (TypeError, ValueError):
        status_code = 0
    try:
        duration_ms = int(body.get("duration_ms", 0))
    except (TypeError, ValueError):
        duration_ms = 0

    title = _sanitize_for_bson(body.get("title", ""))[:512]
    content_type = _sanitize_for_bson(body.get("content_type", "text/html"))[:256]
    error_str = body.get("error")
    if error_str is not None:
        error_str = _sanitize_for_bson(str(error_str))[:2048]

    response_headers = body.get("response_headers") or {}
    if not isinstance(response_headers, dict):
        response_headers = {}

    response_cookies = body.get("response_cookies") or {}
    if not isinstance(response_cookies, dict):
        response_cookies = {}

    # Aggiorna cookie jar della sessione (merge)
    if response_cookies and req_doc.get("session_id"):
        await db.web_proxy_sessions.update_one(
            {
                "session_id": req_doc["session_id"],
                "client_id": client_data["id"],
                "device_ip": req_doc.get("device_ip"),
            },
            {"$set": {
                f"cookies.{k}": _sanitize_for_bson(str(v))[:2048]
                for k, v in response_cookies.items() if k
            }, "$setOnInsert": {
                "created_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )

    # Store response
    response_doc = {
        "status_code": status_code,
        "content_type": content_type,
        "title": title,
        "error": error_str,
        "duration_ms": duration_ms,
        "response_headers": {
            _sanitize_for_bson(k)[:128]: _sanitize_for_bson(str(v))[:2048]
            for k, v in response_headers.items() if k
        },
    }
    response_doc.update(body_stored)

    await db.web_proxy_requests.update_one(
        {"request_id": request_id, "client_id": client_data["id"]},
        {"$set": {
            "status": "completed",
            "response": response_doc,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }},
    )

    # Hot-trigger waiter
    ev = _response_events.get(request_id)
    if ev is not None:
        ev.set()

    # Record metric (fire-and-forget)
    asyncio.create_task(_record_metric(
        client_id=client_data["id"],
        device_ip=req_doc.get("device_ip", ""),
        duration_ms=duration_ms,
        status_code=status_code,
        size_bytes=body_stored.get("size", 0),
        error=error_str,
    ))

    return {"status": "ok", "size": body_stored.get("size", 0)}


@router.get("/connector/web-proxy/response/{request_id}")
async def get_web_proxy_response(
    request_id: str, wait: int = 0, current_user: dict = Depends(get_current_user)
):
    """Frontend endpoint.
    Se `wait>0`: long-poll fino a `wait` secondi.
    Restituisce body sempre come string (decodificato dal base64 se necessario).
    """
    doc = await db.web_proxy_requests.find_one(
        {"request_id": request_id}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Request not found")

    if wait > 0 and doc.get("status") != "completed":
        wait_clamped = min(int(wait), LONG_POLL_MAX_SEC)
        ev = _get_response_event(request_id)
        try:
            await asyncio.wait_for(ev.wait(), timeout=wait_clamped)
        except asyncio.TimeoutError:
            pass
        doc = await db.web_proxy_requests.find_one(
            {"request_id": request_id}, {"_id": 0}
        )
        if not doc:
            _response_events.pop(request_id, None)
            raise HTTPException(status_code=404, detail="Request not found")

    # Best-effort cleanup vecchie completed
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=CLEANUP_MINUTES)).isoformat()
    await db.web_proxy_requests.delete_many(
        {"created_at": {"$lt": cutoff}, "status": "completed"}
    )
    if doc.get("status") == "completed":
        _response_events.pop(request_id, None)

    # Prepara response_body decodificato per il frontend (sempre come stringa)
    resp = doc.get("response") or {}
    if resp:
        if resp.get("is_binary") and resp.get("body_b64"):
            # Il browser si aspetta una stringa; facciamo decode best-effort
            try:
                body_bytes = base64.b64decode(resp["body_b64"])
                # Se è HTML/text lo restituisco decodificato
                ct = (resp.get("content_type") or "").lower()
                if any(x in ct for x in ("text/", "html", "xml", "json", "javascript", "css")):
                    resp["body"] = body_bytes.decode("utf-8", "replace")
                else:
                    # Binary: lascio il base64 + setta flag per frontend
                    resp["body"] = ""
                    resp["body_b64"] = resp["body_b64"]  # già presente
            except Exception as e:
                logger.warning(f"base64 decode failed for {request_id}: {e}")
                resp["body"] = resp.get("body_b64", "")
        # Rimuovi campi internal non richiesti lato client
        resp.pop("body_b64", None)

    return {
        "request_id": doc["request_id"],
        "session_id": doc.get("session_id"),
        "status": doc["status"],
        "response": resp or None,
        "device_ip": doc.get("device_ip"),
        "port": doc.get("port"),
        "scheme": doc.get("scheme"),
        "path": doc.get("path"),
        "method": doc.get("method"),
    }


@router.get("/connector/web-proxy/metrics")
async def get_web_proxy_metrics(
    client_id: str = None,
    hours: int = 24,
    current_user: dict = Depends(get_current_user)
):
    """Admin metrics: aggregazione ultime N ore."""
    if current_user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin only")
    hours = max(1, min(hours, 24 * 7))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    match = {"timestamp": {"$gte": cutoff}}
    if client_id:
        match["client_id"] = client_id

    pipe = [
        {"$match": match},
        {"$group": {
            "_id": "$device_ip",
            "requests": {"$sum": 1},
            "avg_ms": {"$avg": "$duration_ms"},
            "max_ms": {"$max": "$duration_ms"},
            "total_bytes": {"$sum": "$size_bytes"},
            "errors": {"$sum": {"$cond": [{"$ne": ["$error", None]}, 1, 0]}},
            "last_seen": {"$max": "$timestamp"},
        }},
        {"$sort": {"requests": -1}},
        {"$limit": 100},
    ]
    per_device = await db.web_proxy_metrics.aggregate(pipe).to_list(100)
    for d in per_device:
        d["device_ip"] = d.pop("_id")
        d["avg_ms"] = round(d.get("avg_ms") or 0, 1)
        if d.get("last_seen"):
            d["last_seen"] = d["last_seen"].isoformat()

    totals = await db.web_proxy_metrics.aggregate([
        {"$match": match},
        {"$group": {
            "_id": None,
            "requests": {"$sum": 1},
            "errors": {"$sum": {"$cond": [{"$ne": ["$error", None]}, 1, 0]}},
            "total_bytes": {"$sum": "$size_bytes"},
            "avg_ms": {"$avg": "$duration_ms"},
        }}
    ]).to_list(1)
    totals = totals[0] if totals else {"requests": 0, "errors": 0, "total_bytes": 0, "avg_ms": 0}
    totals.pop("_id", None)
    totals["avg_ms"] = round(totals.get("avg_ms") or 0, 1)

    return {"window_hours": hours, "totals": totals, "per_device": per_device}
