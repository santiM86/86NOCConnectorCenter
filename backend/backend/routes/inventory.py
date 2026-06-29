"""Device Inventory - Full network inventory with advanced filtering."""
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query
from database import db
from deps import get_current_user

logger = logging.getLogger("inventory")
router = APIRouter(prefix="/api/inventory", tags=["inventory"])


@router.get("/{client_id}")
async def get_inventory(
    client_id: str,
    search: str = "",
    device_type: str = "",
    status: str = "",
    sort_by: str = "device_ip",
    sort_dir: str = "asc",
    current_user: dict = Depends(get_current_user)
):
    """Get full device inventory for a client with filtering."""
    devices = await db.device_poll_status.find(
        {"client_id": client_id}, {"_id": 0}
    ).to_list(1000)

    managed = await db.managed_devices.find(
        {"client_id": client_id}, {"_id": 0}
    ).to_list(1000)
    managed_map = {m.get("ip"): m for m in managed}

    now = datetime.now(timezone.utc)
    inventory = []

    for d in devices:
        ip = d.get("device_ip", "")
        mgd = managed_map.get(ip, {})

        last_seen_str = d.get("last_seen") or d.get("last_poll")
        uptime_str = ""
        if last_seen_str:
            try:
                last_dt = datetime.fromisoformat(last_seen_str.replace("Z", "+00:00"))
                diff = now - last_dt
                days = diff.days
                hours = diff.seconds // 3600
                uptime_str = f"{days}g {hours}h" if days > 0 else f"{hours}h"
            except Exception:
                pass

        ports = d.get("ports", [])
        ports_up = sum(1 for p in ports if p.get("status") == "up")
        ports_total = len(ports)

        dev_type = d.get("device_type", mgd.get("type", "unknown"))
        if not dev_type or dev_type == "unknown":
            name_lower = (d.get("device_name") or "").lower()
            if any(kw in name_lower for kw in ["switch", "gs1", "gs3", "netgear"]):
                dev_type = "switch"
            elif any(kw in name_lower for kw in ["firewall", "usg", "zyxel", "fortigate"]):
                dev_type = "firewall"
            elif any(kw in name_lower for kw in ["server", "hpe", "dell"]):
                dev_type = "server"
            elif any(kw in name_lower for kw in ["ap", "wifi", "access point"]):
                dev_type = "ap"

        item = {
            "device_ip": ip,
            "device_name": d.get("device_name", ""),
            "device_type": dev_type,
            "monitor_type": d.get("monitor_type", mgd.get("monitor_type", "PING")),
            "reachable": d.get("reachable", False),
            "mac": d.get("mac", ""),
            "sys_descr": d.get("sys_descr", ""),
            "firmware": d.get("firmware", d.get("sys_descr", "")[:60]),
            "ping_ms": d.get("ping_ms"),
            "last_seen": last_seen_str or "",
            "uptime_display": uptime_str,
            "ports_up": ports_up,
            "ports_total": ports_total,
            "community": mgd.get("community", ""),
            "snmp_version": mgd.get("snmp_version", "v2c"),
        }
        inventory.append(item)

    if search:
        s = search.lower()
        inventory = [i for i in inventory if (
            s in i["device_ip"].lower() or
            s in i["device_name"].lower() or
            s in i["mac"].lower() or
            s in i["sys_descr"].lower()
        )]

    if device_type:
        inventory = [i for i in inventory if i["device_type"] == device_type]

    if status == "online":
        inventory = [i for i in inventory if i["reachable"]]
    elif status == "offline":
        inventory = [i for i in inventory if not i["reachable"]]

    reverse = sort_dir == "desc"
    if sort_by in ("device_ip", "device_name", "device_type", "monitor_type", "last_seen"):
        inventory.sort(key=lambda x: x.get(sort_by, ""), reverse=reverse)
    elif sort_by == "ping_ms":
        inventory.sort(key=lambda x: x.get("ping_ms") or 9999, reverse=reverse)
    elif sort_by == "reachable":
        inventory.sort(key=lambda x: x.get("reachable", False), reverse=reverse)

    types_count = {}
    for i in inventory:
        t = i["device_type"] or "unknown"
        types_count[t] = types_count.get(t, 0) + 1

    return {
        "client_id": client_id,
        "total": len(inventory),
        "online": sum(1 for i in inventory if i["reachable"]),
        "offline": sum(1 for i in inventory if not i["reachable"]),
        "types": types_count,
        "devices": inventory,
    }
