"""Metrics, SLA, Change Detection & Audit routes."""
import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from database import db
from deps import get_current_user

logger = logging.getLogger("metrics")
router = APIRouter(prefix="/api", tags=["metrics"])


# ─── METRICS HISTORY ───

@router.post("/metrics/record")
async def record_metrics_snapshot(body: dict):
    """Called by polling scheduler to store device metrics history."""
    client_id = body.get("client_id")
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id required")

    now = datetime.now(timezone.utc)
    hour_bucket = now.replace(minute=0, second=0, microsecond=0).isoformat()

    devices = await db.device_poll_status.find(
        {"client_id": client_id}, {"_id": 0}
    ).to_list(500)

    records = []
    for d in devices:
        records.append({
            "client_id": client_id,
            "device_ip": d.get("device_ip"),
            "device_name": d.get("device_name", ""),
            "reachable": d.get("reachable", False),
            "ping_ms": d.get("ping_ms"),
            "monitor_type": d.get("monitor_type", ""),
            "hour_bucket": hour_bucket,
            "timestamp": now.isoformat(),
        })

    if records:
        await db.metrics_history.insert_many(records)

    return {"status": "ok", "recorded": len(records)}


@router.get("/metrics/device/{client_id}/{device_ip}")
async def get_device_metrics(client_id: str, device_ip: str, hours: int = 24, current_user: dict = Depends(get_current_user)):
    """Get historical metrics for a device."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    records = await db.metrics_history.find(
        {"client_id": client_id, "device_ip": device_ip, "timestamp": {"$gte": cutoff}},
        {"_id": 0}
    ).sort("timestamp", 1).to_list(5000)

    return {"device_ip": device_ip, "hours": hours, "data": records}


@router.get("/metrics/heatmap/{client_id}")
async def get_uptime_heatmap(client_id: str, days: int = 7, current_user: dict = Depends(get_current_user)):
    """Get uptime heatmap data: per device, per hour availability."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    pipeline = [
        {"$match": {"client_id": client_id, "timestamp": {"$gte": cutoff}}},
        {"$group": {
            "_id": {"device_ip": "$device_ip", "hour": "$hour_bucket"},
            "device_name": {"$first": "$device_name"},
            "total": {"$sum": 1},
            "up": {"$sum": {"$cond": ["$reachable", 1, 0]}},
            "avg_ping": {"$avg": "$ping_ms"},
        }},
        {"$sort": {"_id.device_ip": 1, "_id.hour": 1}},
    ]
    results = await db.metrics_history.aggregate(pipeline).to_list(10000)

    heatmap = {}
    for r in results:
        ip = r["_id"]["device_ip"]
        hour = r["_id"]["hour"]
        if ip not in heatmap:
            heatmap[ip] = {"device_name": r["device_name"], "hours": {}}
        pct = round((r["up"] / r["total"]) * 100, 1) if r["total"] > 0 else 0
        heatmap[ip]["hours"][hour] = {
            "uptime_pct": pct,
            "avg_ping": round(r["avg_ping"], 1) if r["avg_ping"] else None,
            "samples": r["total"],
        }

    return {"client_id": client_id, "days": days, "devices": heatmap}


# ─── SLA MONITORING ───

@router.get("/metrics/sla/{client_id}")
async def get_sla_report(client_id: str, days: int = 30, current_user: dict = Depends(get_current_user)):
    """Calculate SLA (uptime %) per device over a period."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    pipeline = [
        {"$match": {"client_id": client_id, "timestamp": {"$gte": cutoff}}},
        {"$group": {
            "_id": "$device_ip",
            "device_name": {"$first": "$device_name"},
            "total_checks": {"$sum": 1},
            "up_checks": {"$sum": {"$cond": ["$reachable", 1, 0]}},
            "avg_ping": {"$avg": "$ping_ms"},
            "max_ping": {"$max": "$ping_ms"},
            "min_ping": {"$min": "$ping_ms"},
        }},
        {"$sort": {"_id": 1}},
    ]
    results = await db.metrics_history.aggregate(pipeline).to_list(500)

    # Get SLA targets
    targets = {}
    target_docs = await db.sla_targets.find({"client_id": client_id}, {"_id": 0}).to_list(100)
    for t in target_docs:
        targets[t.get("device_ip", "")] = t.get("target_pct", 99.9)
    default_target = 99.9

    devices_sla = []
    total_up = 0
    total_checks = 0
    for r in results:
        ip = r["_id"]
        checks = r["total_checks"]
        up = r["up_checks"]
        pct = round((up / checks) * 100, 3) if checks > 0 else 0
        target = targets.get(ip, default_target)
        meets_sla = pct >= target

        devices_sla.append({
            "device_ip": ip,
            "device_name": r["device_name"],
            "uptime_pct": pct,
            "target_pct": target,
            "meets_sla": meets_sla,
            "total_checks": checks,
            "up_checks": up,
            "avg_ping_ms": round(r["avg_ping"], 1) if r["avg_ping"] else None,
            "max_ping_ms": r["max_ping"],
        })
        total_up += up
        total_checks += checks

    overall_sla = round((total_up / total_checks) * 100, 3) if total_checks > 0 else 0

    return {
        "client_id": client_id,
        "period_days": days,
        "overall_sla_pct": overall_sla,
        "devices": devices_sla,
        "total_checks": total_checks,
    }


@router.post("/metrics/sla-target")
async def set_sla_target(body: dict, current_user: dict = Depends(get_current_user)):
    """Set SLA target for a device or client."""
    client_id = body.get("client_id")
    device_ip = body.get("device_ip", "")
    target_pct = body.get("target_pct", 99.9)

    await db.sla_targets.update_one(
        {"client_id": client_id, "device_ip": device_ip},
        {"$set": {"client_id": client_id, "device_ip": device_ip, "target_pct": target_pct,
                  "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return {"status": "ok", "message": f"SLA target impostato a {target_pct}%"}


# ─── CHANGE DETECTION ───

@router.post("/metrics/snapshot")
async def store_network_snapshot(body: dict):
    """Store a network snapshot for change detection. Called by connector or scheduler."""
    client_id = body.get("client_id")
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id required")

    now = datetime.now(timezone.utc)

    devices = await db.device_poll_status.find(
        {"client_id": client_id}, {"_id": 0}
    ).to_list(500)

    snapshot = {
        "client_id": client_id,
        "timestamp": now.isoformat(),
        "devices": [{
            "ip": d.get("device_ip"),
            "name": d.get("device_name", ""),
            "mac": d.get("mac", ""),
            "reachable": d.get("reachable", False),
            "monitor_type": d.get("monitor_type", ""),
            "sys_descr": d.get("sys_descr", ""),
            "ports_up": sum(1 for p in d.get("ports", []) if p.get("status") == "up"),
            "ports_total": len(d.get("ports", [])),
        } for d in devices],
    }

    # Get previous snapshot
    prev = await db.network_snapshots.find_one(
        {"client_id": client_id}, {"_id": 0},
        sort=[("timestamp", -1)]
    )

    # Compare and detect changes
    changes = []
    if prev:
        prev_map = {d["ip"]: d for d in prev.get("devices", [])}
        curr_map = {d["ip"]: d for d in snapshot["devices"]}

        # New devices
        for ip in curr_map:
            if ip not in prev_map:
                changes.append({
                    "type": "device_added",
                    "severity": "info",
                    "device_ip": ip,
                    "device_name": curr_map[ip]["name"],
                    "message": f"Nuovo dispositivo rilevato: {curr_map[ip]['name']} ({ip})",
                })

        # Removed devices
        for ip in prev_map:
            if ip not in curr_map:
                changes.append({
                    "type": "device_removed",
                    "severity": "high",
                    "device_ip": ip,
                    "device_name": prev_map[ip]["name"],
                    "message": f"Dispositivo scomparso: {prev_map[ip]['name']} ({ip})",
                })

        # Changed devices
        for ip in curr_map:
            if ip in prev_map:
                curr = curr_map[ip]
                prev_d = prev_map[ip]

                if curr["name"] != prev_d["name"]:
                    changes.append({
                        "type": "name_changed",
                        "severity": "medium",
                        "device_ip": ip,
                        "device_name": curr["name"],
                        "old_value": prev_d["name"],
                        "new_value": curr["name"],
                        "message": f"Nome cambiato: '{prev_d['name']}' -> '{curr['name']}' ({ip})",
                    })

                if curr["reachable"] != prev_d["reachable"]:
                    sev = "critical" if not curr["reachable"] else "info"
                    state = "ONLINE" if curr["reachable"] else "OFFLINE"
                    changes.append({
                        "type": "status_changed",
                        "severity": sev,
                        "device_ip": ip,
                        "device_name": curr["name"],
                        "old_value": "online" if prev_d["reachable"] else "offline",
                        "new_value": "online" if curr["reachable"] else "offline",
                        "message": f"{curr['name']} ({ip}) -> {state}",
                    })

                if curr["ports_up"] != prev_d.get("ports_up", 0) or curr["ports_total"] != prev_d.get("ports_total", 0):
                    changes.append({
                        "type": "ports_changed",
                        "severity": "medium",
                        "device_ip": ip,
                        "device_name": curr["name"],
                        "old_value": f"{prev_d.get('ports_up',0)}/{prev_d.get('ports_total',0)}",
                        "new_value": f"{curr['ports_up']}/{curr['ports_total']}",
                        "message": f"Porte cambiate su {curr['name']}: {prev_d.get('ports_up',0)}/{prev_d.get('ports_total',0)} -> {curr['ports_up']}/{curr['ports_total']}",
                    })

    # Store changes
    if changes:
        for c in changes:
            c["client_id"] = client_id
            c["timestamp"] = now.isoformat()
        await db.network_changes.insert_many(changes)

    # Store snapshot (keep last 100)
    await db.network_snapshots.insert_one(snapshot)
    count = await db.network_snapshots.count_documents({"client_id": client_id})
    if count > 100:
        oldest = await db.network_snapshots.find(
            {"client_id": client_id}, {"_id": 1}
        ).sort("timestamp", 1).limit(count - 100).to_list(count - 100)
        if oldest:
            await db.network_snapshots.delete_many({"_id": {"$in": [o["_id"] for o in oldest]}})

    return {"status": "ok", "changes_detected": len(changes), "devices_in_snapshot": len(snapshot["devices"])}


@router.get("/metrics/changes/{client_id}")
async def get_network_changes(client_id: str, days: int = 7, current_user: dict = Depends(get_current_user)):
    """Get network change history."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    changes = await db.network_changes.find(
        {"client_id": client_id, "timestamp": {"$gte": cutoff}},
        {"_id": 0}
    ).sort("timestamp", -1).to_list(500)

    # Group by day
    by_day = {}
    for c in changes:
        day = c["timestamp"][:10]
        if day not in by_day:
            by_day[day] = []
        by_day[day].append(c)

    return {
        "client_id": client_id,
        "period_days": days,
        "total_changes": len(changes),
        "changes": changes,
        "by_day": by_day,
    }


# ─── AUDIT LOG ───

async def log_audit(user: str, action: str, resource: str, details: str = "", ip: str = ""):
    """Store an audit log entry."""
    await db.audit_log.insert_one({
        "user": user,
        "action": action,
        "resource": resource,
        "details": details,
        "ip": ip,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


@router.get("/audit-log")
async def get_audit_log(limit: int = 100, current_user: dict = Depends(get_current_user)):
    """Get audit log entries."""
    entries = await db.audit_log.find(
        {}, {"_id": 0}
    ).sort("timestamp", -1).to_list(limit)
    return entries
