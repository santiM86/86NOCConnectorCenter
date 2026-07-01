"""
Auto-Dispatch Cron — stile Park Place ParkView Dispatch.

Chiude il cerchio detect → predict → ticket:
- Scansiona giornalmente i lifecycle_records: se risk_band="high" e non c'è già
  un incident aperto per quel device, crea un incident "Hardware Risk Alert".
- Scansiona ilo_telemetry: se predictive window <=72h, crea incident
  "Predictive Failure Warning".
- Deduplica su device_ip per evitare spam.

Esecuzione:
- Ogni 6h (APScheduler) + endpoint manual run POST /api/intel/auto-dispatch/run
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
from datetime import datetime, timezone, timedelta
import uuid
import logging

from database import db
from deps import get_current_user

router = APIRouter(prefix="/api/intel", tags=["auto-dispatch"])
logger = logging.getLogger(__name__)


async def _has_open_incident_for_device(device_ip: str, kind: str) -> bool:
    # Match by device_ip + auto_dispatch_kind within last 7 days
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    existing = await db.incidents.find_one({
        "device_ip": device_ip,
        "auto_dispatch_kind": kind,
        "created_at": {"$gte": since},
        "status": {"$in": ["open", "investigating", "in_progress", "identified"]}
    })
    return existing is not None


async def _create_auto_incident(*, title: str, description: str, device_ip: str,
                                 client_id: Optional[str], severity: str, kind: str,
                                 source_data: dict) -> str:
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": str(uuid.uuid4()),
        "title": title,
        "description": description,
        "status": "open",
        "priority": severity,       # low|medium|high|critical
        "severity": severity,
        "client_id": client_id,
        "device_ip": device_ip,
        "assigned_to": None,
        "created_at": now,
        "created_by": "auto-dispatch",
        "auto_dispatch": True,
        "auto_dispatch_kind": kind,   # "hardware_risk" | "predictive_failure"
        "source_data": source_data,
        "updated_at": now,
    }
    await db.incidents.insert_one(doc)
    logger.info(f"[AUTO-DISPATCH] Created incident {doc['id']} kind={kind} device={device_ip}")
    return doc["id"]


async def scan_hardware_lifecycle() -> dict:
    """Scansiona lifecycle_records e crea incident per asset high-risk."""
    from routes.lifecycle import _enrich_record
    created = []
    skipped_duplicate = 0
    cursor = db.lifecycle_records.find({}, {"_id": 0}).limit(5000)
    async for d in cursor:
        en = _enrich_record(dict(d))
        if en.get("risk_band") != "high":
            continue
        ip = en.get("device_ip")
        if not ip:
            continue
        if await _has_open_incident_for_device(ip, "hardware_risk"):
            skipped_duplicate += 1
            continue
        # Build description
        reasons = []
        w = en.get("warranty_days_left")
        if w is not None and w < 0:
            reasons.append(f"Garanzia scaduta da {-w} giorni")
        elif w is not None and w < 30:
            reasons.append(f"Garanzia in scadenza tra {w} giorni")
        e = en.get("eosl_days_left")
        if e is not None and e < 0:
            reasons.append(f"EOSL raggiunto da {-e} giorni (nessun supporto OEM)")
        elif e is not None and e < 180:
            reasons.append(f"EOSL tra {e} giorni")
        crit = en.get("criticality") or "medium"
        reasons.append(f"Criticality: {crit}")
        reasons.append(f"Risk score: {en.get('risk_score')}/100")

        vendor = en.get("vendor") or "Unknown"
        model = en.get("model") or ""
        desc = (
            f"Asset high-risk rilevato da Hardware Lifecycle Monitor.\n\n"
            f"Device: {ip}  ({vendor} {model})\n"
            f"Serial: {en.get('serial_number') or '—'}\n\n"
            f"Motivi:\n- " + "\n- ".join(reasons) +
            f"\n\nRaccomandazione: pianificare sostituzione o rinnovo contratto manutenzione entro 30gg."
        )
        severity = "high" if (en.get("risk_score") or 0) >= 70 else "medium"
        iid = await _create_auto_incident(
            title=f"[Hardware Risk] {vendor} {model} — {ip}",
            description=desc, device_ip=ip, client_id=en.get("client_id"),
            severity=severity, kind="hardware_risk",
            source_data={"risk_score": en.get("risk_score"), "risk_band": en.get("risk_band"),
                         "warranty_end": en.get("warranty_end"), "eosl_date": en.get("eosl_date")}
        )
        created.append({"incident_id": iid, "device_ip": ip, "risk_score": en.get("risk_score")})
    return {"kind": "hardware_risk", "created": len(created), "skipped_duplicate": skipped_duplicate, "items": created}


async def scan_predictive_failures() -> dict:
    """Scansiona device con telemetria iLO e crea incident per predictive failure <=72h."""
    from routes.intelligence import predictive_analysis
    created = []
    skipped_duplicate = 0
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    ips = await db.ilo_telemetry.distinct("device_ip", {"timestamp": {"$gte": since}})
    for ip in ips[:200]:
        try:
            r = await predictive_analysis(ip, {})  # dict passthrough
            if not r.get("enough_data"):
                continue
            eta = r.get("predicted_failure_window_hours")
            if not eta or eta > 72:
                continue
            if await _has_open_incident_for_device(ip, "predictive_failure"):
                skipped_duplicate += 1
                continue
            preds = r.get("predictions") or []
            top = preds[0] if preds else None
            desc_lines = [
                f"Predictive Failure Warning rilevato su device {ip}.",
                f"\nRisk score: {r.get('risk_score')}/100 · Band: {r.get('risk_band')}",
                f"Finestra stimata guasto: entro {eta}h",
                "",
                "Segnali:",
            ]
            for p in preds[:5]:
                desc_lines.append(f"- [{p.get('type')}] {p.get('message')} (confidence {int((p.get('confidence') or 0)*100)}%)")
            ms = r.get("metrics_summary") or {}
            desc_lines.append(f"\nMetriche 24h:")
            desc_lines.append(f"- Temperatura max: {ms.get('temperature_max')}°C, avg: {ms.get('temperature_avg')}°C")
            desc_lines.append(f"- Fan RPM max: {ms.get('fan_rpm_max')}%")
            desc_lines.append(f"- Power avg: {ms.get('power_avg_w')}W")
            desc_lines.append(f"\nRaccomandazione: intervento preventivo entro 24h (ispezione fisica, sostituzione ventole/PSU se servono).")
            severity = "critical" if eta <= 24 else ("high" if eta <= 72 else "medium")
            iid = await _create_auto_incident(
                title=f"[Predictive Failure] {ip} — guasto previsto entro {eta}h",
                description="\n".join(desc_lines),
                device_ip=ip, client_id=None, severity=severity,
                kind="predictive_failure",
                source_data={"risk_score": r.get("risk_score"), "eta_hours": eta, "top_prediction": top, "metrics_summary": ms}
            )
            created.append({"incident_id": iid, "device_ip": ip, "eta_hours": eta, "risk_score": r.get("risk_score")})
        except Exception as e:
            logger.warning(f"predictive scan error for {ip}: {e}")
    return {"kind": "predictive_failure", "created": len(created), "skipped_duplicate": skipped_duplicate, "items": created}


async def run_auto_dispatch() -> dict:
    """Esegue entrambe le scansioni — chiamata dal cron + endpoint manuale."""
    t0 = datetime.now(timezone.utc)
    hw = await scan_hardware_lifecycle()
    pr = await scan_predictive_failures()
    elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
    result = {
        "ran_at": t0.isoformat(),
        "elapsed_seconds": round(elapsed, 2),
        "hardware_risk": hw,
        "predictive_failure": pr,
        "total_created": hw["created"] + pr["created"],
    }
    # Persist history
    try:
        await db.auto_dispatch_history.insert_one({**result, "id": str(uuid.uuid4())})
    except Exception:
        pass
    return result


# =========================================================
# ENDPOINTS
# =========================================================

@router.post("/auto-dispatch/run")
async def manual_run(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "superadmin", "operator"):
        raise HTTPException(status_code=403, detail="Permission denied")
    return await run_auto_dispatch()


@router.get("/auto-dispatch/history")
async def list_history(limit: int = 20, current_user: dict = Depends(get_current_user)):
    cursor = db.auto_dispatch_history.find({}, {"_id": 0}).sort("ran_at", -1).limit(min(limit, 100))
    return {"items": [h async for h in cursor]}


@router.get("/auto-dispatch/status")
async def status(current_user: dict = Depends(get_current_user)):
    last = await db.auto_dispatch_history.find_one({}, {"_id": 0}, sort=[("ran_at", -1)])
    open_auto = await db.incidents.count_documents({"auto_dispatch": True, "status": {"$in": ["open", "investigating", "in_progress", "identified"]}})
    return {"last_run": last, "open_auto_incidents": open_auto}
