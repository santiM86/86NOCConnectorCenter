"""
Remote Browser (RMT) — Phase 1 scaffolding.

Archittura target (Phase 2, connector v3.4+):
  [Browser operator] <-WS-> [Backend relay] <-WS-> [Connector] <-CDP-> [Edge headless] <-HTTPS-> [Device UI]

Per ora (Phase 1):
  - POST /api/console-rmt/session  → JWT token + device meta
  - WS   /api/console-rmt/ws/{token} → relay generico. Inoltra JSON messages
    verso il connector via event bus. Se il connector non è v3.4.0, il relay invia
    un messaggio "upgrade_required" e chiude.

Protocollo messages (WS bidirezionale):
  server→client:
    {type: "ready"}
    {type: "frame", data: "<base64 JPEG>", ts: 123}
    {type: "upgrade_required", msg: "..."}
    {type: "error", msg: "..."}
    {type: "closed"}
  client→server:
    {type: "mouse", event: "move|down|up|click", x, y, button}
    {type: "key", event: "down|up|press", key, mods: {ctrl, shift, alt, meta}}
    {type: "scroll", dx, dy}
    {type: "resize", width, height}
    {type: "close"}
"""
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Request
from datetime import datetime, timezone, timedelta
from typing import Optional
import asyncio
import json
import uuid
import os
import logging

import jwt

from database import db
from deps import get_current_user

router = APIRouter(prefix="/api/console-rmt", tags=["console-remote-browser"])
logger = logging.getLogger(__name__)
audit = logging.getLogger("audit")

SECRET_KEY = os.environ.get("JWT_SECRET", "argus-console-rmt-fallback")
ALGORITHM = "HS256"
SESSION_TTL_MINUTES = 60
REQUIRED_CONNECTOR_VERSION = "3.4.1"


def _is_connector_supported(version: Optional[str]) -> bool:
    """v3.4.1+ supports RMT (HTTP transport). Lower versions get upgrade_required."""
    if not version:
        return False
    try:
        parts = [int(p) for p in version.split(".")[:3]]
        while len(parts) < 3:
            parts.append(0)
        req = [3, 4, 1]
        return parts >= req
    except Exception:
        return False


def _make_token(*, device_ip: str, port: int, client_id: str, user_email: str) -> tuple[str, datetime]:
    exp = datetime.now(timezone.utc) + timedelta(minutes=SESSION_TTL_MINUTES)
    payload = {
        "sid": str(uuid.uuid4()),
        "dip": device_ip,
        "dport": port,
        "cid": client_id,
        "usr": user_email,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM), exp


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=410, detail="Sessione scaduta")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token invalido")


@router.post("/session")
async def create_rmt_session(body: dict, current_user: dict = Depends(get_current_user)):
    """Crea una sessione RMT. Ritorna token JWT + URL WebSocket.

    Verifica preliminare: il connector del cliente deve essere v3.4.0+.
    Se non lo è, risponde comunque con sessione ma il client verrà avvisato
    nel WebSocket handshake (upgrade_required).
    """
    device_ip = str((body or {}).get("device_ip", "")).strip()
    port = int((body or {}).get("port") or 443)
    if not device_ip:
        raise HTTPException(status_code=400, detail="device_ip required")

    md = await db.managed_devices.find_one({"ip": device_ip}, {"_id": 0, "client_id": 1, "web_console_scheme": 1})
    ps = await db.device_poll_status.find_one({"device_ip": device_ip}, {"_id": 0, "client_id": 1})
    if not md and not ps:
        raise HTTPException(status_code=404, detail="Device non registrato")
    client_id = (md or ps).get("client_id")

    # Check connector version (best-effort)
    connector = await db.connector_status.find_one({"client_id": client_id}, {"_id": 0, "connector_version": 1, "is_offline": 1})
    connector_version = (connector or {}).get("connector_version")
    connector_supported = _is_connector_supported(connector_version)
    connector_offline = (connector or {}).get("is_offline", True)

    token, exp = _make_token(device_ip=device_ip, port=port, client_id=client_id, user_email=current_user.get("email", ""))

    audit.info(
        f"[AUDIT] rmt_session_created | user={current_user.get('email')} | device={device_ip}:{port} | "
        f"connector_version={connector_version} | supported={connector_supported}"
    )

    await db.rmt_sessions.insert_one({
        "sid": jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])["sid"],
        "device_ip": device_ip,
        "port": port,
        "client_id": client_id,
        "user_email": current_user.get("email"),
        "connector_version": connector_version,
        "supported": connector_supported,
        "offline": connector_offline,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": exp.isoformat(),
    })

    return {
        "token": token,
        "ws_url": f"/api/console-rmt/ws/{token}",
        "expires_at": exp.isoformat(),
        "connector_version": connector_version,
        "connector_supported": connector_supported,
        "connector_offline": connector_offline,
        "required_version": REQUIRED_CONNECTOR_VERSION,
    }


# ======================== WS relay ========================

# In-memory registry of active remote-browser sessions (device-side).
# Quando il connector si collega alla sua WS, registra qui; il browser-operator
# WS fa relay bidirezionale con quella coda.
_CONNECTOR_WS: dict[str, WebSocket] = {}
_CLIENT_WS: dict[str, WebSocket] = {}


@router.websocket("/ws/{token}")
async def rmt_operator_ws(websocket: WebSocket, token: str):
    """WebSocket operatore (browser del Center).

    Protocollo:
    1. Decode token, verifica scadenza
    2. Se connector non supportato/offline → manda 'upgrade_required' e chiude
    3. Altrimenti registra la socket e attende il connector
    4. Relay JSON bidirezionale
    """
    await websocket.accept()
    try:
        payload = _decode_token(token)
    except HTTPException as e:
        await websocket.send_json({"type": "error", "msg": e.detail})
        await websocket.close(code=4401)
        return

    sid = payload["sid"]
    client_id = payload["cid"]
    device_ip = payload["dip"]
    port = payload["dport"]

    # Check connector
    connector = await db.connector_status.find_one({"client_id": client_id}, {"_id": 0, "connector_version": 1, "is_offline": 1})
    version = (connector or {}).get("connector_version")
    offline = (connector or {}).get("is_offline", True)

    if offline:
        await websocket.send_json({
            "type": "error",
            "msg": "Connector offline. Il PC con il connector deve essere acceso e collegato.",
        })
        await websocket.close(code=4503)
        return

    if not _is_connector_supported(version):
        await websocket.send_json({
            "type": "upgrade_required",
            "msg": f"Remote Browser (RMT) richiede connector v{REQUIRED_CONNECTOR_VERSION}+. Versione installata: v{version or 'sconosciuta'}. Aggiorna dal menu Connettori del Center.",
            "current_version": version,
            "required_version": REQUIRED_CONNECTOR_VERSION,
        })
        # keep socket open 5s so the client UI can display the message
        await asyncio.sleep(5)
        await websocket.close(code=4426)
        return

    # === Phase 2: registra e fai relay ===
    _CLIENT_WS[sid] = websocket

    # Dispatch a "remote_browser_start" command to the connector via pending_commands
    await db.pending_commands.insert_one({
        "id": str(uuid.uuid4()),
        "client_id": client_id,
        "type": "remote_browser_start",
        "payload": {
            "session_id": sid,
            "device_ip": device_ip,
            "port": port,
            "token": token,
            "ws_relay_url": f"/api/console-rmt/connector-ws/{token}",
        },
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    await websocket.send_json({"type": "ready", "msg": "In attesa che il connector avvii Edge headless..."})

    # Wait for connector WS registration (max 30s)
    try:
        for _ in range(60):
            if sid in _CONNECTOR_WS:
                break
            await asyncio.sleep(0.5)
        else:
            await websocket.send_json({"type": "error", "msg": "Timeout: il connector non ha avviato la sessione remote browser entro 30 secondi."})
            await websocket.close(code=4504)
            return

        # Active relay loop (from operator → connector)
        connector_ws = _CONNECTOR_WS[sid]
        while True:
            msg = await websocket.receive_text()
            try:
                await connector_ws.send_text(msg)
            except Exception as e:
                logger.warning(f"rmt relay to connector failed sid={sid}: {e}")
                break
    except WebSocketDisconnect:
        pass
    finally:
        _CLIENT_WS.pop(sid, None)
        # Notify connector to close Edge
        cws = _CONNECTOR_WS.get(sid)
        if cws:
            try:
                await cws.send_json({"type": "close"})
            except Exception:
                pass


@router.websocket("/connector-ws/{token}")
async def rmt_connector_ws(websocket: WebSocket, token: str):
    """WebSocket del connector (server cliente).

    Il connector, dopo aver avviato Edge + CDP, si collega qui e fa relay
    degli screencast frames al browser operatore.
    """
    await websocket.accept()
    try:
        payload = _decode_token(token)
    except HTTPException:
        await websocket.close(code=4401)
        return

    sid = payload["sid"]
    _CONNECTOR_WS[sid] = websocket
    logger.info(f"RMT connector WS registered sid={sid}")

    try:
        # Relay loop connector → operator
        while True:
            msg = await websocket.receive_text()
            client_ws = _CLIENT_WS.get(sid)
            if client_ws:
                try:
                    await client_ws.send_text(msg)
                except Exception as e:
                    logger.warning(f"rmt relay to operator failed sid={sid}: {e}")
                    break
    except WebSocketDisconnect:
        pass
    finally:
        _CONNECTOR_WS.pop(sid, None)
        # Notify operator
        cws = _CLIENT_WS.get(sid)
        if cws:
            try:
                await cws.send_json({"type": "closed", "msg": "Sessione chiusa dal connector"})
            except Exception:
                pass


@router.get("/sessions")
async def list_rmt_sessions(current_user: dict = Depends(get_current_user)):
    """Admin: elenca sessioni RMT attive (audit)."""
    now_iso = datetime.now(timezone.utc).isoformat()
    cursor = db.rmt_sessions.find(
        {"expires_at": {"$gte": now_iso}}, {"_id": 0}
    ).sort("created_at", -1).limit(50)
    items = [s async for s in cursor]
    return {"active_count": len(items), "items": items}
