"""
Metric History — time-series storage for device metrics.

Collection `metric_history` con TTL 30 giorni (auto-delete).
Ingested dal device-report endpoint per cpu_usage/memory_usage/temperature/vendor_metrics.
Aggregato via $bucket per line chart frontend.
"""
from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timezone, timedelta
from typing import Optional
from database import db
from deps import get_current_user

router = APIRouter(prefix="/api", tags=["metric-history"])

METRIC_TTL_DAYS = 30


async def ensure_index():
    """Create TTL index on ts field (30 days) — idempotent, one-off."""
    try:
        await db.metric_history.create_index("ts", expireAfterSeconds=METRIC_TTL_DAYS * 86400)
        await db.metric_history.create_index([("device_ip", 1), ("metric", 1), ("ts", -1)])
    except Exception:
        pass


async def record_metrics(client_id: str, device_ip: str, dev: dict) -> None:
    """Append point-in-time metrics to metric_history for later trend graphs.
    Called from _check_device_thresholds on every device-report.
    """
    now = datetime.now(timezone.utc)
    points = []

    def _add(metric_name: str, value):
        if value is None:
            return
        try:
            v = float(value)
            if -1000 <= v <= 100000:
                points.append({
                    "client_id": client_id,
                    "device_ip": device_ip,
                    "metric": metric_name,
                    "value": v,
                    "ts": now,
                })
        except (ValueError, TypeError):
            pass

    _add("cpu", dev.get("cpu_usage"))
    _add("memory", dev.get("memory_usage"))
    _add("temperature", dev.get("temperature"))
    _add("response_ms", dev.get("response_time_ms"))

    vm = dev.get("vendor_metrics") or {}
    # Synology
    _add("temperature", vm.get("temperatureC"))
    for idx, t in (vm.get("diskTemperature") or {}).items():
        _add(f"disk_temp_{idx}", t)
    # UPS
    _add("ups_charge_pct", vm.get("upsEstimatedChargeRemaining"))
    _add("ups_runtime_min", vm.get("upsEstimatedMinutesRemaining"))
    _add("ups_load_pct", vm.get("upsOutputPercentLoad"))
    # Fortinet
    _add("cpu", vm.get("fgSysCpuUsage"))
    _add("memory", vm.get("fgSysMemUsage"))
    _add("sessions", vm.get("fgSysSesCount"))
    # HPE Comware / Cisco / MikroTik / Zyxel (scalar or table max)
    for k in ["h3cEntityExtCpuUsage", "cpuUtil", "cpuUsage", "cpuUtilization", "cpmCPUTotal5min", "zyxelCpuCurrent", "zyxelCpu5min"]:
        v = vm.get(k)
        if isinstance(v, dict):
            nums = [x for x in v.values() if isinstance(x, (int, float))]
            if nums: _add("cpu", max(nums))
        elif v is not None:
            _add("cpu", v)

    if points:
        try:
            await db.metric_history.insert_many(points, ordered=False)
        except Exception:
            pass


@router.get("/devices/by-ip/{device_ip}/metrics")
async def get_metrics_history(
    device_ip: str,
    metric: str = "cpu",
    period: str = "24h",
    current_user: dict = Depends(get_current_user),
):
    """Returns aggregated time-series for a metric.
    period: 1h | 6h | 24h | 7d | 30d
    """
    delta_map = {"1h": (1, 60), "6h": (6, 300), "24h": (24, 900), "7d": (168, 3600), "30d": (720, 14400)}
    if period not in delta_map:
        period = "24h"
    hours, bucket_sec = delta_map[period]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    pipeline = [
        {"$match": {"device_ip": device_ip, "metric": metric, "ts": {"$gte": cutoff}}},
        {"$group": {
            "_id": {
                "$toDate": {
                    "$subtract": [
                        {"$toLong": "$ts"},
                        {"$mod": [{"$toLong": "$ts"}, bucket_sec * 1000]}
                    ]
                }
            },
            "avg": {"$avg": "$value"},
            "min": {"$min": "$value"},
            "max": {"$max": "$value"},
            "count": {"$sum": 1},
        }},
        {"$sort": {"_id": 1}},
        {"$limit": 500},
    ]
    rows = []
    async for r in db.metric_history.aggregate(pipeline):
        rows.append({
            "ts": r["_id"].isoformat() if hasattr(r["_id"], "isoformat") else str(r["_id"]),
            "avg": round(r["avg"], 2) if r.get("avg") is not None else None,
            "min": round(r["min"], 2) if r.get("min") is not None else None,
            "max": round(r["max"], 2) if r.get("max") is not None else None,
        })
    return {"device_ip": device_ip, "metric": metric, "period": period, "points": rows, "count": len(rows)}
