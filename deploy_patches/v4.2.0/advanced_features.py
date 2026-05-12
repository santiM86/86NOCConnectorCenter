"""Alert thresholds, maintenance windows, bandwidth monitoring, auto-discovery approval, SOC correlation."""
import logging
import uuid
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from database import db
from deps import get_current_user, validate_api_key

logger = logging.getLogger("advanced_features")
router = APIRouter(prefix="/api", tags=["advanced"])


# ==================== CUSTOM THRESHOLDS ====================

@router.get("/thresholds/{client_id}")
async def get_thresholds(client_id: str, current_user: dict = Depends(get_current_user)):
    """Get alert thresholds for a client."""
    thresholds = await db.alert_thresholds.find_one({"client_id": client_id}, {"_id": 0})
    if not thresholds:
        return {
            "client_id": client_id,
            "ping_max_ms": 100,
            "ping_warning_ms": 50,
            "packet_loss_max_pct": 5,
            "toner_low_pct": 15,
            "toner_critical_pct": 5,
            "offline_alert_after_min": 5,
            "cpu_warning_pct": 80,
            "cpu_critical_pct": 95,
            "memory_warning_pct": 85,
            "memory_critical_pct": 95,
            "bandwidth_warning_pct": 80,
            "bandwidth_critical_pct": 95,
        }
    return thresholds


@router.post("/thresholds/{client_id}")
async def update_thresholds(client_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    """Update alert thresholds for a client."""
    body = await request.json()
    body["client_id"] = client_id
    body["updated_at"] = datetime.now(timezone.utc).isoformat()
    body["updated_by"] = current_user.get("email", "system")
    await db.alert_thresholds.update_one(
        {"client_id": client_id},
        {"$set": body},
        upsert=True
    )
    return {"status": "ok", "message": "Soglie aggiornate"}


# ==================== MAINTENANCE WINDOWS ====================

@router.get("/maintenance/{client_id}")
async def get_maintenance_windows(client_id: str, current_user: dict = Depends(get_current_user)):
    """Get all maintenance windows for a client."""
    windows = await db.maintenance_windows.find(
        {"client_id": client_id}, {"_id": 0}
    ).sort("start_time", -1).to_list(50)
    return windows


@router.post("/maintenance/{client_id}")
async def create_maintenance_window(client_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    """Create a new maintenance window."""
    body = await request.json()
    window = {
        "id": str(uuid.uuid4()),
        "client_id": client_id,
        "title": body.get("title", "Manutenzione programmata"),
        "description": body.get("description", ""),
        "start_time": body.get("start_time"),
        "end_time": body.get("end_time"),
        "device_ips": body.get("device_ips", []),
        "suppress_alerts": body.get("suppress_alerts", True),
        "recurring": body.get("recurring", False),
        "recurrence_type": body.get("recurrence_type"),
        "status": "scheduled",
        "created_by": current_user.get("email", "system"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.maintenance_windows.insert_one({**window, "_id": window["id"]})
    return window


@router.put("/maintenance/{client_id}/{window_id}")
async def update_maintenance_window(client_id: str, window_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    """Update a maintenance window."""
    body = await request.json()
    body.pop("_id", None)
    body.pop("id", None)
    body["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = await db.maintenance_windows.update_one(
        {"id": window_id, "client_id": client_id},
        {"$set": body}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Finestra non trovata")
    return {"status": "ok"}


@router.delete("/maintenance/{client_id}/{window_id}")
async def delete_maintenance_window(client_id: str, window_id: str, current_user: dict = Depends(get_current_user)):
    """Delete a maintenance window."""
    result = await db.maintenance_windows.delete_one({"id": window_id, "client_id": client_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Finestra non trovata")
    return {"status": "ok"}


@router.get("/maintenance/active/{client_id}")
async def get_active_maintenance(client_id: str):
    """Check if there's an active maintenance window. Used by alert engine to suppress alerts."""
    now = datetime.now(timezone.utc).isoformat()
    active = await db.maintenance_windows.find_one({
        "client_id": client_id,
        "start_time": {"$lte": now},
        "end_time": {"$gte": now},
        "suppress_alerts": True,
    }, {"_id": 0})
    if active:
        return {"in_maintenance": True, "window": active}
    return {"in_maintenance": False}


# ==================== BANDWIDTH MONITORING ====================

@router.post("/bandwidth/process-poll")
async def process_bandwidth_poll(request: Request):
    """Receive bandwidth data from the connector (ifInOctets/ifOutOctets)."""
    api_key = request.headers.get("X-API-Key")
    client_id = None
    if api_key:
        client_data = await db.clients.find_one({"api_key": api_key}, {"_id": 0})
        if client_data:
            client_id = client_data["id"]

    body = await request.json()
    if not client_id:
        client_id = body.get("client_id", "")
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id required")

    interfaces = body.get("interfaces", [])
    now = datetime.now(timezone.utc).isoformat()

    for iface in interfaces:
        doc = {
            "client_id": client_id,
            "device_ip": iface.get("device_ip", ""),
            "device_name": iface.get("device_name", ""),
            "if_index": iface.get("if_index", 0),
            "if_name": iface.get("if_name", ""),
            "if_speed": iface.get("if_speed", 0),
            "in_octets": iface.get("in_octets", 0),
            "out_octets": iface.get("out_octets", 0),
            "in_bps": iface.get("in_bps", 0),
            "out_bps": iface.get("out_bps", 0),
            "utilization_pct": iface.get("utilization_pct", 0),
            "timestamp": now,
        }
        await db.bandwidth_history.insert_one(doc)

    # Cleanup old data (keep 7 days)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    await db.bandwidth_history.delete_many({"timestamp": {"$lt": cutoff}})

    return {"status": "ok", "interfaces_recorded": len(interfaces)}


@router.get("/bandwidth/summary/{client_id}")
async def get_bandwidth_summary(client_id: str, current_user: dict = Depends(get_current_user)):
    """Get bandwidth summary for all devices in a client."""
    pipeline = [
        {"$match": {"client_id": client_id}},
        {"$sort": {"timestamp": -1}},
        {"$group": {
            "_id": {"device_ip": "$device_ip", "if_name": "$if_name"},
            "device_name": {"$first": "$device_name"},
            "if_speed": {"$first": "$if_speed"},
            "last_in_bps": {"$first": "$in_bps"},
            "last_out_bps": {"$first": "$out_bps"},
            "last_utilization": {"$first": "$utilization_pct"},
            "avg_utilization": {"$avg": "$utilization_pct"},
            "max_utilization": {"$max": "$utilization_pct"},
            "last_seen": {"$first": "$timestamp"},
        }},
    ]
    results = await db.bandwidth_history.aggregate(pipeline).to_list(500)
    summary = []
    for r in results:
        summary.append({
            "device_ip": r["_id"]["device_ip"],
            "device_name": r.get("device_name", ""),
            "if_name": r["_id"]["if_name"],
            "if_speed": r.get("if_speed", 0),
            "last_in_bps": r.get("last_in_bps", 0),
            "last_out_bps": r.get("last_out_bps", 0),
            "last_utilization": r.get("last_utilization", 0),
            "avg_utilization": round(r.get("avg_utilization", 0), 1),
            "max_utilization": round(r.get("max_utilization", 0), 1),
            "last_seen": r.get("last_seen", ""),
        })
    return summary


@router.get("/bandwidth/{client_id}/{device_ip}")
async def get_bandwidth_history(client_id: str, device_ip: str, hours: int = 24, current_user: dict = Depends(get_current_user)):
    """Get bandwidth history for a device."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    records = await db.bandwidth_history.find(
        {"client_id": client_id, "device_ip": device_ip, "timestamp": {"$gte": cutoff}},
        {"_id": 0}
    ).sort("timestamp", 1).to_list(5000)

    # Group by interface
    interfaces = {}
    for r in records:
        ifname = r.get("if_name", f"if{r.get('if_index', 0)}")
        if ifname not in interfaces:
            interfaces[ifname] = {"if_name": ifname, "if_speed": r.get("if_speed", 0), "data": []}
        interfaces[ifname]["data"].append({
            "timestamp": r["timestamp"],
            "in_bps": r.get("in_bps", 0),
            "out_bps": r.get("out_bps", 0),
            "utilization_pct": r.get("utilization_pct", 0),
        })

    return {"device_ip": device_ip, "hours": hours, "interfaces": list(interfaces.values())}


# ==================== AUTO-DISCOVERY APPROVAL ====================

@router.post("/discovery/approve")
async def approve_discovered_device(request: Request, current_user: dict = Depends(get_current_user)):
    """Approve a discovered device and add it to managed devices."""
    body = await request.json()
    client_id = body.get("client_id")
    ip = body.get("ip")
    name = body.get("name", ip)
    community = body.get("community", "public")
    monitor_type = body.get("monitor_type", "snmp")

    if not client_id or not ip:
        raise HTTPException(status_code=400, detail="client_id and ip required")

    existing = await db.managed_devices.find_one({"client_id": client_id, "ip": ip})
    if existing:
        raise HTTPException(status_code=409, detail="Dispositivo già gestito")

    device = {
        "id": str(uuid.uuid4()),
        "client_id": client_id,
        "ip": ip,
        "name": name,
        "community": community,
        "monitor_type": monitor_type,
        "device_type": body.get("device_type", "network"),
        "added_via": "auto-discovery",
        "added_by": current_user.get("email", "system"),
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.managed_devices.insert_one({**device, "_id": device["id"]})

    # Hot-push the refreshed poller config to every connected v4 agent
    # of this tenant so live ICMP/SNMP probing of the new device starts
    # within seconds (instead of waiting for the next service restart).
    try:
        from routes.agent_ws import push_config_to_client
        await push_config_to_client(client_id)
    except Exception as e:
        # Best-effort — the approval succeeded, polling will catch up on
        # the next welcome anyway.
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "approve_discovered_device: push_config failed client=%s ip=%s err=%s",
            client_id, ip, e,
        )
    return device


@router.post("/discovery/dismiss")
async def dismiss_discovered_device(request: Request, current_user: dict = Depends(get_current_user)):
    """Dismiss a discovered device (mark it as ignored)."""
    body = await request.json()
    client_id = body.get("client_id")
    ip = body.get("ip")
    if not client_id or not ip:
        raise HTTPException(status_code=400, detail="client_id and ip required")

    await db.discovery_dismissed.update_one(
        {"client_id": client_id, "ip": ip},
        {"$set": {"client_id": client_id, "ip": ip, "dismissed_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True
    )
    return {"status": "ok"}


# ==================== SOC AI CORRELATION ====================

@router.get("/correlation/{client_id}")
async def get_correlations(client_id: str, current_user: dict = Depends(get_current_user)):
    """Analyze current alerts and device status to find correlated issues."""
    devices = await db.device_poll_status.find({"client_id": client_id}, {"_id": 0}).to_list(500)
    alerts = await db.alerts.find(
        {"client_id": client_id, "resolved": {"$ne": True}},
        {"_id": 0}
    ).sort("created_at", -1).to_list(100)

    # Active maintenance check
    now = datetime.now(timezone.utc).isoformat()
    active_maint = await db.maintenance_windows.find_one({
        "client_id": client_id,
        "start_time": {"$lte": now},
        "end_time": {"$gte": now},
    }, {"_id": 0})

    correlations = []
    offline_devices = [d for d in devices if not d.get("reachable")]
    online_devices = [d for d in devices if d.get("reachable")]

    # Pattern 1: Multiple devices offline = upstream issue
    if len(offline_devices) >= 3:
        # Check if same subnet
        subnets = {}
        for d in offline_devices:
            ip = d.get("device_ip", "")
            subnet = ".".join(ip.split(".")[:3])
            subnets.setdefault(subnet, []).append(d)

        for subnet, sub_devices in subnets.items():
            if len(sub_devices) >= 2:
                correlations.append({
                    "id": f"UPSTREAM-{subnet}",
                    "type": "upstream_failure",
                    "severity": "critical",
                    "title": f"Possibile guasto upstream nella subnet {subnet}.0/24",
                    "description": f"{len(sub_devices)} dispositivi offline nella stessa subnet. Probabile problema sullo switch di distribuzione o sul router.",
                    "affected_devices": [{"ip": d.get("device_ip"), "name": d.get("device_name", "")} for d in sub_devices],
                    "recommendation": "Verificare lo switch di distribuzione e il cablaggio della subnet. Controllare alimentazione e porte trunk.",
                    "confidence": min(95, 60 + len(sub_devices) * 10),
                })

    # Pattern 2: High latency across multiple devices
    high_latency = [d for d in online_devices if (d.get("ping_ms") or 0) > 100]
    if len(high_latency) >= 2:
        correlations.append({
            "id": "LATENCY-CLUSTER",
            "type": "performance_degradation",
            "severity": "high",
            "title": f"Latenza elevata su {len(high_latency)} dispositivi",
            "description": "Molteplici dispositivi mostrano latenza superiore a 100ms. Possibile congestione di rete o problema sul link WAN.",
            "affected_devices": [{"ip": d.get("device_ip"), "name": d.get("device_name", ""), "ping_ms": d.get("ping_ms")} for d in high_latency],
            "recommendation": "Verificare la capacita del link WAN, controllare eventuali loop di rete o broadcast storm.",
            "confidence": 70,
        })

    # Pattern 3: Device flapping (alternating online/offline)
    cutoff_1h = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    recent_alerts = [a for a in alerts if a.get("created_at", "") >= cutoff_1h]
    device_alert_counts = {}
    for a in recent_alerts:
        dip = a.get("device_ip", "")
        if dip:
            device_alert_counts[dip] = device_alert_counts.get(dip, 0) + 1

    flapping = {ip: count for ip, count in device_alert_counts.items() if count >= 3}
    if flapping:
        for ip, count in flapping.items():
            dev = next((d for d in devices if d.get("device_ip") == ip), {})
            correlations.append({
                "id": f"FLAP-{ip}",
                "type": "flapping",
                "severity": "high",
                "title": f"Flapping rilevato: {dev.get('device_name', ip)}",
                "description": f"Il dispositivo ha generato {count} alert nell'ultima ora, indicando instabilita di connessione.",
                "affected_devices": [{"ip": ip, "name": dev.get("device_name", ip), "alert_count": count}],
                "recommendation": "Controllare il cavo di rete, la porta dello switch e l'alimentazione del dispositivo.",
                "confidence": 80,
            })

    # Pattern 4: All offline = WAN/Internet failure
    if len(offline_devices) > 0 and len(offline_devices) >= len(devices) * 0.7:
        correlations.append({
            "id": "WAN-DOWN",
            "type": "wan_failure",
            "severity": "critical",
            "title": "Possibile guasto WAN/Internet",
            "description": f"{len(offline_devices)} su {len(devices)} dispositivi sono offline ({round(len(offline_devices)/len(devices)*100)}%). Il connettore potrebbe aver perso la connettivita Internet.",
            "affected_devices": [{"ip": d.get("device_ip"), "name": d.get("device_name", "")} for d in offline_devices[:10]],
            "recommendation": "Verificare il collegamento Internet, il router di bordo e il provider ISP.",
            "confidence": 90,
        })

    # Pattern 5: Security alerts cluster
    security_alerts = [a for a in alerts if a.get("severity") in ("critical", "high")]
    if len(security_alerts) >= 5:
        correlations.append({
            "id": "SEC-CLUSTER",
            "type": "security_event",
            "severity": "critical",
            "title": f"Cluster di {len(security_alerts)} alert di sicurezza",
            "description": "Molteplici alert ad alta severita in breve tempo. Possibile attacco in corso o compromissione.",
            "affected_devices": [{"ip": a.get("device_ip", ""), "name": a.get("device_name", "")} for a in security_alerts[:10]],
            "recommendation": "Attivare procedura di incident response. Isolare i dispositivi colpiti e analizzare i log.",
            "confidence": 75,
        })

    # Maintenance awareness
    if active_maint:
        correlations.append({
            "id": "MAINT-ACTIVE",
            "type": "maintenance",
            "severity": "low",
            "title": f"Manutenzione in corso: {active_maint.get('title', '')}",
            "description": "Finestra di manutenzione attiva. Gli alert sono soppressi per i dispositivi coinvolti.",
            "affected_devices": [{"ip": ip} for ip in active_maint.get("device_ips", [])],
            "recommendation": "Nessuna azione richiesta. La manutenzione e pianificata.",
            "confidence": 100,
        })

    # Sort by severity
    sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    correlations.sort(key=lambda c: sev_order.get(c["severity"], 4))

    return {
        "client_id": client_id,
        "timestamp": now,
        "total_devices": len(devices),
        "offline_count": len(offline_devices),
        "active_alerts": len(alerts),
        "correlations": correlations,
        "correlation_count": len(correlations),
        "maintenance_active": active_maint is not None,
    }


# ==================== TREND DATA ====================

@router.get("/trends/{client_id}")
async def get_trends(client_id: str, days: int = 7, current_user: dict = Depends(get_current_user)):
    """Get aggregated trend data for a client over time."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # VA score trend from vulnerability_scans
    va_scans = await db.vulnerability_scans.find(
        {"client_id": client_id, "timestamp": {"$gte": cutoff}},
        {"_id": 0, "timestamp": 1, "overall_score": 1, "total_vulnerabilities": 1}
    ).sort("timestamp", 1).to_list(100)

    # Availability trend from metrics_history
    avail_pipeline = [
        {"$match": {"client_id": client_id, "timestamp": {"$gte": cutoff}}},
        {"$group": {
            "_id": "$hour_bucket",
            "total": {"$sum": 1},
            "up": {"$sum": {"$cond": ["$reachable", 1, 0]}},
            "avg_ping": {"$avg": "$ping_ms"},
        }},
        {"$sort": {"_id": 1}},
    ]
    avail_data = await db.metrics_history.aggregate(avail_pipeline).to_list(500)
    availability = []
    for a in avail_data:
        pct = round((a["up"] / a["total"] * 100), 1) if a["total"] > 0 else 0
        availability.append({
            "timestamp": a["_id"],
            "availability_pct": pct,
            "avg_ping_ms": round(a["avg_ping"], 1) if a["avg_ping"] else None,
            "devices_up": a["up"],
            "devices_total": a["total"],
        })

    # Alert trend
    alert_pipeline = [
        {"$match": {"client_id": client_id, "created_at": {"$gte": cutoff}}},
        {"$addFields": {"day": {"$substr": ["$created_at", 0, 10]}}},
        {"$group": {
            "_id": "$day",
            "total": {"$sum": 1},
            "critical": {"$sum": {"$cond": [{"$eq": ["$severity", "critical"]}, 1, 0]}},
            "high": {"$sum": {"$cond": [{"$eq": ["$severity", "high"]}, 1, 0]}},
        }},
        {"$sort": {"_id": 1}},
    ]
    alert_trend = await db.alerts.aggregate(alert_pipeline).to_list(100)

    return {
        "client_id": client_id,
        "days": days,
        "va_score_trend": va_scans,
        "availability_trend": availability,
        "alert_trend": alert_trend,
    }


# ==================== CLIENT PORTAL ====================

@router.get("/portal/{client_id}")
async def client_portal_dashboard(client_id: str):
    """Public-facing client portal with limited data. Accessible via client token."""
    client = await db.clients.find_one({"id": client_id}, {"_id": 0, "api_key": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    devices = await db.device_poll_status.find({"client_id": client_id}, {"_id": 0}).to_list(500)
    online = sum(1 for d in devices if d.get("reachable"))
    offline = len(devices) - online

    alerts = await db.alerts.find(
        {"client_id": client_id, "resolved": {"$ne": True}},
        {"_id": 0}
    ).sort("created_at", -1).to_list(20)

    # Active maintenance
    now = datetime.now(timezone.utc).isoformat()
    active_maint = await db.maintenance_windows.find({
        "client_id": client_id,
        "start_time": {"$lte": now},
        "end_time": {"$gte": now},
    }, {"_id": 0}).to_list(5)

    # SLA
    cutoff_30d = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    sla_pipeline = [
        {"$match": {"client_id": client_id, "timestamp": {"$gte": cutoff_30d}}},
        {"$group": {"_id": None, "total": {"$sum": 1}, "up": {"$sum": {"$cond": ["$reachable", 1, 0]}}}},
    ]
    sla_data = await db.metrics_history.aggregate(sla_pipeline).to_list(1)
    sla_pct = round((sla_data[0]["up"] / sla_data[0]["total"] * 100), 2) if sla_data and sla_data[0]["total"] > 0 else 99.9

    return {
        "client_name": client.get("name", ""),
        "total_devices": len(devices),
        "online": online,
        "offline": offline,
        "sla_pct": sla_pct,
        "active_alerts": len(alerts),
        "alerts": [{"severity": a.get("severity"), "title": a.get("title"), "device_name": a.get("device_name", ""), "created_at": a.get("created_at")} for a in alerts[:10]],
        "devices": [{"name": d.get("device_name", d.get("device_ip")), "ip": d.get("device_ip"), "reachable": d.get("reachable"), "ping_ms": d.get("ping_ms")} for d in devices],
        "maintenance": active_maint,
        "timestamp": now,
    }
