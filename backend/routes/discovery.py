"""Network discovery routes."""
from fastapi import APIRouter, Depends, HTTPException, Request
from datetime import datetime, timezone

from database import db
from deps import get_current_user, validate_api_key

router = APIRouter(prefix="/api", tags=["discovery"])


@router.post("/connector/start-discovery")
async def start_network_discovery(request: Request, current_user: dict = Depends(get_current_user)):
    body = await request.json()
    client_id = body.get("client_id")
    subnet = body.get("subnet", "")
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id required")
    await db.discovery_requests.update_one(
        {"client_id": client_id},
        {"$set": {
            "client_id": client_id, "subnet": subnet, "status": "pending",
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "requested_by": current_user.get("name", "admin")
        }},
        upsert=True
    )
    return {"status": "ok", "message": "Discovery scan requested"}


@router.get("/connector/discovery-check")
async def check_discovery_request(request: Request):
    client_data = await validate_api_key(request)
    req = await db.discovery_requests.find_one({"client_id": client_data["id"], "status": "pending"}, {"_id": 0})
    if req:
        await db.discovery_requests.update_one({"client_id": client_data["id"]}, {"$set": {"status": "in_progress"}})
        return {"scan_requested": True, "subnet": req.get("subnet", "")}
    return {"scan_requested": False}


@router.post("/connector/discovery-results")
async def submit_discovery_results(request: Request):
    client_data = await validate_api_key(request)
    body = await request.json()
    devices = body.get("devices", [])
    managed = await db.managed_devices.find({"client_id": client_data["id"]}, {"_id": 0, "ip": 1}).to_list(500)
    managed_ips = {d["ip"] for d in managed}
    await db.discovery_results.update_one(
        {"client_id": client_data["id"]},
        {"$set": {
            "client_id": client_data["id"], "devices": devices,
            "managed_ips": list(managed_ips),
            "scanned_at": datetime.now(timezone.utc).isoformat(),
            "device_count": len(devices)
        }},
        upsert=True
    )
    await db.discovery_requests.update_one({"client_id": client_data["id"]}, {"$set": {"status": "completed"}})
    return {"status": "ok", "devices_found": len(devices)}


@router.get("/connector/discovery-results/{client_id}")
async def get_discovery_results(client_id: str, current_user: dict = Depends(get_current_user)):
    results = await db.discovery_results.find_one({"client_id": client_id}, {"_id": 0})
    if not results:
        return {"devices": [], "scanned_at": None}
    managed = await db.managed_devices.find({"client_id": client_id}, {"_id": 0, "ip": 1}).to_list(500)
    results["managed_ips"] = [d["ip"] for d in managed]
    return results


@router.get("/connector/discovery-status/{client_id}")
async def get_discovery_status(client_id: str, current_user: dict = Depends(get_current_user)):
    req = await db.discovery_requests.find_one({"client_id": client_id}, {"_id": 0})
    if not req:
        return {"status": "none"}
    return {"status": req.get("status", "none"), "requested_at": req.get("requested_at")}
