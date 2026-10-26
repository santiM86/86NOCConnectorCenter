"""
Remote Browser (RMT) via HTTP only — polling + header-based auth.

v2: Token JWT passato in header X-RMT-Token invece che nel path, per evitare
WAF/proxy che rigettano URL con JWT lunghi (causa 400 Bad Request su alcuni ingress prod).
"""
from fastapi import APIRouter, HTTPException, Header, Request
from fastapi.responses import JSONResponse, Response
from datetime import datetime, timezone
from typing import Optional
import asyncio
import json
import uuid
import logging

import jwt

from database import db
from routes.console_rmt import SECRET_KEY, ALGORITHM, _is_connector_supported, REQUIRED_CONNECTOR_VERSION

router = APIRouter(prefix="/api/console-rmt", tags=["console-remote-browser-http"])
logger = logging.getLogger(__name__)


def _decode_token(token: str) -> dict:
    if not token:
        raise HTTPException(status_code=401, detail="Token mancante")
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=410, detail="Sessione scaduta")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token invalido")


def _resolve_token(token_header: Optional[str], token_query: Optional[str], token_path: Optional[str]) -> str:
    """Accetta il token da header (preferito), query string o path (legacy)."""
    return (token_header or token_query or token_path or "").strip()


# Shared state with path-based router
_LATEST_FRAME: dict[str, tuple[int, dict]] = {}
_LATEST_STATUS: dict[str, dict] = {}
_SEQ: dict[str, int] = {}
_START_DISPATCHED: dict[str, bool] = {}
_INPUT_Q: dict[str, asyncio.Queue] = {}


def _get_input_q(sid: str) -> asyncio.Queue:
    if sid not in _INPUT_Q:
        _INPUT_Q[sid] = asyncio.Queue(maxsize=200)
    return _INPUT_Q[sid]


# ============== BROWSER SIDE ==============

@router.get("/poll-status")
async def poll_status_v2(
    x_rmt_token: Optional[str] = Header(None, alias="X-RMT-Token"),
    token: Optional[str] = None,
):
    """Status poll (header-based). Dispatcha start al connector al primo poll."""
    t = _resolve_token(x_rmt_token, token, None)
    payload = _decode_token(t)
    sid = payload["sid"]
    client_id = payload["cid"]
    device_ip = payload["dip"]
    port = payload["dport"]

    if sid in _LATEST_STATUS:
        return JSONResponse(_LATEST_STATUS[sid])

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
                "token": t,
                "transport": "http",
            },
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    return JSONResponse({"type": "ready", "msg": "In attesa che il connector avvii Edge headless..."})


@router.get("/latest-frame")
async def latest_frame_v2(
    since: int = 0,
    x_rmt_token: Optional[str] = Header(None, alias="X-RMT-Token"),
    token: Optional[str] = None,
):
    """Polling frame. Ritorna 200+JSON se nuovo frame, 204 se nessun update."""
    t = _resolve_token(x_rmt_token, token, None)
    payload = _decode_token(t)
    sid = payload["sid"]
    latest = _LATEST_FRAME.get(sid)
    if not latest or latest[0] <= since:
        return Response(status_code=204)
    seq, frame = latest
    return JSONResponse({"seq": seq, **frame})


@router.post("/input")
async def post_input_v2(
    body: dict,
    x_rmt_token: Optional[str] = Header(None, alias="X-RMT-Token"),
    token: Optional[str] = None,
):
    """Browser → server, input event."""
    t = _resolve_token(x_rmt_token, token, None)
    payload = _decode_token(t)
    sid = payload["sid"]
    q = _get_input_q(sid)
    try:
        q.put_nowait(body)
    except asyncio.QueueFull:
        try: q.get_nowait()
        except asyncio.QueueEmpty: pass
        q.put_nowait(body)
    return {"ok": True}


# ============== CONNECTOR SIDE ==============

@router.post("/frame")
async def push_frame_v2(
    body: dict,
    x_rmt_token: Optional[str] = Header(None, alias="X-RMT-Token"),
    token: Optional[str] = None,
):
    """Connector → server, push frame JPEG base64."""
    t = _resolve_token(x_rmt_token, token, None)
    payload = _decode_token(t)
    sid = payload["sid"]
    _SEQ[sid] = _SEQ.get(sid, 0) + 1
    _LATEST_FRAME[sid] = (_SEQ[sid], {
        "data": body.get("data", ""),
        "ts": body.get("ts"),
        "w": body.get("w"),
        "h": body.get("h"),
    })
    return {"ok": True, "seq": _SEQ[sid]}


@router.get("/poll-inputs")
async def poll_inputs_v2(
    x_rmt_token: Optional[str] = Header(None, alias="X-RMT-Token"),
    token: Optional[str] = None,
):
    """Connector long-poll (25s) per batch input dal browser."""
    t = _resolve_token(x_rmt_token, token, None)
    payload = _decode_token(t)
    sid = payload["sid"]
    q = _get_input_q(sid)
    events = []
    try:
        first = await asyncio.wait_for(q.get(), timeout=25.0)
        events.append(first)
        while True:
            try: events.append(q.get_nowait())
            except asyncio.QueueEmpty: break
    except asyncio.TimeoutError:
        pass
    return {"events": events, "ts": datetime.now(timezone.utc).isoformat()}


@router.post("/status")
async def push_status_v2(
    body: dict,
    x_rmt_token: Optional[str] = Header(None, alias="X-RMT-Token"),
    token: Optional[str] = None,
):
    """Connector → server, status updates."""
    t = _resolve_token(x_rmt_token, token, None)
    payload = _decode_token(t)
    sid = payload["sid"]
    status_obj = {
        "type": body.get("type", "status"),
        "msg": body.get("msg", ""),
        **{k: v for k, v in body.items() if k not in ("type", "msg")},
    }
    if body.get("type") in ("error", "closed", "edge_started", "streaming"):
        _LATEST_STATUS[sid] = status_obj
    return {"ok": True}
