"""
Remote Browser (RMT) via HTTP only — SSE + POST fallback.

Evita WebSocket per non richiedere configurazione infrastrutturale speciale sul
custom domain (argus.86bit.it). Funziona su qualunque ingress HTTP standard.

Endpoints:
  POST /api/console-rmt/session               → crea JWT session (riuso)
  GET  /api/console-rmt/stream/{token}        → SSE event-stream, server→browser, frame+status
  POST /api/console-rmt/input/{token}         → browser→server, input events (mouse/key/scroll/close)
  POST /api/console-rmt/frame/{token}         → connector→server, push frame JPEG
  GET  /api/console-rmt/poll-inputs/{token}   → connector→server long-poll (fino a 25s) per ricevere batch input
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from datetime import datetime, timezone, timedelta
from typing import Optional
import asyncio
import json
import uuid
import logging

import jwt

from database import db
from deps import get_current_user
from routes.console_rmt import SECRET_KEY, ALGORITHM, _is_connector_supported, REQUIRED_CONNECTOR_VERSION

router = APIRouter(prefix="/api/console-rmt", tags=["console-remote-browser-http"])
logger = logging.getLogger(__name__)
audit = logging.getLogger("audit")


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=410, detail="Sessione scaduta")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token invalido")


# In-memory per-session queues.
# frames: queue[str] JSON-serialized events pushed to operator (SSE)
# inputs: queue[dict] input events waiting for connector long-poll
_FRAME_Q: dict[str, asyncio.Queue] = {}
_INPUT_Q: dict[str, asyncio.Queue] = {}
_SESSION_META: dict[str, dict] = {}
# Latest frame per session (for polling fallback) — stores (seq, data_dict)
_LATEST_FRAME: dict[str, tuple[int, dict]] = {}
_LATEST_STATUS: dict[str, dict] = {}
_SEQ: dict[str, int] = {}
_START_DISPATCHED: dict[str, bool] = {}


def _get_frame_q(sid: str) -> asyncio.Queue:
    if sid not in _FRAME_Q:
        _FRAME_Q[sid] = asyncio.Queue(maxsize=120)
    return _FRAME_Q[sid]


def _get_input_q(sid: str) -> asyncio.Queue:
    if sid not in _INPUT_Q:
        _INPUT_Q[sid] = asyncio.Queue(maxsize=200)
    return _INPUT_Q[sid]


# ============== BROWSER SIDE ==============

@router.get("/stream/{token}")
async def sse_stream(token: str):
    """SSE endpoint. Il browser operatore riceve qui tutti i frame + status.

    Il response stream è `Content-Type: text/event-stream` con keep-alive pings
    ogni 15s per evitare che proxy/ingress taglino la connessione idle.
    """
    payload = _decode_token(token)
    sid = payload["sid"]
    client_id = payload["cid"]
    device_ip = payload["dip"]
    port = payload["dport"]

    # Check connector status
    connector = await db.connector_status.find_one({"client_id": client_id}, {"_id": 0, "connector_version": 1, "is_offline": 1})
    version = (connector or {}).get("connector_version")
    offline = (connector or {}).get("is_offline", True)

    async def event_generator():
        if offline:
            yield f"data: {json.dumps({'type':'error','msg':'Connector offline. Accendi il PC del cliente.'})}\n\n"
            return
        if not _is_connector_supported(version):
            msg_text = f"Remote Browser richiede connector v{REQUIRED_CONNECTOR_VERSION}+. Versione: v{version or 'sconosciuta'}."
            upgrade_payload = {
                "type": "upgrade_required",
                "msg": msg_text,
                "current_version": version,
                "required_version": REQUIRED_CONNECTOR_VERSION,
            }
            yield f"data: {json.dumps(upgrade_payload)}\n\n"
            return

        # Dispatch start command
        _SESSION_META[sid] = {
            "device_ip": device_ip, "port": port, "client_id": client_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.pending_commands.insert_one({
            "id": str(uuid.uuid4()),
            "client_id": client_id,
            "type": "remote_browser_start",
            "payload": {
                "session_id": sid,
                "device_ip": device_ip,
                "port": port,
                "token": token,
                "transport": "http",  # tell connector to use POST/poll instead of WS
            },
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        yield f"data: {json.dumps({'type':'ready','msg':'Comando inviato al connector, in attesa del primo frame...'})}\n\n"

        q = _get_frame_q(sid)
        try:
            while True:
                try:
                    # Wait for next event with 15s timeout (keepalive)
                    evt = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {evt}\n\n"
                except asyncio.TimeoutError:
                    # Keepalive ping (SSE comment)
                    yield f": ping {datetime.now(timezone.utc).isoformat()}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            # Don't flush the session here — Connector may still send; cleanup via timeout
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/input/{token}")
async def post_input(token: str, body: dict):
    """Browser → server. Accoda un input event nella coda del connector."""
    payload = _decode_token(token)
    sid = payload["sid"]
    q = _get_input_q(sid)
    try:
        q.put_nowait(body)
    except asyncio.QueueFull:
        # Drop oldest for back-pressure
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            pass
        q.put_nowait(body)
    return {"ok": True}


# ============== CONNECTOR SIDE ==============

@router.post("/frame/{token}")
async def push_frame(token: str, body: dict):
    """Connector → server. Pushes a single frame (base64 JPEG).
    Used both by SSE (pushes into _FRAME_Q) and polling (stored in _LATEST_FRAME).
    """
    payload = _decode_token(token)
    sid = payload["sid"]
    # Polling fallback: store latest frame with incremental seq
    _SEQ[sid] = _SEQ.get(sid, 0) + 1
    _LATEST_FRAME[sid] = (_SEQ[sid], {
        "data": body.get("data", ""),
        "ts": body.get("ts"),
        "w": body.get("w"),
        "h": body.get("h"),
    })
    # SSE path (legacy, kept for backward compat)
    q = _get_frame_q(sid)
    evt = json.dumps({
        "type": "frame",
        "data": body.get("data", ""),
        "ts": body.get("ts"),
        "w": body.get("w"),
        "h": body.get("h"),
    })
    try:
        q.put_nowait(evt)
    except asyncio.QueueFull:
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            pass
        q.put_nowait(evt)
    return {"ok": True, "seq": _SEQ[sid]}


@router.get("/latest-frame/{token}")
async def latest_frame(token: str, since: int = 0):
    """Polling endpoint per browser: ritorna l'ultimo frame disponibile se seq > since.
    Altrimenti 204 No Content. Timeout veloce (non è long-poll), il browser riprova ogni 250ms.
    """
    from fastapi.responses import JSONResponse, Response
    payload = _decode_token(token)
    sid = payload["sid"]
    latest = _LATEST_FRAME.get(sid)
    if not latest or latest[0] <= since:
        # No new frame yet
        return Response(status_code=204)
    seq, frame = latest
    return JSONResponse({"seq": seq, **frame})


@router.get("/poll-status/{token}")
async def poll_status_route(token: str):
    """Browser chiede lo status corrente (ready/upgrade/error/closed).
    Dispatcha il 'remote_browser_start' al connector al primo poll.
    """
    from fastapi.responses import JSONResponse
    payload = _decode_token(token)
    sid = payload["sid"]
    client_id = payload["cid"]
    device_ip = payload["dip"]
    port = payload["dport"]

    # If we already have a status set by the connector, return it
    if sid in _LATEST_STATUS:
        return JSONResponse(_LATEST_STATUS[sid])

    # First call: check connector and dispatch
    connector = await db.connector_status.find_one({"client_id": client_id}, {"_id": 0, "connector_version": 1, "is_offline": 1})
    version = (connector or {}).get("connector_version")
    offline = (connector or {}).get("is_offline", True)

    if offline:
        return JSONResponse({"type": "error", "msg": "Connector offline. Accendi il PC del cliente."})
    if not _is_connector_supported(version):
        return JSONResponse({
            "type": "upgrade_required",
            "msg": f"Remote Browser richiede connector v{REQUIRED_CONNECTOR_VERSION}+. Versione: v{version or 'sconosciuta'}.",
            "current_version": version,
            "required_version": REQUIRED_CONNECTOR_VERSION,
        })

    # Dispatch start once
    if not _START_DISPATCHED.get(sid):
        _START_DISPATCHED[sid] = True
        await db.pending_commands.insert_one({
            "id": str(uuid.uuid4()),
            "client_id": client_id,
            "type": "remote_browser_start",
            "payload": {
                "session_id": sid,
                "device_ip": device_ip,
                "port": port,
                "token": token,
                "transport": "http",
            },
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    return JSONResponse({"type": "ready", "msg": "In attesa che il connector avvii Edge headless..."})


@router.get("/poll-inputs/{token}")
async def poll_inputs(token: str):
    """Connector long-poll (fino a 25s) che ritorna batch di input eventi dal browser.
    Ritorna subito non appena c'è almeno 1 evento, o dopo 25s con lista vuota (connector rilancia).
    """
    payload = _decode_token(token)
    sid = payload["sid"]
    q = _get_input_q(sid)

    events = []
    try:
        first = await asyncio.wait_for(q.get(), timeout=25.0)
        events.append(first)
        # Drain any others immediately available
        while True:
            try:
                events.append(q.get_nowait())
            except asyncio.QueueEmpty:
                break
    except asyncio.TimeoutError:
        pass

    return {"events": events, "ts": datetime.now(timezone.utc).isoformat()}


@router.post("/status/{token}")
async def push_status(token: str, body: dict):
    """Connector → server. Pushes status updates (es. 'edge_started', 'error', 'closed')."""
    payload = _decode_token(token)
    sid = payload["sid"]
    status_obj = {
        "type": body.get("type", "status"),
        "msg": body.get("msg", ""),
        **{k: v for k, v in body.items() if k not in ("type", "msg")},
    }
    # Save for polling fallback (only overwrite if more meaningful state)
    if body.get("type") in ("error", "closed", "edge_started", "streaming"):
        _LATEST_STATUS[sid] = status_obj
    # SSE queue (legacy)
    q = _get_frame_q(sid)
    evt = json.dumps(status_obj)
    try:
        q.put_nowait(evt)
    except asyncio.QueueFull:
        pass
    return {"ok": True}
