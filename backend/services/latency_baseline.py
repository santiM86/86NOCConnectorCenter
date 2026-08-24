"""
Dynamic Threshold — anomalia di latenza su baseline storica.

Invece di una soglia fissa (es. ping > 100ms), confronta la latenza CORRENTE di
ogni device con la sua NORMALITA' storica per la stessa FASCIA ORARIA (hour of
day) calcolata su `metrics_history` degli ultimi giorni. Un alert scatta solo
quando la latenza devia molto dalla baseline (media + K*sigma), riducendo i
falsi positivi (es. link naturalmente lento la mattina).

Config (db.settings key "dynamic_threshold_config"):
  enabled, lookback_days, min_samples, sigma, floor_ms, hard_ms
Alert: source_type = "latency_anomaly" (auto-resolve quando rientra).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta

from database import db
from alert_filter import insert_alert_if_emit

logger = logging.getLogger("latency_baseline")

SETTINGS_KEY = "dynamic_threshold_config"
DEFAULT_CONFIG = {
    "enabled": True,
    "lookback_days": 14,
    "min_samples": 20,
    "sigma": 3.0,
    "floor_ms": 20.0,   # deviazione minima assoluta per allertare
    "hard_ms": 400.0,   # oltre questa latenza allerta comunque (se baseline nota)
}


async def get_config() -> dict:
    doc = await db.settings.find_one({"key": SETTINGS_KEY}, {"_id": 0, "value": 1})
    cfg = dict(DEFAULT_CONFIG)
    if doc and isinstance(doc.get("value"), dict):
        cfg.update(doc["value"])
    return cfg


async def set_config(patch: dict) -> dict:
    cfg = await get_config()
    for k in DEFAULT_CONFIG:
        if k in patch and patch[k] is not None:
            cfg[k] = patch[k]
    await db.settings.update_one(
        {"key": SETTINGS_KEY},
        {"$set": {"key": SETTINGS_KEY, "value": cfg,
                  "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return cfg


async def _baseline_map(hh: int, cfg: dict) -> dict:
    """Baseline (avg, std, count) di ping_ms per (client_id, device_ip) nella
    fascia oraria `hh` sugli ultimi lookback_days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=int(cfg["lookback_days"]))).isoformat()
    pipeline = [
        {"$match": {
            "timestamp": {"$gte": cutoff},
            "ping_ms": {"$ne": None, "$gt": 0},
            "hour_bucket": {"$regex": f"T{hh:02d}:"},
        }},
        {"$group": {
            "_id": {"client_id": "$client_id", "device_ip": "$device_ip"},
            "avg": {"$avg": "$ping_ms"},
            "std": {"$stdDevPop": "$ping_ms"},
            "count": {"$sum": 1},
            "device_name": {"$first": "$device_name"},
        }},
    ]
    out = {}
    try:
        async for r in db.metrics_history.aggregate(pipeline):
            k = (r["_id"].get("client_id"), r["_id"].get("device_ip"))
            out[k] = r
    except Exception as e:
        logger.debug("baseline aggregate failed: %s", e)
    return out


async def scan_all() -> dict:
    cfg = await get_config()
    if not cfg.get("enabled", True):
        return {"skipped": True}
    now = datetime.now(timezone.utc)
    hh = now.hour
    baseline = await _baseline_map(hh, cfg)
    if not baseline:
        return {"anomalies": 0, "checked": 0, "note": "no_baseline"}

    sigma = float(cfg["sigma"]); floor_ms = float(cfg["floor_ms"])
    min_samples = int(cfg["min_samples"]); hard_ms = float(cfg["hard_ms"])

    client_names = {c["id"]: c["name"] for c in
                    await db.clients.find({}, {"_id": 0, "id": 1, "name": 1}).to_list(1000)}

    checked = 0
    anomalies = 0
    async for d in db.device_poll_status.find(
        {"reachable": True, "ping_ms": {"$ne": None, "$gt": 0}},
        {"_id": 0, "client_id": 1, "device_ip": 1, "device_name": 1, "ping_ms": 1},
    ):
        cid = d.get("client_id"); ip = d.get("device_ip")
        base = baseline.get((cid, ip))
        if not base or base["count"] < min_samples:
            continue
        checked += 1
        cur = float(d.get("ping_ms") or 0)
        avg = float(base.get("avg") or 0)
        std = float(base.get("std") or 0)
        threshold = avg + sigma * std
        is_anom = (cur > threshold and (cur - avg) >= floor_ms) or (cur >= hard_ms and cur > avg * 1.5)
        dedup = f"latanom:{cid}:{ip}"
        existing = await db.alerts.find_one(
            {"dedup_key": dedup, "status": "active"}, {"_id": 0, "id": 1})
        if is_anom:
            if existing:
                continue
            name = d.get("device_name") or base.get("device_name") or ip
            cname = client_names.get(cid, "")
            alert = {
                "id": str(uuid.uuid4()),
                "client_id": cid,
                "device_ip": ip,
                "device_name": name,
                "device_type": "network",
                "severity": "medium",
                "source_type": "latency_anomaly",
                "dedup_key": dedup,
                "title": f"Latenza anomala: {name} — {cur:.0f}ms",
                "message": (f"Cliente {cname}: latenza {cur:.0f}ms su '{name}' ({ip}), molto sopra "
                            f"la norma per questa fascia oraria (media {avg:.0f}ms, dev. std {std:.0f}ms, "
                            f"soglia {threshold:.0f}ms su {base['count']} campioni). Possibile congestione, "
                            f"saturazione del link o problema sul percorso."),
                "status": "active",
                "created_at": now.isoformat(),
                "baseline_avg_ms": round(avg, 1),
                "baseline_std_ms": round(std, 1),
                "current_ms": round(cur, 1),
            }
            if await insert_alert_if_emit(db, alert):
                anomalies += 1
                try:
                    from alert_engine import notify_alert_telegram
                    await notify_alert_telegram(db, alert)
                except Exception:
                    pass
        elif existing:
            # rientrato nella norma → risolvi
            await db.alerts.update_one(
                {"id": existing["id"]},
                {"$set": {"status": "resolved", "resolved_at": now.isoformat(),
                          "resolution_note": f"Latenza rientrata ({cur:.0f}ms)."}})
    if anomalies:
        logger.info("[lat-anomaly] checked=%s anomalies=%s", checked, anomalies)
    return {"checked": checked, "anomalies": anomalies}
