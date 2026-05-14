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
    """Auto-Discovery aggregata: fonde i risultati della discovery SNMP classica
    (lanciata via 'Avvia Scansione') con i dati live raccolti dal Connector
    Scanner via /api/connector/lan-scan (collection `discovered_endpoints`).

    Cosi' nella UI Auto-Discovery l'admin vede TUTTO: sia gli host SNMP scoperti
    dal master, sia gli host scoperti dagli scanner remoti su VLAN isolate.
    """
    results = await db.discovery_results.find_one({"client_id": client_id}, {"_id": 0})
    devices: list = []
    scanned_at = None
    if results:
        devices = results.get("devices", []) or []
        scanned_at = results.get("scanned_at")

    # v3.8.12: aggrega dati live dei Connector Scanner.
    # I record arrivano da POST /api/connector/lan-scan e finiscono in
    # `discovered_endpoints` con last_seen_via=arp|mdns|scanner-ui.
    # Mappiamo nel formato del frontend DiscoveryPage.
    seen_keys = {(d.get("ip") or "").strip(): True for d in devices if d.get("ip")}
    scanner_eps = await db.discovered_endpoints.find(
        {"client_id": client_id, "source_connector_mode": {"$in": ["scanner", "agent_v4"]}},
        {
            "_id": 0, "ip": 1, "mac": 1, "hostname_scanner": 1,
            "sys_descr_scanner": 1, "sys_name_scanner": 1, "vendor_scanner": 1,
            "last_seen_at": 1, "last_seen_via": 1, "vlan_id": 1,
            "last_seen_subnet": 1, "datto_name": 1,
        },
    ).to_list(2000)
    scanner_count = 0
    latest_scanner_at = None
    for ep in scanner_eps:
        ip = (ep.get("ip") or "").strip()
        if not ip or ip in seen_keys:
            continue
        seen_keys[ip] = True
        last_seen = ep.get("last_seen_at")
        if last_seen and (latest_scanner_at is None or last_seen > latest_scanner_at):
            latest_scanner_at = last_seen
        devices.append({
            "ip": ip,
            "mac": ep.get("mac"),
            "hostname": ep.get("hostname_scanner") or ep.get("datto_name") or ep.get("sys_name_scanner"),
            "vendor": ep.get("vendor_scanner"),
            "reachable": True,  # se l'abbiamo visto via ARP/mDNS e' raggiungibile sul layer-2 della VLAN remota
            "snmp_available": False,
            "type": "scanner-endpoint",
            "discovered_via": ep.get("last_seen_via") or "scanner",
            "vlan_id": ep.get("vlan_id"),
            "subnet": ep.get("last_seen_subnet"),
            "source": "scanner",
            "last_seen_at": last_seen,
            "community": "public",
        })
        scanner_count += 1

    managed = await db.managed_devices.find({"client_id": client_id}, {"_id": 0, "ip": 1}).to_list(500)
    return {
        "devices": devices,
        "managed_ips": [d["ip"] for d in managed],
        "scanned_at": scanned_at,
        "scanner_endpoints_count": scanner_count,
        "scanner_last_seen_at": latest_scanner_at,
        "device_count": len(devices),
    }


@router.get("/connector/discovery-status/{client_id}")
async def get_discovery_status(client_id: str, current_user: dict = Depends(get_current_user)):
    req = await db.discovery_requests.find_one({"client_id": client_id}, {"_id": 0})
    if not req:
        return {"status": "none"}
    return {"status": req.get("status", "none"), "requested_at": req.get("requested_at")}
