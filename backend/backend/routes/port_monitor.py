"""TCP Port / Service Monitoring."""
import logging
import asyncio
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from database import db
from deps import get_current_user

logger = logging.getLogger("port_monitor")
router = APIRouter(prefix="/api/port-monitor", tags=["port-monitor"])

COMMON_SERVICES = {
    22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS",
    80: "HTTP", 110: "POP3", 143: "IMAP", 443: "HTTPS",
    445: "SMB", 993: "IMAPS", 995: "POP3S", 1433: "MSSQL",
    3306: "MySQL", 3389: "RDP", 5432: "PostgreSQL",
    5900: "VNC", 8080: "HTTP-Alt", 8443: "HTTPS-Alt",
}


async def check_tcp_port(host: str, port: int, timeout: float = 3.0):
    """Check if a TCP port is open."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        return True, None
    except asyncio.TimeoutError:
        return False, "timeout"
    except ConnectionRefusedError:
        return False, "refused"
    except OSError as e:
        return False, str(e)


@router.get("/services/{client_id}")
async def get_monitored_services(client_id: str, current_user: dict = Depends(get_current_user)):
    """Get all monitored services/ports for a client."""
    services = await db.port_monitors.find(
        {"client_id": client_id}, {"_id": 0}
    ).to_list(500)
    return services


@router.post("/services")
async def add_service_monitor(body: dict, current_user: dict = Depends(get_current_user)):
    """Add a new port/service to monitor."""
    now = datetime.now(timezone.utc).isoformat()
    service = {
        "id": str(uuid.uuid4()),
        "client_id": body.get("client_id", ""),
        "device_ip": body.get("device_ip", ""),
        "device_name": body.get("device_name", ""),
        "port": int(body.get("port", 80)),
        "service_name": body.get("service_name", COMMON_SERVICES.get(int(body.get("port", 80)), "Custom")),
        "enabled": True,
        "last_check": None,
        "is_open": None,
        "error": None,
        "response_time_ms": None,
        "created_at": now,
    }
    await db.port_monitors.insert_one({**service})
    service.pop("_id", None)
    return service


@router.delete("/services/{service_id}")
async def remove_service_monitor(service_id: str, current_user: dict = Depends(get_current_user)):
    """Remove a monitored port/service."""
    result = await db.port_monitors.delete_one({"id": service_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Servizio non trovato")
    return {"status": "ok"}


@router.post("/check/{client_id}")
async def check_all_ports(client_id: str, current_user: dict = Depends(get_current_user)):
    """Run a check on all monitored ports for a client."""
    services = await db.port_monitors.find(
        {"client_id": client_id, "enabled": True}
    ).to_list(500)

    results = []
    for svc in services:
        ip = svc.get("device_ip", "")
        port = svc.get("port", 80)
        start = asyncio.get_event_loop().time()
        is_open, error = await check_tcp_port(ip, port)
        elapsed = round((asyncio.get_event_loop().time() - start) * 1000, 1)

        now = datetime.now(timezone.utc).isoformat()
        await db.port_monitors.update_one(
            {"id": svc["id"]},
            {"$set": {
                "last_check": now,
                "is_open": is_open,
                "error": error,
                "response_time_ms": elapsed if is_open else None,
            }}
        )
        results.append({
            "id": svc["id"],
            "device_ip": ip,
            "port": port,
            "service_name": svc.get("service_name", ""),
            "is_open": is_open,
            "response_time_ms": elapsed if is_open else None,
            "error": error,
        })

    return {"client_id": client_id, "checked": len(results), "results": results}


@router.get("/common-ports")
async def get_common_ports(current_user: dict = Depends(get_current_user)):
    """Return list of common service ports."""
    return [{"port": p, "name": n} for p, n in sorted(COMMON_SERVICES.items())]
