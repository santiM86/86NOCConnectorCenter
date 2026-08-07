"""
Traffic Anomaly Detection (NDR-lite)
====================================
Rileva picchi anomali di traffico sulle porte switch usando i contatori SNMP
GIA' raccolti (switch_ports.rx_bps / tx_bps). Nessun DPI: solo comportamento sui
volumi. Un picco improvviso in USCITA (tx) puo' indicare exfiltration; picchi
anomali possono indicare scan/DoS/malware.

Metodo: baseline EWMA per porta (collection port_traffic_baseline). Durante un
periodo di warmup si impara soltanto; dopo, se il valore corrente supera la
baseline di un fattore (spike_factor) ED e' sopra una soglia minima assoluta
(floor_mbps), si genera un alert PER-TENANT (source_type=traffic_anomaly).

Config in db.settings "traffic_anomaly_config".
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from database import db
from alert_filter import insert_alert_if_emit

logger = logging.getLogger("traffic_anomaly")

SETTINGS_KEY = "traffic_anomaly_config"
DEFAULT_CONFIG = {
    "enabled": True,
    "spike_factor": 6.0,     # corrente > baseline * fattore
    "floor_mbps": 20,        # ignora sotto questa soglia assoluta
    "warmup": 5,             # campioni prima di iniziare ad allertare
    "severity": "warning",
}
_ALPHA = 0.3  # peso EWMA


async def get_config() -> dict:
    doc = await db.settings.find_one({"key": SETTINGS_KEY}, {"_id": 0, "value": 1})
    cfg = dict(DEFAULT_CONFIG)
    if doc and isinstance(doc.get("value"), dict):
        cfg.update(doc["value"])
    return cfg


async def set_config(patch: dict) -> dict:
    cfg = await get_config()
    if "enabled" in patch:
        cfg["enabled"] = bool(patch["enabled"])
    for k in ("spike_factor", "floor_mbps", "warmup"):
        if k in patch and patch[k] is not None:
            cfg[k] = type(DEFAULT_CONFIG[k])(patch[k])
    if patch.get("severity") in ("info", "warning", "high", "critical"):
        cfg["severity"] = patch["severity"]
    await db.settings.update_one(
        {"key": SETTINGS_KEY},
        {"$set": {"key": SETTINGS_KEY, "value": cfg, "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return cfg


async def scan_all() -> dict:
    cfg = await get_config()
    if not cfg.get("enabled", True):
        return {"skipped": True}

    spike = float(cfg["spike_factor"])
    floor_bps = float(cfg["floor_mbps"]) * 1_000_000
    warmup = int(cfg["warmup"])
    severity = cfg["severity"]

    ports = await db.switch_ports.find(
        {}, {"_id": 0, "client_id": 1, "local_ip": 1, "idx": 1, "name": 1,
             "rx_bps": 1, "tx_bps": 1, "oper": 1, "speed_mbps": 1},
    ).to_list(50000)

    checked = 0
    anomalies = 0
    for p in ports:
        cid = p.get("client_id")
        lip = p.get("local_ip")
        idx = p.get("idx")
        if not cid or not lip or idx is None:
            continue
        cur_rx = float(p.get("rx_bps", 0) or 0)
        cur_tx = float(p.get("tx_bps", 0) or 0)
        checked += 1

        key = {"client_id": cid, "local_ip": lip, "idx": idx}
        base = await db.port_traffic_baseline.find_one(key, {"_id": 0})
        samples = int(base.get("samples", 0)) if base else 0
        ewma_rx = float(base.get("ewma_rx", cur_rx)) if base else cur_rx
        ewma_tx = float(base.get("ewma_tx", cur_tx)) if base else cur_tx

        if samples >= warmup:
            direction = None
            cur_val = base_val = 0.0
            if cur_tx > floor_bps and cur_tx > ewma_tx * spike and ewma_tx > 0:
                direction, cur_val, base_val = "USCITA (tx)", cur_tx, ewma_tx
            elif cur_rx > floor_bps and cur_rx > ewma_rx * spike and ewma_rx > 0:
                direction, cur_val, base_val = "INGRESSO (rx)", cur_rx, ewma_rx
            if direction:
                created = await _emit_anomaly(cid, p, direction, cur_val, base_val, severity)
                if created:
                    anomalies += 1

        # aggiorna EWMA
        new_rx = _ALPHA * cur_rx + (1 - _ALPHA) * ewma_rx
        new_tx = _ALPHA * cur_tx + (1 - _ALPHA) * ewma_tx
        await db.port_traffic_baseline.update_one(
            key,
            {"$set": {**key, "name": p.get("name"), "ewma_rx": new_rx, "ewma_tx": new_tx,
                      "samples": min(samples + 1, 10_000),
                      "updated_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )

    if anomalies:
        logger.info(f"[traffic-anomaly] checked={checked} anomalies={anomalies}")
    return {"checked": checked, "anomalies": anomalies}


def _mbps(bps: float) -> str:
    return f"{bps / 1_000_000:.1f} Mbps"


async def _emit_anomaly(cid: str, port: dict, direction: str, cur: float, base: float, severity: str) -> bool:
    lip = port.get("local_ip")
    idx = port.get("idx")
    pname = port.get("name") or f"idx {idx}"
    dedup_key = f"{lip}:{idx}"

    existing = await db.alerts.find_one(
        {"client_id": cid, "source_type": "traffic_anomaly", "raw_data": dedup_key, "status": "active"},
        {"_id": 0, "id": 1},
    )
    factor = (cur / base) if base else 0
    title = f"Anomalia traffico su {lip} porta {pname}"
    msg = (f"Picco di traffico in {direction} sulla porta {pname} dello switch {lip}: "
           f"{_mbps(cur)} contro una media di {_mbps(base)} (~{factor:.0f}x). "
           f"Possibile exfiltration/scan/anomalia. Verifica il dispositivo collegato alla porta.")
    now_iso = datetime.now(timezone.utc).isoformat()
    if existing:
        await db.alerts.update_one({"id": existing["id"]}, {"$set": {"message": msg, "last_seen_at": now_iso}})
        return False

    alert_doc = {
        "id": str(uuid.uuid4()),
        "client_id": cid,
        "device_id": None,
        "device_ip": lip,
        "device_name": f"{lip} · {pname}",
        "device_type": "switch",
        "severity": severity,
        "source_type": "traffic_anomaly",
        "title": title,
        "message": msg,
        "raw_data": dedup_key,
        "status": "active",
        "acknowledged_by": None,
        "acknowledged_at": None,
        "resolved_at": None,
        "created_at": now_iso,
    }
    await insert_alert_if_emit(db, alert_doc)
    try:
        from deps import manager
        client = await db.clients.find_one({"id": cid}, {"_id": 0, "name": 1})
        payload = dict(alert_doc)
        payload["client_name"] = client["name"] if client else ""
        payload["ip_address"] = lip
        await manager.broadcast({"type": "new_alert", "alert": payload})
    except Exception as e:
        logger.warning(f"[traffic-anomaly] WS broadcast failed: {e}")
    try:
        import webpush as _wp
        await _wp.notify_new_alert(db, alert_doc)
    except Exception:
        pass
    return True


async def get_status() -> dict:
    cfg = await get_config()
    active = await db.alerts.count_documents({"source_type": "traffic_anomaly", "status": "active"})
    baselines = await db.port_traffic_baseline.count_documents({})
    return {"config": cfg, "active_alerts": active, "baselines": baselines}
