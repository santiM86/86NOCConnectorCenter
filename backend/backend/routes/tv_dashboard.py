"""TV Dashboard - Full-screen NOC monitoring view for wall displays.
Provides aggregated, enriched data optimized for at-a-glance monitoring."""
import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter
from database import db

logger = logging.getLogger("tv_dashboard")
router = APIRouter(prefix="/api/tv", tags=["tv-dashboard"])


# --- Hardware Health Matrix aggregation helpers ------------------------------

_RANK = {"critical": 3, "warning": 2, "ok": 1, "unknown": 0}
_SUBSYSTEM_KEYS = ("system", "thermal", "fans", "power", "memory", "storage", "processors", "network")


def _norm_health(h):
    h = (h or "").lower().strip()
    if h in ("critical", "failed", "fatal"):
        return "critical"
    if h in ("warning", "degraded", "predictive"):
        return "warning"
    if h in ("ok", "good"):
        return "ok"
    return "unknown"


def _worst(a: str, b: str) -> str:
    return a if _RANK.get(a, 0) >= _RANK.get(b, 0) else b


def _agg(items, getter=lambda x: x.get("health")):
    """Return worst-of across items, ignoring unknown. Returns 'unknown' if no valid item."""
    worst = "unknown"
    seen = False
    for it in items or []:
        v = _norm_health(getter(it))
        if v == "unknown":
            continue
        seen = True
        worst = _worst(worst, v)
    return worst if seen else "unknown"


def _compute_subsystems_for_device(poll_doc: dict) -> dict:
    """Compute 8-subsystem health from a single device_poll_status doc (iLO)."""
    rf = (poll_doc.get("redfish") or {}) if poll_doc else {}
    hw = (poll_doc.get("hardware") or {}) if poll_doc else {}
    # Thermal from hardware.temperatures (filter stale)
    temps = [t for t in (hw.get("temperatures") or []) if not t.get("stale")]
    thermal = _agg(temps, lambda t: t.get("condition") or t.get("health"))
    # Fans
    fans = [f for f in (hw.get("fans") or []) if not f.get("stale")]
    fans_h = _agg(fans, lambda f: f.get("condition") or f.get("health"))
    # PSUs
    psus = hw.get("power_supplies") or []
    power_h = _agg(psus, lambda p: p.get("condition") or p.get("health"))
    # Memory
    dimms = [d for d in (rf.get("memory_dimms") or []) if (d.get("capacity_mb") or 0) > 0]
    memory_h = _agg(dimms)
    # Storage (controllers + drives + failure_predicted)
    storage_items = []
    for ctrl in (rf.get("storage_controllers") or []):
        storage_items.append({"health": ctrl.get("health")})
        for dr in (ctrl.get("drives") or []):
            storage_items.append({"health": dr.get("health")})
            if dr.get("failure_predicted"):
                storage_items.append({"health": "warning"})
    storage_h = _agg(storage_items)
    # Network (only NICs that are up or were configured)
    nic_items = []
    for nic in (rf.get("network_adapters") or []):
        ls = (nic.get("link_status") or "").lower()
        if ls == "linkdown" and nic.get("speed_mbps"):
            nic_items.append({"health": "warning"})
        elif ls in ("linkup", "up"):
            nic_items.append({"health": nic.get("health") or "ok"})
    network_h = _agg(nic_items)
    # Processors: aggregated from CPU-named temperature sensors (proxy)
    cpu_t = [t for t in temps if (t.get("locale") or t.get("name") or "").lower() and
             ("cpu" in (t.get("locale") or t.get("name") or "").lower() or
              "processor" in (t.get("locale") or t.get("name") or "").lower())]
    processors_h = _agg(cpu_t, lambda t: t.get("condition") or t.get("health"))
    # System
    system_h = _norm_health(hw.get("health_status"))
    return {
        "system": system_h,
        "thermal": thermal,
        "fans": fans_h,
        "power": power_h,
        "memory": memory_h,
        "storage": storage_h,
        "processors": processors_h,
        "network": network_h,
    }


def _rollup_subsystems(list_of_subsystems):
    """Rollup worst-of across multiple device subsystems dicts."""
    out = {k: "unknown" for k in _SUBSYSTEM_KEYS}
    for subs in list_of_subsystems or []:
        if not subs:
            continue
        for k in _SUBSYSTEM_KEYS:
            out[k] = _worst(out[k], _norm_health(subs.get(k)))
    return out



def _time_ago(iso_str: str) -> str:
    """Convert ISO timestamp to human-readable 'time ago' string in Italian."""
    if not iso_str:
        return ""
    try:
        then = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = now - then
        secs = int(diff.total_seconds())
        if secs < 60:
            return f"{secs}s fa"
        elif secs < 3600:
            return f"{secs // 60}m fa"
        elif secs < 86400:
            h = secs // 3600
            m = (secs % 3600) // 60
            return f"{h}h {m}m fa" if m > 0 else f"{h}h fa"
        else:
            d = secs // 86400
            return f"{d}g fa"
    except Exception:
        return ""


@router.get("/dashboard")
async def tv_dashboard_data():
    """Aggregated data for TV display. No auth required for easy TV setup."""
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    five_min_ago = (now - timedelta(minutes=5)).isoformat()

    # 1. All clients
    clients_raw = await db.clients.find({}, {"_id": 0, "api_key": 0}).to_list(100)
    client_name_map = {c["id"]: c["name"] for c in clients_raw}

    # 2. All connector statuses
    connectors = await db.connector_status.find({}, {"_id": 0}).to_list(100)
    connector_map = {c.get("client_id"): c for c in connectors}

    # 3. All device poll statuses
    all_devices = await db.device_poll_status.find({}, {"_id": 0}).to_list(2000)

    # 4. Managed devices (for names)
    managed = await db.managed_devices.find({}, {"_id": 0}).to_list(2000)
    managed_name_map = {}
    for m in managed:
        managed_name_map[f"{m.get('client_id')}:{m.get('ip')}"] = m.get("name", m.get("ip", ""))

    # 5. Active alerts - enriched with device/client names
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    active_alerts_raw = await db.alerts.find(
        {"status": "active"}, {"_id": 0}
    ).sort("created_at", -1).to_list(50)
    active_alerts_raw.sort(key=lambda a: severity_order.get(a.get("severity", "low"), 4))

    # Build device_id -> info map for enrichment
    device_id_map = {}
    for m in managed:
        device_id_map[m.get("id", "")] = {"name": m.get("name", ""), "ip": m.get("ip", "")}

    enriched_alerts = []
    for a in active_alerts_raw:
        cid = a.get("client_id", "")
        dev_ip = a.get("device_ip", a.get("source_ip", ""))
        dev_name = a.get("device_name", "")
        # Resolve from device_id if name/ip missing
        did = a.get("device_id", "")
        if did and did in device_id_map:
            if not dev_name:
                dev_name = device_id_map[did]["name"]
            if not dev_ip:
                dev_ip = device_id_map[did]["ip"]
        if not dev_name:
            dev_name = managed_name_map.get(f"{cid}:{dev_ip}", dev_ip or "Sconosciuto")
        enriched_alerts.append({
            "id": a.get("id", ""),
            "severity": a.get("severity", "low"),
            "title": a.get("title", a.get("trap_type", "")),
            "message": a.get("value", a.get("message", a.get("description", ""))),
            "device_name": dev_name,
            "device_ip": dev_ip,
            "client_name": client_name_map.get(cid, ""),
            "client_id": cid,
            "created_at": a.get("created_at", ""),
            "time_ago": _time_ago(a.get("created_at", "")),
        })

    # 6. Printer status
    low_toner_printers = []
    all_printers = await db.printer_status.find({}, {"_id": 0}).to_list(500)
    printers_online = sum(1 for p in all_printers if p.get("reachable"))
    printers_offline = len(all_printers) - printers_online
    for p in all_printers:
        for s in p.get("supplies", []):
            level = s.get("level_pct")
            if level is not None and 0 < level <= 15:
                low_toner_printers.append({
                    "printer_name": p.get("device_name", p.get("device_ip")),
                    "printer_ip": p.get("device_ip"),
                    "client_name": client_name_map.get(p.get("client_id"), ""),
                    "supply_name": s.get("name", "?"),
                    "level_pct": level,
                    "color_hex": s.get("color_hex", "#9e9e9e"),
                })

    # 7. Build per-client summary + collect ALL offline devices
    client_summaries = []
    all_offline_devices = []
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

        client_alerts = [a for a in enriched_alerts if a.get("client_id") == cid]
        critical_count = sum(1 for a in client_alerts if a.get("severity") == "critical")
        high_count = sum(1 for a in client_alerts if a.get("severity") == "high")

        connector = connector_map.get(cid)
        connector_online = False
        connector_version = ""
        last_heartbeat = ""
        if connector:
            last_seen = connector.get("last_seen", "")
            if last_seen and last_seen > five_min_ago:
                connector_online = True
            connector_version = connector.get("connector_version", "")
            last_heartbeat = _time_ago(last_seen) if last_seen else "mai"

        # Offline devices with enriched data
        problem_devices = []
        for d in client_devices:
            if not d.get("reachable"):
                dev_ip = d.get("device_ip", "")
                dev_name = managed_name_map.get(f"{cid}:{dev_ip}", dev_ip)
                last_seen_dev = d.get("last_seen", d.get("updated_at", ""))
                offline_dev = {
                    "ip": dev_ip,
                    "name": dev_name,
                    "client_name": client["name"],
                    "client_id": cid,
                    "last_seen": last_seen_dev,
                    "down_since": _time_ago(last_seen_dev),
                }
                problem_devices.append(offline_dev)
                all_offline_devices.append(offline_dev)

        # Online devices list for this client
        online_devices = []
        for d in client_devices:
            if d.get("reachable"):
                dev_ip = d.get("device_ip", "")
                dev_name = managed_name_map.get(f"{cid}:{dev_ip}", dev_ip)
                online_devices.append({"ip": dev_ip, "name": dev_name})

        health = round((online / max(len(client_devices), 1)) * 100)

        # Hardware Health Matrix (rollup worst-of across iLO servers of this client)
        ilo_docs = [d for d in client_devices
                    if d.get("device_class") == "hpe-ilo"
                    or d.get("monitor_type") == "redfish_direct"
                    or (d.get("redfish") or {}).get("server_model")]
        ilo_subs = [_compute_subsystems_for_device(d) for d in ilo_docs]
        hw_health = _rollup_subsystems(ilo_subs) if ilo_subs else None

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
            "last_heartbeat": last_heartbeat,
            "problem_devices": problem_devices[:8],
            "online_devices": online_devices[:20],
            "printer_count": sum(1 for p in all_printers if p.get("client_id") == cid),
            "hardware_health": hw_health,
            "ilo_server_count": len(ilo_docs),
        })

    # 8. Open incidents (enriched)
    open_incidents_raw = await db.incidents.find(
        {"status": {"$in": ["open", "in_progress"]}}, {"_id": 0}
    ).sort("created_at", -1).to_list(10)
    open_incidents = []
    for inc in open_incidents_raw:
        open_incidents.append({
            "id": inc.get("id", ""),
            "title": inc.get("title", ""),
            "priority": inc.get("priority", "medium"),
            "status": inc.get("status", "open"),
            "client_name": client_name_map.get(inc.get("client_id"), ""),
            "created_at": inc.get("created_at", ""),
            "time_ago": _time_ago(inc.get("created_at", "")),
        })

    # 9. Connector status list
    connector_list = []
    for client in clients_raw:
        cid = client["id"]
        conn = connector_map.get(cid)
        if conn:
            last_seen = conn.get("last_seen", "")
            online = last_seen > five_min_ago if last_seen else False
            connector_list.append({
                "client_name": client["name"],
                "hostname": conn.get("hostname", ""),
                "version": conn.get("connector_version", ""),
                "online": online,
                "last_seen": _time_ago(last_seen) if last_seen else "mai",
                "ip": conn.get("local_ip", ""),
            })

    # 10. Recent events for ticker (last 10 alerts/events)
    recent_events = await db.alerts.find(
        {}, {"_id": 0}
    ).sort("created_at", -1).to_list(15)
    ticker_events = []
    for ev in recent_events:
        cid = ev.get("client_id", "")
        dev_ip = ev.get("device_ip", ev.get("source_ip", ""))
        dev_name = ev.get("device_name", managed_name_map.get(f"{cid}:{dev_ip}", dev_ip))
        ticker_events.append({
            "severity": ev.get("severity", "low"),
            "message": f"{dev_name} ({dev_ip}) - {ev.get('title', ev.get('trap_type', ''))} - {ev.get('value', ev.get('message', ''))}",
            "client_name": client_name_map.get(cid, ""),
            "time_ago": _time_ago(ev.get("created_at", "")),
        })

    # 11. WAN monitoring data (external probe results)
    wan_diagnoses = await db.wan_client_diagnosis.find({}, {"_id": 0}).to_list(100)
    wan_diag_map = {d["client_id"]: d for d in wan_diagnoses}
    wan_results = await db.wan_probe_results.find({}, {"_id": 0}).to_list(500)
    wan_by_client = {}
    for wr in wan_results:
        cid = wr.get("client_id", "")
        if cid not in wan_by_client:
            wan_by_client[cid] = []
        wan_by_client[cid].append({
            "label": wr.get("label", ""),
            "device_type": wr.get("device_type", ""),
            "public_ip": wr.get("public_ip", ""),
            "status": wr.get("status", "unknown"),
            "latency_ms": wr.get("ping", {}).get("latency_ms"),
            "packet_loss_pct": wr.get("ping", {}).get("packet_loss_pct"),
            "ports": wr.get("ports", []),
            "checked_at": wr.get("checked_at", ""),
        })

    # Enrich client summaries with WAN data
    for cs in client_summaries:
        cid = cs["id"]
        cs["wan_targets"] = wan_by_client.get(cid, [])
        diag = wan_diag_map.get(cid)
        cs["wan_diagnosis"] = diag.get("diagnosis", "not_configured") if diag else "not_configured"
        cs["wan_diagnosis_text"] = diag.get("diagnosis_text", "Non configurato") if diag else "Non configurato"

    return {
        "timestamp": now_iso,
        "global_stats": {
            "total_clients": len(clients_raw),
            "total_devices": total_devices_count,
            "total_online": total_online,
            "total_offline": total_offline,
            "total_alerts": len(enriched_alerts),
            "critical_alerts": sum(1 for a in enriched_alerts if a.get("severity") == "critical"),
            "high_alerts": sum(1 for a in enriched_alerts if a.get("severity") == "high"),
            "open_incidents": len(open_incidents),
            "total_printers": len(all_printers),
            "printers_online": printers_online,
            "printers_offline": printers_offline,
            "low_toner_count": len(low_toner_printers),
        },
        "clients": client_summaries,
        "offline_devices": all_offline_devices,
        "alerts": enriched_alerts[:20],
        "incidents": open_incidents,
        "connectors": connector_list,
        "low_toner": low_toner_printers[:10],
        "ticker": ticker_events[:15],
    }



@router.get("/clients/{client_id}/hardware-health")
async def client_hardware_health(client_id: str):
    """Aggregate hardware Health Matrix for all iLO servers of a client.
    Returns {subsystems, ilo_server_count, per_device[]}. No auth (same as TV board)."""
    docs = await db.device_poll_status.find(
        {
            "client_id": client_id,
            "$or": [
                {"device_class": "hpe-ilo"},
                {"monitor_type": "redfish_direct"},
                {"redfish.server_model": {"$nin": [None, ""]}},
            ],
        },
        {"_id": 0}
    ).to_list(100)
    per_device = []
    all_subs = []
    for d in docs:
        subs = _compute_subsystems_for_device(d)
        per_device.append({
            "device_ip": d.get("device_ip"),
            "device_name": d.get("device_name") or d.get("device_ip"),
            "subsystems": subs,
        })
        all_subs.append(subs)
    return {
        "client_id": client_id,
        "ilo_server_count": len(docs),
        "subsystems": _rollup_subsystems(all_subs) if all_subs else None,
        "per_device": per_device,
    }
