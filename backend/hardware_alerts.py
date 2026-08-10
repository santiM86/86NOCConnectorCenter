"""Alert proattivi hardware da metriche SNMP vendor.

Valuta i valori raccolti dall'Agent Go (v4.30+) e salvati in
`device_poll_status.vendor_metrics` contro le soglie definite nel profilo
device (`device_profiles/__init__.py` -> `thresholds`) ed emette alert
WARNING (severity "high") / CRITICAL (severity "critical") quando i valori
superano le soglie o quando lo stato di ventole/alimentatori indica un guasto.

Comportamento:
- 1 solo alert ATTIVO per (client_id, device_ip, metrica): dedup via campo
  `dedup_key` in `db.alerts`. Nessun doppione ad ogni poll (~60s).
- Quando la metrica rientra sotto soglia (o il guasto rientra) l'alert attivo
  viene AUTO-RISOLTO (status "resolved") con nota di ripristino.
- Escalation: se un WARNING attivo passa a CRITICAL (o viceversa) la severity
  dell'alert esistente viene aggiornata e la notifica ri-dispatchata.
- Notifiche via dispatcher esistente (Telegram/WebPush) in alert_engine.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from alert_engine import _dispatch_notification, _mk_alert, get_config
from alert_filter import insert_alert_if_emit

logger = logging.getLogger("hardware_alerts")

SOURCE_TYPE = "hardware_snmp"

# ---------------------------------------------------------------------------
# Regole stato Fan/PSU per profilo (conservative: alert SOLO su guasto certo).
# `healthy` = set di valori numerici da considerare sani o non-applicabili
# (es. H3C notSupported(1)/normal(2), Cisco normal(1)/notPresent(5)).
# Qualsiasi valore FUORI da `healthy` viene trattato come guasto fisico.
# I profili NON presenti in mappa NON generano alert fan/psu (zero falsi
# positivi finche' l'enum del vendor non e' verificato).
# ---------------------------------------------------------------------------
FAN_PSU_HEALTHY_STATES: dict[str, set[int]] = {
    # HH3C-ENTITY-EXT-MIB hh3cEntityExtErrorStatus: notSupported(1), normal(2);
    # guasti espliciti fanError(41)/psuError(51)/altri > 2.
    "hpe_comware": {1, 2},
    # CISCO-ENVMON-MIB: normal(1), warning(2), critical(3), shutdown(4),
    # notPresent(5), notFunctioning(6). Sani = normal + notPresent.
    "cisco_catalyst": {1, 5},
}


def _to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        m = re.search(r"-?\d+(?:\.\d+)?", v.replace(",", "."))
        if m:
            try:
                return float(m.group(0))
            except ValueError:
                return None
    return None


def _values(metric_val: Any) -> list[float]:
    """Normalizza uno scalare o un dict {index: value} in lista di float."""
    out: list[float] = []
    if isinstance(metric_val, dict):
        for v in metric_val.values():
            f = _to_float(v)
            if f is not None:
                out.append(f)
    else:
        f = _to_float(metric_val)
        if f is not None:
            out.append(f)
    return out


def _classify(key: str) -> Optional[str]:
    k = (key or "").lower()
    if not k:
        return None
    # stato ventole / alimentatori (prima di cpu/mem/temp per evitare collisioni)
    if "fan" in k and ("state" in k or "status" in k):
        return "fan"
    if ("psu" in k or "power" in k or "supply" in k) and ("state" in k or "status" in k):
        return "psu"
    if "temp" in k and "template" not in k and ("state" not in k and "status" not in k):
        return "temp"
    if "cpu" in k and any(t in k for t in ("usage", "util", "load", "total", "percent")):
        return "cpu"
    if "mem" in k and ("usage" in k or "util" in k):
        return "mem"
    return None


def _threshold(thresholds: dict, *keys: str) -> Optional[float]:
    for key in keys:
        if key in thresholds:
            f = _to_float(thresholds[key])
            if f is not None:
                return f
    return None


async def _resolve_alert(db, cfg, dedup_key: str, recovery_msg: str) -> None:
    active = await db.alerts.find_one({"dedup_key": dedup_key, "status": "active"}, {"_id": 0})
    if not active:
        return
    now = datetime.now(timezone.utc).isoformat()
    await db.alerts.update_one(
        {"id": active["id"]},
        {"$set": {"status": "resolved", "resolved_at": now}},
    )
    rec = dict(active)
    rec["status"] = "resolved"
    rec["resolved_at"] = now
    rec["title"] = "Ripristino: " + active.get("title", "")
    rec["message"] = recovery_msg
    rec["severity"] = "low"
    try:
        await _dispatch_notification(db, cfg, rec)
    except Exception:  # noqa: BLE001
        pass


async def _emit_or_update(db, cfg, *, client_id: str, client_name: str,
                          device_name: str, device_ip: str, device_type: str,
                          dedup_key: str, severity: str, title: str,
                          message: str) -> None:
    active = await db.alerts.find_one({"dedup_key": dedup_key, "status": "active"}, {"_id": 0})
    if active:
        # Aggiorna solo se cambia severity o messaggio (escalation/variazione)
        if active.get("severity") != severity or active.get("message") != message:
            await db.alerts.update_one(
                {"id": active["id"]},
                {"$set": {"severity": severity, "title": title, "message": message}},
            )
            upd = {**active, "severity": severity, "title": title, "message": message}
            try:
                await _dispatch_notification(db, cfg, upd)
            except Exception:  # noqa: BLE001
                pass
        return
    alert = _mk_alert(client_id, client_name, device_name, device_ip,
                      device_type, severity, SOURCE_TYPE, title, message)
    alert["dedup_key"] = dedup_key
    try:
        inserted = await insert_alert_if_emit(db, alert)
        if inserted:
            await _dispatch_notification(db, cfg, alert)
    except Exception as e:  # noqa: BLE001
        logger.debug("hardware alert emit failed key=%s err=%s", dedup_key, e)


def _eval_percent(vm: dict, kind: str, warn: Optional[float], crit: Optional[float]):
    """Ritorna (severity|None, value|None) per metriche percentuali (cpu/mem)."""
    peak: Optional[float] = None
    for key, val in vm.items():
        if _classify(key) != kind:
            continue
        for v in _values(val):
            if peak is None or v > peak:
                peak = v
    if peak is None:
        return None, None
    if crit is not None and peak >= crit:
        return "critical", peak
    if warn is not None and peak >= warn:
        return "high", peak
    return None, peak


async def evaluate_hardware_alerts(db, *, client_id: str, device_ip: str,
                                   vendor_metrics: dict,
                                   profile_key: Optional[str] = None,
                                   sys_name: Optional[str] = None) -> None:
    """Valuta le vendor_metrics contro le soglie del profilo ed emette/risolve
    gli alert hardware. Chiamata dal bridge SNMP solo se il device e' reachable
    e ha vendor_metrics."""
    if not isinstance(vendor_metrics, dict) or not vendor_metrics:
        return
    try:
        from device_profiles import get_profile
    except Exception:  # noqa: BLE001
        return

    # Contesto per l'alert (client + device name/type + profile_key)
    device_name = sys_name or ""
    device_type = ""
    try:
        mdoc = await db.managed_devices.find_one(
            {"client_id": client_id, "ip": device_ip},
            {"_id": 0, "hostname": 1, "name": 1, "device_name": 1,
             "device_type": 1, "profile_key": 1},
        )
        if mdoc:
            device_name = mdoc.get("hostname") or mdoc.get("name") or mdoc.get("device_name") or device_name
            device_type = mdoc.get("device_type") or ""
            if not profile_key:
                profile_key = mdoc.get("profile_key")
    except Exception:  # noqa: BLE001
        pass
    if not profile_key:
        try:
            ps = await db.device_poll_status.find_one(
                {"client_id": client_id, "device_ip": device_ip},
                {"_id": 0, "profile_key": 1},
            )
            if ps:
                profile_key = ps.get("profile_key")
        except Exception:  # noqa: BLE001
            pass
    if not profile_key:
        return
    prof = get_profile(profile_key) or {}
    thresholds = prof.get("thresholds") or {}
    if not thresholds:
        return

    cfg = await get_config(db)
    client_name = ""
    try:
        cdoc = await db.clients.find_one({"id": client_id}, {"_id": 0, "name": 1})
        if cdoc:
            client_name = cdoc.get("name") or ""
    except Exception:  # noqa: BLE001
        pass
    device_name = device_name or device_ip

    # ---- CPU % ----
    sev, val = _eval_percent(vendor_metrics, "cpu",
                             _threshold(thresholds, "cpu_warn_pct"),
                             _threshold(thresholds, "cpu_crit_pct"))
    dk = f"{client_id}:{device_ip}:cpu"
    if sev:
        lbl = "critica" if sev == "critical" else "elevata"
        await _emit_or_update(
            db, cfg, client_id=client_id, client_name=client_name,
            device_name=device_name, device_ip=device_ip, device_type=device_type,
            dedup_key=dk, severity=sev,
            title=f"CPU {lbl} su {device_name}",
            message=f"Utilizzo CPU al {val:.0f}% (soglia {sev.upper()} superata) su {device_name} ({device_ip}).",
        )
    elif val is not None:
        await _resolve_alert(db, cfg, dk, f"CPU rientrata al {val:.0f}% su {device_name} ({device_ip}).")

    # ---- RAM % ----
    sev, val = _eval_percent(vendor_metrics, "mem",
                             _threshold(thresholds, "mem_warn_pct"),
                             _threshold(thresholds, "mem_crit_pct"))
    dk = f"{client_id}:{device_ip}:mem"
    if sev:
        lbl = "critica" if sev == "critical" else "elevata"
        await _emit_or_update(
            db, cfg, client_id=client_id, client_name=client_name,
            device_name=device_name, device_ip=device_ip, device_type=device_type,
            dedup_key=dk, severity=sev,
            title=f"Memoria {lbl} su {device_name}",
            message=f"Utilizzo memoria al {val:.0f}% (soglia {sev.upper()} superata) su {device_name} ({device_ip}).",
        )
    elif val is not None:
        await _resolve_alert(db, cfg, dk, f"Memoria rientrata al {val:.0f}% su {device_name} ({device_ip}).")

    # ---- Temperatura (C) ----
    sev, val = _eval_percent(
        vendor_metrics, "temp",
        _threshold(thresholds, "temp_warn_c", "inlet_temp_warn_c", "cpu_temp_warn_c"),
        _threshold(thresholds, "temp_crit_c", "inlet_temp_crit_c", "cpu_temp_crit_c"),
    )
    dk = f"{client_id}:{device_ip}:temp"
    if sev:
        lbl = "critica" if sev == "critical" else "elevata"
        await _emit_or_update(
            db, cfg, client_id=client_id, client_name=client_name,
            device_name=device_name, device_ip=device_ip, device_type=device_type,
            dedup_key=dk, severity=sev,
            title=f"Temperatura {lbl} su {device_name}",
            message=f"Temperatura a {val:.0f}\u00b0C (soglia {sev.upper()} superata) su {device_name} ({device_ip}).",
        )
    elif val is not None:
        await _resolve_alert(db, cfg, dk, f"Temperatura rientrata a {val:.0f}\u00b0C su {device_name} ({device_ip}).")

    # ---- Ventole / Alimentatori (solo profili con enum verificato) ----
    healthy = FAN_PSU_HEALTHY_STATES.get(profile_key)
    if healthy is not None:
        for kind, label in (("fan", "ventola"), ("psu", "alimentatore")):
            faulty: list[str] = []
            for key, mv in vendor_metrics.items():
                if _classify(key) != kind:
                    continue
                if isinstance(mv, dict):
                    for idx, v in mv.items():
                        f = _to_float(v)
                        if f is not None and int(f) not in healthy:
                            faulty.append(f"#{idx}={int(f)}")
                else:
                    f = _to_float(mv)
                    if f is not None and int(f) not in healthy:
                        faulty.append(f"={int(f)}")
            dk = f"{client_id}:{device_ip}:{kind}_fault"
            if faulty:
                await _emit_or_update(
                    db, cfg, client_id=client_id, client_name=client_name,
                    device_name=device_name, device_ip=device_ip, device_type=device_type,
                    dedup_key=dk, severity="critical",
                    title=f"Guasto {label} su {device_name}",
                    message=(f"Stato {label}/e anomalo su {device_name} ({device_ip}): "
                             f"{', '.join(faulty)}. Verifica hardware necessaria."),
                )
            else:
                await _resolve_alert(db, cfg, dk,
                                     f"{label.capitalize()}/e tornata/e normale/i su {device_name} ({device_ip}).")
