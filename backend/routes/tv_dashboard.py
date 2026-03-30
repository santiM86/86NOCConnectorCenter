"""TV Dashboard - Full-screen NOC monitoring view for wall displays."""
import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException
from database import db

logger = logging.getLogger("tv_dashboard")
router = APIRouter(prefix="/api/tv", tags=["tv-dashboard"])


@router.get("/dashboard")
async def tv_dashboard_data():
    """Aggregated data for TV display. No auth required for easy TV setup."""
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    five_min_ago = (now - timedelta(minutes=5)).isoformat()

    # 1. All clients
    clients_raw = await db.clients.find({}, {"_id": 0, "api_key": 0}).to_list(100)

    # 2. All connector statuses
    connectors = await db.connector_status.find({}, {"_id": 0}).to_list(100)
    connector_map = {c.get("client_id"): c for c in connectors}

    # 3. All device poll statuses
    all_devices = await db.device_poll_status.find({}, {"_id": 0}).to_list(2000)

    # 4. Active alerts (sorted by severity)
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    active_alerts = await db.alerts.find(
        {"status": "active"}, {"_id": 0}
    ).sort("created_at", -1).to_list(50)
    active_alerts.sort(key=lambda a: severity_order.get(a.get("severity", "low"), 4))

    # 5. Printer alerts
    low_toner_printers = []
    all_printers = await db.printer_status.find({}, {"_id": 0}).to_list(500)
    printers_online = 0
    printers_offline = 0
    for p in all_printers:
        if p.get("reachable"):
            printers_online += 1
        else:
            printers_offline += 1
        for s in p.get("supplies", []):
            level = s.get("level_pct")
            if level is not None and 0 < level <= 15:
                low_toner_printers.append({
                    "printer_name": p.get("device_name", p.get("device_ip")),
                    "printer_ip": p.get("device_ip"),
                    "client_id": p.get("client_id"),
                    "supply_name": s.get("name", "?"),
                    "level_pct": level,
                    "color_hex": s.get("color_hex", "#9e9e9e"),
                })

    # 6. Build per-client summary
    client_summaries = []
    total_online = 0
    total_offline = 0
    total_devices_count = 0

    for client in clients_raw:
        cid = client["id"]
        client_devices = [d for d in all_devices if d.get("client_id") == cid]
        online = sum(1 for d in client_devices if d.get("reachable"))
        offline = len(client_devices) - online
        total_online += online
        total_offline += offline
        total_devices_count += len(client_devices)

        client_alerts = [a for a in active_alerts if a.get("client_id") == cid]
        critical_count = sum(1 for a in client_alerts if a.get("severity") == "critical")
        high_count = sum(1 for a in client_alerts if a.get("severity") == "high")

        connector = connector_map.get(cid)
        connector_online = False
        connector_version = ""
        if connector:
            last_seen = connector.get("last_seen", "")
            if last_seen and last_seen > five_min_ago:
                connector_online = True
            connector_version = connector.get("connector_version", "")

        # Devices with issues (offline or critical alerts)
        problem_devices = []
        for d in client_devices:
            if not d.get("reachable"):
                problem_devices.append({
                    "ip": d.get("device_ip"),
                    "name": d.get("device_name", d.get("device_ip")),
                    "status": "offline",
                })

        client_printers = [p for p in all_printers if p.get("client_id") == cid]
        printer_count = len(client_printers)

        # Health score: percentage of devices online
        health = round((online / max(len(client_devices), 1)) * 100)

        client_summaries.append({
            "id": cid,
            "name": client["name"],
            "total_devices": len(client_devices),
            "online": online,
            "offline": offline,
            "health_pct": health,
            "alert_count": len(client_alerts),
            "critical_alerts": critical_count,
            "high_alerts": high_count,
            "connector_online": connector_online,
            "connector_version": connector_version,
            "problem_devices": problem_devices[:5],
            "printer_count": printer_count,
        })

    # 7. Open incidents count
    open_incidents = await db.incidents.count_documents({"status": {"$in": ["open", "in_progress"]}})

    return {
        "timestamp": now_iso,
        "global_stats": {
            "total_clients": len(clients_raw),
            "total_devices": total_devices_count,
            "total_online": total_online,
            "total_offline": total_offline,
            "total_alerts": len(active_alerts),
            "critical_alerts": sum(1 for a in active_alerts if a.get("severity") == "critical"),
            "high_alerts": sum(1 for a in active_alerts if a.get("severity") == "high"),
            "open_incidents": open_incidents,
            "total_printers": len(all_printers),
            "printers_online": printers_online,
            "printers_offline": printers_offline,
            "low_toner_count": len(low_toner_printers),
        },
        "clients": client_summaries,
        "alerts": active_alerts[:20],
        "low_toner": low_toner_printers[:10],
    }
