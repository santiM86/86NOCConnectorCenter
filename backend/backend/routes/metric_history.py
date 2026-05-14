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
            if nums:
                _add("cpu", max(nums))
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
    Aggrega da DUE collection:
      - metric_history (nuova, 30gg TTL, granulare per-metric)
      - device_metrics_history (legacy, 24h, un doc per poll con cpu_usage/memory_usage/temperature/ping_avg/active_sessions/vpn_throughput)
    """
    delta_map = {"1h": (1, 60), "6h": (6, 300), "24h": (24, 900), "7d": (168, 3600), "30d": (720, 14400)}
    if period not in delta_map:
        period = "24h"
    hours, bucket_sec = delta_map[period]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    # Legacy fallback: mapping metric name -> field name in device_metrics_history
    # il doc legacy ha `timestamp` come ISO-string, non `ts`. Convertiamo on-the-fly.
    legacy_field_map = {
        "cpu": "cpu_usage",
        "memory": "memory_usage",
        "temperature": "temperature",
        "response_ms": "ping_avg",
        "sessions": "active_sessions",
        "vpn_throughput": "vpn_throughput",
        "ping_avg": "ping_avg",
        "ping_jitter": "ping_jitter",
        "packet_loss": "packet_loss",
    }

    # Bucket points raccolti da entrambe le collection
    buckets: dict = {}

    def _accumulate(ts_dt, val):
        if val is None or ts_dt is None:
            return
        try:
            v = float(val)
        except (TypeError, ValueError):
            return
        # Align to bucket start
        epoch_ms = int(ts_dt.replace(tzinfo=timezone.utc).timestamp() * 1000) if ts_dt.tzinfo is None else int(ts_dt.timestamp() * 1000)
        bucket_ms = epoch_ms - (epoch_ms % (bucket_sec * 1000))
        b = buckets.setdefault(bucket_ms, {"sum": 0.0, "count": 0, "min": v, "max": v})
        b["sum"] += v
        b["count"] += 1
        if v < b["min"]:
            b["min"] = v
        if v > b["max"]:
            b["max"] = v

    # Source 1: new metric_history
    async for d in db.metric_history.find(
        {"device_ip": device_ip, "metric": metric, "ts": {"$gte": cutoff}},
        {"_id": 0, "ts": 1, "value": 1},
    ):
        _accumulate(d.get("ts"), d.get("value"))

    # Source 2: legacy device_metrics_history (timestamp è ISO string)
    legacy_field = legacy_field_map.get(metric)
    if legacy_field:
        cutoff_iso = cutoff.isoformat()
        async for d in db.device_metrics_history.find(
            {"device_ip": device_ip, "timestamp": {"$gte": cutoff_iso}},
            {"_id": 0, "timestamp": 1, legacy_field: 1},
        ):
            val = d.get(legacy_field)
            ts_s = d.get("timestamp")
            if val is None or not ts_s:
                continue
            try:
                ts_dt = datetime.fromisoformat(ts_s.replace("Z", "+00:00"))
            except Exception:
                continue
            _accumulate(ts_dt, val)

    # Build response ordered
    rows = []
    for bucket_ms in sorted(buckets.keys())[:500]:
        b = buckets[bucket_ms]
        rows.append({
            "ts": datetime.fromtimestamp(bucket_ms / 1000, tz=timezone.utc).isoformat(),
            "avg": round(b["sum"] / b["count"], 2) if b["count"] > 0 else None,
            "min": round(b["min"], 2),
            "max": round(b["max"], 2),
        })

    return {"device_ip": device_ip, "metric": metric, "period": period, "points": rows, "count": len(rows)}
