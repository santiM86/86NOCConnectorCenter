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

    active_alerts = await db.alerts.find(
        {"status": "active"}, {"_id": 0, "client_id": 1, "severity": 1, "title": 1, "device_name": 1, "created_at": 1, "id": 1}
    ).to_list(10000)

    devices = await db.devices.find({}, {"_id": 0, "client_id": 1, "status": 1, "ip_address": 1, "name": 1, "device_type": 1}).to_list(10000)

    # Also include connector-discovered devices (device_poll_status) and manually managed devices (managed_devices)
    poll_devices = await db.device_poll_status.find(
        {}, {"_id": 0, "client_id": 1, "device_ip": 1, "device_name": 1, "status": 1, "device_type": 1, "device_class": 1, "sys_descr": 1}
    ).to_list(10000)
    managed_devices_raw = await db.managed_devices.find(
        {}, {"_id": 0, "client_id": 1, "ip": 1, "name": 1, "device_type": 1}
    ).to_list(10000)
    # Build maps for dedup merging by (client_id, ip)
    seen_device_keys = {(d.get("client_id"), d.get("ip_address")) for d in devices if d.get("ip_address")}
    managed_by_key = {(m.get("client_id"), m.get("ip")): m for m in managed_devices_raw if m.get("ip")}

    def _infer_device_type(name, sys_descr, device_class, explicit_type):
        if explicit_type and explicit_type not in ("", "?", "network", "generic"):
            return explicit_type
        combined = f"{name or ''} {sys_descr or ''} {device_class or ''}".lower()
        if any(k in combined for k in ["firewall", "zyxel", "usg", "fortigate", "pfsense", "sonicwall"]):
            return "firewall"
        if any(k in combined for k in ["ilo", "idrac", "ipmi", "bmc", "integrated lights"]):
            return "ilo"
        if any(k in combined for k in ["ups", "xanto", "apc", "eaton", "liebert", "riello"]):
            return "ups"
        if any(k in combined for k in ["nas", "synology", "qnap", "truenas", "freenas"]):
            return "nas"
        if any(k in combined for k in ["printer", "stampa", "brother", "xerox", "kyocera", "ricoh"]):
            return "printer"
        if any(k in combined for k in ["tvcc", "nvr", "dvr", "camera", "hikvision", "dahua"]):
            return "tvcc"
        if any(k in combined for k in ["ubiquiti", "unifi", "aruba ap", "access point", "wifi"]):
            return "ap"
        if any(k in combined for k in ["switch", "catalyst", "procurve", "aruba", "5130", "5120", "netgear"]):
            return "switch"
        if any(k in combined for k in ["server", "proliant", "poweredge", "dell "]):
            return "server"
        return explicit_type or "generic"

    # Merge poll_devices and managed_devices into the unified list (skip duplicates)
    for pd in poll_devices:
        ip = pd.get("device_ip")
        cid = pd.get("client_id")
        if not ip or not cid:
            continue
        key = (cid, ip)
        if key in seen_device_keys:
            continue
        seen_device_keys.add(key)
        # Look up name/type from managed_devices if available
        md = managed_by_key.get(key, {})
        dev_type = _infer_device_type(
            md.get("name") or pd.get("device_name", ""),
            pd.get("sys_descr", ""),
            pd.get("device_class", ""),
            md.get("device_type") or pd.get("device_type"),
        )
        devices.append({
            "client_id": cid,
            "name": md.get("name") or pd.get("device_name") or ip,
            "ip_address": ip,
            "status": pd.get("status", "unknown"),
            "device_type": dev_type,
        })
    # Also add managed_devices that never polled yet
    for md in managed_devices_raw:
        ip = md.get("ip")
        cid = md.get("client_id")
        if not ip or not cid:
            continue
        key = (cid, ip)
        if key in seen_device_keys:
            continue
        seen_device_keys.add(key)
        devices.append({
            "client_id": cid,
            "name": md.get("name") or ip,
            "ip_address": ip,
            "status": "unknown",
            "device_type": md.get("device_type", "generic"),
        })

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

    wan_targets_by_client = {}
    for t in wan_targets:
        cid = t.get("client_id")
        if cid not in wan_targets_by_client:
            wan_targets_by_client[cid] = []
        wan_targets_by_client[cid].append(t)

    alerts_by_client = {}
    alerts_detail_by_client = {}
    for a in active_alerts:
        cid = a.get("client_id")
        if cid not in alerts_by_client:
            alerts_by_client[cid] = {"critical": 0, "high": 0, "medium": 0, "low": 0, "total": 0}
            alerts_detail_by_client[cid] = []
        alerts_by_client[cid][a.get("severity", "low")] += 1
        alerts_by_client[cid]["total"] += 1
        if len(alerts_detail_by_client[cid]) < 5:
            alerts_detail_by_client[cid].append({
                "id": a.get("id"), "severity": a.get("severity"), "title": a.get("title", ""),
                "device_name": a.get("device_name", ""), "created_at": a.get("created_at", ""),
            })

    devices_by_client = {}
    devices_detail_by_client = {}
    for d in devices:
        cid = d.get("client_id")
        if cid not in devices_by_client:
            devices_by_client[cid] = {"total": 0, "online": 0, "offline": 0}
            devices_detail_by_client[cid] = []
        devices_by_client[cid]["total"] += 1
        if d.get("status") == "online":
            devices_by_client[cid]["online"] += 1
        else:
            devices_by_client[cid]["offline"] += 1
        devices_detail_by_client[cid].append({
            "name": d.get("name", "?"), "ip": d.get("ip_address", ""), "status": d.get("status", "unknown"),
            "type": d.get("device_type", ""),
        })

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
        wan_tgts = wan_targets_by_client.get(cid, [])
        connector_online = connector_by_client.get(cid)

        # WAN summary — compute from probe results directly
        wan_status = "not_configured"
        wan_latency = None
        wan_gateway = None
        if wan_tgts:
            all_online = True
            any_online = False
            best_latency = None
            has_gateway = False
            gw_online = None
            for t in wan_tgts:
                r = wan_results_map.get(t.get("id"))
                if not r:
                    continue
                st = r.get("status", "unknown")
                if st in ("online", "degraded"):
                    any_online = True
                else:
                    all_online = False
                lat = r.get("ping", {}).get("latency_ms")
                if lat and (best_latency is None or lat < best_latency):
                    best_latency = lat
                # Check gateway
                gw = r.get("gateway_ping")
                if gw:
                    has_gateway = True
                    if gw.get("reachable"):
                        gw_online = "online"
                    elif gw_online is None:
                        gw_online = "offline"

            wan_latency = best_latency
            wan_gateway = gw_online
            if any_online and all_online:
                wan_status = "ok"
            elif any_online:
                wan_status = "degraded"
            elif has_gateway and gw_online == "online":
                wan_status = "router_down"
            elif has_gateway and gw_online == "offline":
                wan_status = "isp_down"
            elif not any_online and len([t for t in wan_tgts if wan_results_map.get(t.get("id"))]) > 0:
                wan_status = "offline"
            else:
                wan_status = "pending"

        # Overall health score
        health = "ok"
        if alerts_info["critical"] > 0 or wan_status in ("isp_down", "firewall_down", "router_down"):
            health = "critical"
        elif alerts_info["high"] > 0 or wan_status in ("firewall_degraded", "router_degraded") or backup_info.get("error", 0) > 0:
            health = "warning"
        elif alerts_info["total"] > 0 or printer_info.get("low_toner", 0) > 0:
            health = "attention"

        # WAN targets detail for expansion
        wan_detail = []
        for t in wan_tgts:
            r = wan_results_map.get(t.get("id"))
            wan_detail.append({
                "label": t.get("label", "?"), "device_type": t.get("device_type", "?"),
                "ip": t.get("public_ip", ""), "gateway_ip": t.get("gateway_ip"),
                "check_ping": t.get("check_ping", False),
                "status": r.get("status", "unknown") if r else "pending",
                "latency_ms": r.get("ping", {}).get("latency_ms") if r else None,
                "loss_pct": r.get("ping", {}).get("packet_loss_pct") if r else None,
                "gateway_ok": r.get("gateway_ping", {}).get("reachable") if r and r.get("gateway_ping") else None,
                "gateway_latency": r.get("gateway_ping", {}).get("latency_ms") if r and r.get("gateway_ping") else None,
                "ports": r.get("ports", []) if r else [],
                "checked_at": r.get("checked_at") if r else None,
            })

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
            "detail": {
                "wan_targets": wan_detail,
                "devices_list": devices_detail_by_client.get(cid, []),
                "recent_alerts": alerts_detail_by_client.get(cid, []),
            },
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
