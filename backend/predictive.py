"""
Diagnosi predittiva — situazioni di "GUASTO IMMINENTE" (Argus Center)
=====================================================================
Rileva i problemi PRIMA che il dispositivo cada, combinando:
  - RAID degradato/crashed  (stato istantaneo vendor_metrics: raidStatus/systemStatus)
  - Trend TEMPERATURA e temperatura DISCHI in salita verso la soglia critica
  - Batteria UPS in esaurimento (carica bassa/in calo, autonomia residua bassa)

I trend sono calcolati sulla time-series `metric_history` (TTL 30gg) popolata dai
report device (cpu/memory/temperature/disk_temp_*/ups_*). Quando la storia non e'
sufficiente si applica un controllo "vicinanza alla soglia" sul valore corrente.

Emette alert con source_type `predictive_*` (deduplicati e auto-risolti), che il
Situation Engine classifica nel dominio "predictive" (peso alto) e usa per il
verdetto unico. Best-effort: non deve mai rompere il polling.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, List, Tuple, Dict

from alert_engine import _dispatch_notification, _mk_alert, get_config
from alert_filter import insert_alert_if_emit
from hardware_alerts import _to_float, _values, SENTINELS

logger = logging.getLogger("predictive")

# Synology RAID-STATUS-MIB raidStatus: 11=Degrade, 12=Crashed.
_RAID_BAD: Dict[int, str] = {11: "degradato", 12: "in crash"}
# Synology systemStatus: 2=Failed.
_SYS_BAD: Dict[int, str] = {2: "guasto di sistema"}

DEFAULT_TEMP_CRIT = 78.0        # °C chassis/CPU
DEFAULT_DISK_TEMP_CRIT = 60.0   # °C disco (HDD/SSD)
TREND_WINDOW_H = 6              # ore di storia usate per il trend
MIN_POINTS = 4                  # punti minimi per fidarsi del trend
MIN_SPAN_MIN = 20              # minuti minimi coperti dalla storia


# ---------------------------------------------------------------------------
# Emit / resolve (parametrizzati per source_type predittivo)
# ---------------------------------------------------------------------------
async def _emit(db, cfg, *, source_type: str, dedup_key: str, client_id: str,
                client_name: str, device_name: str, device_ip: str, device_type: str,
                severity: str, title: str, message: str) -> None:
    active = await db.alerts.find_one({"dedup_key": dedup_key, "status": "active"}, {"_id": 0})
    if active:
        if active.get("severity") != severity or active.get("message") != message:
            await db.alerts.update_one(
                {"id": active["id"]},
                {"$set": {"severity": severity, "title": title, "message": message}},
            )
            try:
                await _dispatch_notification(db, cfg, {**active, "severity": severity, "title": title, "message": message})
            except Exception:  # noqa: BLE001
                pass
        return
    alert = _mk_alert(client_id, client_name, device_name, device_ip,
                      device_type, severity, source_type, title, message)
    alert["dedup_key"] = dedup_key
    try:
        if await insert_alert_if_emit(db, alert):
            await _dispatch_notification(db, cfg, alert)
    except Exception as e:  # noqa: BLE001
        logger.debug("predictive emit failed key=%s err=%s", dedup_key, e)


async def _resolve(db, cfg, dedup_key: str, recovery_msg: str) -> None:
    active = await db.alerts.find_one({"dedup_key": dedup_key, "status": "active"}, {"_id": 0})
    if not active:
        return
    now = datetime.now(timezone.utc).isoformat()
    await db.alerts.update_one({"id": active["id"]},
                               {"$set": {"status": "resolved", "resolved_at": now}})
    rec = {**active, "status": "resolved", "resolved_at": now, "severity": "low",
           "title": "Ripristino: " + active.get("title", ""), "message": recovery_msg}
    try:
        await _dispatch_notification(db, cfg, rec)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Time-series helpers
# ---------------------------------------------------------------------------
async def _series(db, client_id: str, device_ip: str, metric: str,
                  hours: int = TREND_WINDOW_H) -> List[Tuple[datetime, float]]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    q = {"device_ip": device_ip, "metric": metric, "ts": {"$gte": cutoff}}
    if client_id:
        q["client_id"] = client_id
    pts: List[Tuple[datetime, float]] = []
    async for d in db.metric_history.find(q, {"_id": 0, "ts": 1, "value": 1}).sort("ts", 1):
        ts = d.get("ts")
        v = d.get("value")
        if isinstance(ts, datetime) and isinstance(v, (int, float)):
            pts.append((ts, float(v)))
    return pts


def _slope_per_hour(points: List[Tuple[datetime, float]]) -> Optional[float]:
    """Regressione lineare (minimi quadrati): pendenza in unita'/ora."""
    if len(points) < 2:
        return None
    t0 = points[0][0]
    xs = [(t - t0).total_seconds() / 3600.0 for t, _ in points]
    ys = [v for _, v in points]
    n = len(xs)
    sx, sy = sum(xs), sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-9:
        return None
    return (n * sxy - sx * sy) / denom


def _span_minutes(points: List[Tuple[datetime, float]]) -> float:
    if len(points) < 2:
        return 0.0
    return (points[-1][0] - points[0][0]).total_seconds() / 60.0


def _eta_hours(current: float, slope: float, target: float) -> Optional[float]:
    if slope is None or slope <= 0 or current >= target:
        return 0.0 if current >= target else None
    return (target - current) / slope


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------
async def _ctx(db, client_id: str, device_ip: str, sys_name: Optional[str]):
    device_name, device_type, profile_key = sys_name or device_ip, "", None
    try:
        md = await db.managed_devices.find_one(
            {"client_id": client_id, "ip": device_ip},
            {"_id": 0, "hostname": 1, "name": 1, "device_name": 1, "device_type": 1, "profile_key": 1},
        )
        if md:
            device_name = md.get("hostname") or md.get("name") or md.get("device_name") or device_name
            device_type = md.get("device_type") or ""
            profile_key = md.get("profile_key")
    except Exception:  # noqa: BLE001
        pass
    thresholds: Dict[str, Any] = {}
    if profile_key:
        try:
            from device_profiles import get_profile
            thresholds = (get_profile(profile_key) or {}).get("thresholds") or {}
        except Exception:  # noqa: BLE001
            pass
    client_name = ""
    try:
        c = await db.clients.find_one({"id": client_id}, {"_id": 0, "name": 1})
        if c:
            client_name = c.get("name") or ""
    except Exception:  # noqa: BLE001
        pass
    return device_name, device_type, thresholds, client_name


def _threshold(thresholds: dict, *keys, default=None):
    for k in keys:
        v = thresholds.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    return default


# ---------------------------------------------------------------------------
# Valutazione predittiva
# ---------------------------------------------------------------------------
async def evaluate_predictive_alerts(db, *, client_id: str, device_ip: str,
                                     vendor_metrics: dict,
                                     sys_name: Optional[str] = None) -> None:
    if not isinstance(vendor_metrics, dict) or not vendor_metrics:
        return
    cfg = await get_config(db)
    device_name, device_type, thresholds, client_name = await _ctx(db, client_id, device_ip, sys_name)
    base = dict(db=db, cfg=cfg, client_id=client_id, client_name=client_name,
                device_name=device_name, device_ip=device_ip, device_type=device_type)

    # ---- RAID degradato / systemStatus failed (stato istantaneo) ----
    dk = f"{client_id}:{device_ip}:predictive_raid"
    raid_bad_label = None
    for v in _values(vendor_metrics.get("raidStatus")):
        code = int(v)
        if code in _RAID_BAD:
            raid_bad_label = f"RAID {_RAID_BAD[code]}"
            break
    if not raid_bad_label:
        for v in _values(vendor_metrics.get("systemStatus")):
            if int(v) in _SYS_BAD:
                raid_bad_label = _SYS_BAD[int(v)].capitalize()
                break
    if raid_bad_label:
        await _emit(**base, source_type="predictive_raid", dedup_key=dk, severity="critical",
                    title=f"GUASTO IMMINENTE: {raid_bad_label} su {device_name}",
                    message=(f"Volume/array in stato «{raid_bad_label}» su {device_name} ({device_ip}). "
                             f"Rischio ELEVATO di perdita dati al prossimo guasto disco: "
                             f"verifica lo stato dei dischi e avvia la ricostruzione/sostituzione."))
    else:
        await _resolve(db, cfg, dk, f"RAID/array tornato normale su {device_name} ({device_ip}).")

    # ---- Trend TEMPERATURA chassis/CPU ----
    temp_crit = _threshold(thresholds, "temp_crit_c", "inlet_temp_crit_c", "cpu_temp_crit_c",
                           default=DEFAULT_TEMP_CRIT)
    temp_warn = _threshold(thresholds, "temp_warn_c", "inlet_temp_warn_c", "cpu_temp_warn_c",
                           default=temp_crit - 10)
    await _eval_temp_trend(base, metric="temperature", crit=temp_crit, warn=temp_warn,
                           label="Temperatura", unit="°C")

    # ---- Trend TEMPERATURA DISCHI ----
    disk_metrics = set()
    dt = vendor_metrics.get("diskTemperature")
    if isinstance(dt, dict):
        for idx in dt.keys():
            disk_metrics.add(f"disk_temp_{idx}")
    for m in await db.metric_history.distinct("metric", {"client_id": client_id, "device_ip": device_ip}):
        if isinstance(m, str) and m.startswith("disk_temp_"):
            disk_metrics.add(m)
    for m in disk_metrics:
        idx = m.replace("disk_temp_", "")
        await _eval_temp_trend(base, metric=m, crit=DEFAULT_DISK_TEMP_CRIT,
                               warn=DEFAULT_DISK_TEMP_CRIT - 8,
                               label=f"Temperatura disco #{idx}", unit="°C", key_suffix=m)

    # ---- Batteria UPS ----
    await _eval_ups(base, vendor_metrics)


async def _eval_temp_trend(base, *, metric: str, crit: float, warn: float,
                           label: str, unit: str, key_suffix: Optional[str] = None) -> None:
    db, cfg = base["db"], base["cfg"]
    dk = f"{base['client_id']}:{base['device_ip']}:predictive_{key_suffix or 'temp'}"
    pts = await _series(db, base["client_id"], base["device_ip"], metric)
    valid = [(t, v) for t, v in pts if int(v) not in SENTINELS and -40 < v <= 150]
    if not valid:
        await _resolve(db, cfg, dk, f"{label} senza dati anomali su {base['device_name']}.")
        return
    current = valid[-1][1]
    slope = _slope_per_hour(valid)
    enough = len(valid) >= MIN_POINTS and _span_minutes(valid) >= MIN_SPAN_MIN

    severity = None
    detail = ""
    if enough and slope is not None and slope > 0.5 and current > warn:
        eta = _eta_hours(current, slope, crit)
        if eta is not None and eta <= TREND_WINDOW_H:
            severity = "critical" if eta <= 1 else "high"
            detail = (f"in salita di {slope:.1f}{unit}/h (ora {current:.0f}{unit}); "
                      f"raggiungera' la soglia critica {crit:.0f}{unit} tra ~{_fmt_eta(eta)}.")
    if severity is None and current >= (crit - 5) and current > warn:
        # vicinanza alla soglia critica anche senza trend affidabile
        severity = "high"
        detail = f"a {current:.0f}{unit}, molto vicina alla soglia critica {crit:.0f}{unit}."

    if severity:
        await _emit(**base, source_type=f"predictive_{key_suffix or 'temp'}", dedup_key=dk,
                    severity=severity,
                    title=f"GUASTO IMMINENTE: {label} su {base['device_name']}",
                    message=(f"{label} {detail} Interveni sul raffreddamento/ventilazione di "
                             f"{base['device_name']} ({base['device_ip']}) prima del blocco termico."))
    else:
        await _resolve(db, cfg, dk, f"{label} stabile ({current:.0f}{unit}) su {base['device_name']}.")


async def _eval_ups(base, vendor_metrics: dict) -> None:
    db, cfg = base["db"], base["cfg"]
    dk = f"{base['client_id']}:{base['device_ip']}:predictive_ups"

    def _first(key):
        vals = _values(vendor_metrics.get(key))
        return vals[0] if vals else None

    charge = _first("upsEstimatedChargeRemaining")
    runtime = _first("upsEstimatedMinutesRemaining")
    load = _first("upsOutputPercentLoad")
    if charge is None and runtime is None:
        # nessuna metrica UPS presente -> risolvi eventuale alert e esci
        await _resolve(db, cfg, dk, f"Nessuna anomalia UPS su {base['device_name']}.")
        return

    severity = None
    parts: List[str] = []
    if runtime is not None and runtime <= 5:
        severity = "critical"; parts.append(f"autonomia residua ~{runtime:.0f} min")
    if charge is not None and charge <= 20:
        severity = "critical"; parts.append(f"carica batteria {charge:.0f}%")
    if severity is None:
        # trend carica in discesa (su batteria / batteria che degrada)
        pts = await _series(db, base["client_id"], base["device_ip"], "ups_charge_pct")
        slope = _slope_per_hour(pts) if len(pts) >= MIN_POINTS else None
        if charge is not None and charge <= 60 and slope is not None and slope < -1:
            severity = "high"
            parts.append(f"carica {charge:.0f}% in calo ({slope:.0f}%/h)")
        elif charge is not None and charge < 100 and runtime is not None and runtime <= 15:
            severity = "high"
            parts.append(f"su batteria (carica {charge:.0f}%, autonomia ~{runtime:.0f} min)")

    if severity:
        if load is not None:
            parts.append(f"carico {load:.0f}%")
        await _emit(**base, source_type="predictive_ups", dedup_key=dk, severity=severity,
                    title=f"GUASTO IMMINENTE: UPS in esaurimento su {base['device_name']}",
                    message=(f"UPS di {base['device_name']} ({base['device_ip']}): "
                             f"{', '.join(parts)}. Rischio spegnimento non pianificato: "
                             f"verifica alimentazione di rete e stato batteria."))
    else:
        await _resolve(db, cfg, dk, f"UPS stabile su {base['device_name']}.")


def _fmt_eta(hours: float) -> str:
    if hours <= 0:
        return "adesso"
    if hours < 1:
        return f"{int(round(hours * 60))} min"
    return f"{hours:.1f} h"
