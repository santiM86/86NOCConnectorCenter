"""Web console proxy routes."""
from fastapi import APIRouter, Depends, HTTPException, Request
import uuid
import logging
from datetime import datetime, timezone, timedelta

from database import db
from deps import get_current_user, validate_api_key

router = APIRouter(prefix="/api", tags=["web_proxy"])


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
    logging.getLogger("audit").info(
        f"[AUDIT] web_proxy_request | User: {current_user.get('email')} | Device: {device_ip}:{port}{path} | Client: {client_id}"
    )
    return {"request_id": request_id, "status": "pending"}


@router.get("/connector/web-proxy/pending")
async def get_pending_web_proxy_requests(request: Request):
    client_data = await validate_api_key(request)
    requests_list = await db.web_proxy_requests.find(
        {"client_id": client_data["id"], "status": "pending"}, {"_id": 0}
    ).sort("created_at", 1).to_list(5)
    for req in requests_list:
        await db.web_proxy_requests.update_one({"request_id": req["request_id"]}, {"$set": {"status": "in_progress"}})
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
    return {"status": "ok"}


@router.get("/connector/web-proxy/response/{request_id}")
async def get_web_proxy_response(request_id: str, current_user: dict = Depends(get_current_user)):
    doc = await db.web_proxy_requests.find_one({"request_id": request_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Request not found")
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    await db.web_proxy_requests.delete_many({"created_at": {"$lt": cutoff}, "status": "completed"})
    return {
        "request_id": doc["request_id"], "status": doc["status"],
        "response": doc.get("response"), "device_ip": doc.get("device_ip"),
        "port": doc.get("port"), "path": doc.get("path")
    }
