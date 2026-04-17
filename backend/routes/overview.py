"""Aggregated client overview for NOC Dashboard."""
from fastapi import APIRouter, Depends
from database import db
from deps import get_current_user
from datetime import datetime, timezone, timedelta

router = APIRouter(prefix="/api", tags=["overview"])


@router.get("/overview/clients")
async def get_clients_overview(current_user: dict = Depends(get_current_user)):
    """Returns aggregated status for all clients: WAN, devices, alerts, backup, printers."""
    clients_raw = await db.clients.find({}, {"_id": 0}).to_list(500)
    clients = clients_raw if isinstance(clients_raw, list) else []

    # Pre-fetch all data in parallel-ish
    wan_targets = await db.wan_targets.find({"enabled": True}, {"_id": 0}).to_list(1000)
    wan_results_raw = await db.wan_probe_results.find({}, {"_id": 0}).to_list(5000)
    wan_diagnoses_raw = await db.wan_diagnoses.find({}, {"_id": 0}).to_list(500)

    active_alerts = await db.alerts.find(
        {"status": "active"}, {"_id": 0, "client_id": 1, "severity": 1}
    ).to_list(10000)

    devices = await db.devices.find({}, {"_id": 0, "client_id": 1, "status": 1, "ip_address": 1}).to_list(10000)

    # Backup status
    backup_data = await db.backup_status.find({}, {"_id": 0, "client_id": 1, "status": 1, "last_success": 1}).to_list(5000)

    # Printer status
    printer_data = await db.printers.find({}, {"_id": 0, "client_id": 1, "toner_levels": 1, "status": 1}).to_list(5000)

    # Connector status
    connectors = await db.connector_status.find({}, {"_id": 0, "client_id": 1, "last_seen": 1}).to_list(500)

    # Index by client_id
    wan_results_map = {}
    for r in wan_results_raw:
        wan_results_map[r.get("target_id")] = r

    wan_diag_map = {}
    for d in wan_diagnoses_raw:
        wan_diag_map[d.get("client_id")] = d

    wan_targets_by_client = {}
    for t in wan_targets:
        cid = t.get("client_id")
        if cid not in wan_targets_by_client:
            wan_targets_by_client[cid] = []
        wan_targets_by_client[cid].append(t)

    alerts_by_client = {}
    for a in active_alerts:
        cid = a.get("client_id")
        if cid not in alerts_by_client:
            alerts_by_client[cid] = {"critical": 0, "high": 0, "medium": 0, "low": 0, "total": 0}
        alerts_by_client[cid][a.get("severity", "low")] += 1
        alerts_by_client[cid]["total"] += 1

    devices_by_client = {}
    for d in devices:
        cid = d.get("client_id")
        if cid not in devices_by_client:
            devices_by_client[cid] = {"total": 0, "online": 0, "offline": 0}
        devices_by_client[cid]["total"] += 1
        if d.get("status") == "online":
            devices_by_client[cid]["online"] += 1
        else:
            devices_by_client[cid]["offline"] += 1

    backup_by_client = {}
    for b in backup_data:
        cid = b.get("client_id")
        if cid not in backup_by_client:
            backup_by_client[cid] = {"ok": 0, "warning": 0, "error": 0, "total": 0}
        st = b.get("status", "unknown")
        backup_by_client[cid]["total"] += 1
        if st in ("ok", "success", "completed"):
            backup_by_client[cid]["ok"] += 1
        elif st in ("warning",):
            backup_by_client[cid]["warning"] += 1
        else:
            backup_by_client[cid]["error"] += 1

    printer_by_client = {}
    for p in printer_data:
        cid = p.get("client_id")
        if cid not in printer_by_client:
            printer_by_client[cid] = {"total": 0, "low_toner": 0, "ok": 0}
        printer_by_client[cid]["total"] += 1
        toner = p.get("toner_levels", {})
        min_toner = min(toner.values()) if toner and isinstance(toner, dict) else 100
        if min_toner < 15:
            printer_by_client[cid]["low_toner"] += 1
        else:
            printer_by_client[cid]["ok"] += 1

    connector_by_client = {}
    now = datetime.now(timezone.utc)
    for c in connectors:
        cid = c.get("client_id")
        last_seen = c.get("last_seen")
        is_online = False
        if last_seen:
            if isinstance(last_seen, str):
                try:
                    ls = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
                    is_online = (now - ls).total_seconds() < 120
                except Exception:
                    pass
            elif isinstance(last_seen, datetime):
                is_online = (now - last_seen).total_seconds() < 120
        connector_by_client[cid] = is_online

    # Build response
    result = []
    for c in clients:
        cid = c.get("id")
        alerts_info = alerts_by_client.get(cid, {"critical": 0, "high": 0, "medium": 0, "low": 0, "total": 0})
        devices_info = devices_by_client.get(cid, {"total": 0, "online": 0, "offline": 0})
        backup_info = backup_by_client.get(cid, {"ok": 0, "warning": 0, "error": 0, "total": 0})
        printer_info = printer_by_client.get(cid, {"total": 0, "low_toner": 0, "ok": 0})
        wan_diag = wan_diag_map.get(cid)
        wan_tgts = wan_targets_by_client.get(cid, [])
        connector_online = connector_by_client.get(cid)

        # WAN summary
        wan_status = "not_configured"
        wan_latency = None
        wan_gateway = None
        if wan_diag:
            wan_status = wan_diag.get("diagnosis", "unknown")
            wan_gateway = wan_diag.get("gateway_status")
        elif wan_tgts:
            wan_status = "pending"
        for t in wan_tgts:
            r = wan_results_map.get(t.get("id"))
            if r and r.get("ping", {}).get("latency_ms"):
                wan_latency = r["ping"]["latency_ms"]
                break

        # Overall health score
        health = "ok"
        if alerts_info["critical"] > 0 or wan_status in ("isp_down", "firewall_down", "router_down"):
            health = "critical"
        elif alerts_info["high"] > 0 or wan_status in ("firewall_degraded", "router_degraded") or backup_info.get("error", 0) > 0:
            health = "warning"
        elif alerts_info["total"] > 0 or printer_info.get("low_toner", 0) > 0:
            health = "attention"

        result.append({
            "id": cid,
            "name": c.get("name", "?"),
            "health": health,
            "alerts": alerts_info,
            "devices": devices_info,
            "wan": {
                "status": wan_status,
                "latency_ms": wan_latency,
                "gateway": wan_gateway,
            },
            "backup": backup_info,
            "printers": printer_info,
            "connector_online": connector_online,
        })

    # Sort: critical first, then warning, then ok
    priority = {"critical": 0, "warning": 1, "attention": 2, "ok": 3}
    result.sort(key=lambda x: (priority.get(x["health"], 9), x["name"]))

    # Global stats
    total_alerts = sum(a["total"] for a in alerts_by_client.values())
    total_critical = sum(a["critical"] for a in alerts_by_client.values())

    return {
        "clients": result,
        "global": {
            "total_clients": len(clients),
            "clients_ok": sum(1 for r in result if r["health"] == "ok"),
            "clients_warning": sum(1 for r in result if r["health"] in ("warning", "attention")),
            "clients_critical": sum(1 for r in result if r["health"] == "critical"),
            "total_alerts": total_alerts,
            "critical_alerts": total_critical,
            "total_devices": sum(d["total"] for d in devices_by_client.values()),
            "devices_online": sum(d["online"] for d in devices_by_client.values()),
        },
    }
