"""Web console proxy routes — ottimizzato con long-polling + hot-trigger."""
from fastapi import APIRouter, Depends, HTTPException, Request
import uuid
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from collections import defaultdict

from database import db
from deps import get_current_user, validate_api_key

router = APIRouter(prefix="/api", tags=["web_proxy"])

# Per-client event flags: viene "set" quando arriva una nuova richiesta,
# così eventuali long-poll bloccati sbloccano immediatamente senza attesa.
_request_events: dict[str, asyncio.Event] = defaultdict(asyncio.Event)
# Per-client response ready flags: viene "set" quando il connector fa POST della response,
# così il polling frontend sblocca subito.
_response_events: dict[str, asyncio.Event] = defaultdict(asyncio.Event)


def _request_event(client_id: str) -> asyncio.Event:
    ev = _request_events[client_id]
    return ev


def _response_event(request_id: str) -> asyncio.Event:
    ev = _response_events[request_id]
    return ev


@router.post("/connector/web-proxy/request")
async def create_web_proxy_request(request: Request, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") == "viewer":
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    body = await request.json()
    client_id = body.get("client_id")
    device_ip = body.get("device_ip")
    port = body.get("port", 80)
    path = body.get("path", "/")
    method = body.get("method", "GET")
    if not client_id or not device_ip:
        raise HTTPException(status_code=400, detail="client_id and device_ip required")
    device = await db.managed_devices.find_one({"client_id": client_id, "ip": device_ip}, {"_id": 0})
    if not device:
        poll = await db.device_poll_status.find_one({"client_id": client_id, "device_ip": device_ip}, {"_id": 0})
        if not poll:
            raise HTTPException(status_code=403, detail="Device not authorized for this client")
    request_id = str(uuid.uuid4())
    await db.web_proxy_requests.insert_one({
        "request_id": request_id, "client_id": client_id,
        "device_ip": device_ip, "port": port, "path": path, "method": method,
        "status": "pending", "requested_by": current_user.get("email", "unknown"),
        "created_at": datetime.now(timezone.utc).isoformat(), "response": None
    })
    # Hot-trigger: sblocca eventuale long-poll bloccato sul /pending
    _request_event(client_id).set()
    logging.getLogger("audit").info(
        f"[AUDIT] web_proxy_request | User: {current_user.get('email')} | Device: {device_ip}:{port}{path} | Client: {client_id}"
    )
    return {"request_id": request_id, "status": "pending"}


@router.get("/connector/web-proxy/pending")
async def get_pending_web_proxy_requests(request: Request, wait: int = 0):
    """Connector endpoint.
    - `wait=0` (default): ritorna immediatamente le richieste pending (compat).
    - `wait>0`: long-poll fino a `wait` secondi (max 25). Ritorna non appena arriva
      una nuova richiesta per il cliente (via asyncio.Event hot-trigger).
    """
    client_data = await validate_api_key(request)
    client_id = client_data["id"]

    async def _fetch():
        docs = await db.web_proxy_requests.find(
            {"client_id": client_id, "status": "pending"}, {"_id": 0}
        ).sort("created_at", 1).to_list(5)
        return docs

    requests_list = await _fetch()

    if not requests_list and wait > 0:
        wait_clamped = min(int(wait), 25)
        ev = _request_event(client_id)
        ev.clear()
        try:
            await asyncio.wait_for(ev.wait(), timeout=wait_clamped)
        except asyncio.TimeoutError:
            pass
        # Refetch after signal/timeout
        requests_list = await _fetch()

    for req in requests_list:
        await db.web_proxy_requests.update_one(
            {"request_id": req["request_id"]}, {"$set": {"status": "in_progress"}}
        )
    return {"requests": requests_list}


@router.post("/connector/web-proxy/response")
async def submit_web_proxy_response(request: Request):
    client_data = await validate_api_key(request)
    body = await request.json()
    request_id = body.get("request_id")
    if not request_id:
        raise HTTPException(status_code=400, detail="request_id required")
    await db.web_proxy_requests.update_one(
        {"request_id": request_id, "client_id": client_data["id"]},
        {"$set": {
            "status": "completed",
            "response": {
                "status_code": body.get("status_code", 0),
                "content_type": body.get("content_type", "text/html"),
                "body": body.get("body", ""), "title": body.get("title", ""),
                "error": body.get("error", None)
            },
            "completed_at": datetime.now(timezone.utc).isoformat()
        }}
    )
    # Hot-trigger: sblocca il long-poll della risposta lato frontend
    _response_event(request_id).set()
    return {"status": "ok"}


@router.get("/connector/web-proxy/response/{request_id}")
async def get_web_proxy_response(
    request_id: str, wait: int = 0, current_user: dict = Depends(get_current_user)
):
    """Frontend endpoint.
    - `wait=0` (default): ritorna subito lo stato (compat).
    - `wait>0`: long-poll fino a `wait` secondi (max 25). Ritorna appena il connector
      pubblica la risposta (via asyncio.Event hot-trigger), senza polling attivo.
    """
    doc = await db.web_proxy_requests.find_one({"request_id": request_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Request not found")

    if wait > 0 and doc.get("status") != "completed":
        wait_clamped = min(int(wait), 25)
        ev = _response_event(request_id)
        try:
            await asyncio.wait_for(ev.wait(), timeout=wait_clamped)
        except asyncio.TimeoutError:
            pass
        # Refetch fresh state
        doc = await db.web_proxy_requests.find_one({"request_id": request_id}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Request not found")

    # Best-effort cleanup of old completed requests
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    await db.web_proxy_requests.delete_many({"created_at": {"$lt": cutoff}, "status": "completed"})
    # Rimuovi l'evento dopo che il client lo ha letto (se completato)
    if doc.get("status") == "completed":
        _response_events.pop(request_id, None)

    return {
        "request_id": doc["request_id"], "status": doc["status"],
        "response": doc.get("response"), "device_ip": doc.get("device_ip"),
        "port": doc.get("port"), "path": doc.get("path")
    }
