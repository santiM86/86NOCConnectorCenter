"""
NOC Intelligence — stile Park Place ParkView + Kaseya AI.

Contiene 3 moduli:
1. Proactive Fault Triage — classificazione automatica severity + root-cause suggestion
   basata su rule euristiche + knowledge base interna.
2. Patch Compliance — tracking patch OS/firmware per asset, alert CVE critici.
3. Predictive Failure Analysis — trend analysis su ilo_telemetry + pattern SMART
   per prevedere guasti 24-72h prima.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone, timedelta
import uuid
import logging
import statistics

from database import db
from deps import get_current_user

router = APIRouter(prefix="/api/intel", tags=["intelligence"])
audit = logging.getLogger("audit")


# =========================================================
# 1. PROACTIVE FAULT TRIAGE
# =========================================================

# Rule euristiche builtin (precedenza per AI/ML futuro).
TRIAGE_RULES = [
    # (pattern, severity, root_cause, recommended_action)
    ("link down|port down|ifdown|state: down", "high", "Link fisico interrotto o porta disabilitata", "Verificare cavo patch, LED switch, port-security. Runbook: link-flap-check"),
    ("cpu.*100|cpu high|cpu threshold", "critical", "Saturazione CPU", "Identificare processo runaway. Runbook: top-cpu-processes + restart service"),
    ("memory.*9[5-9]|memory high|oom|out of memory", "critical", "Esaurimento memoria, rischio OOM", "Riavvio servizio + analisi leak. Runbook: memory-leak-diagnose"),
    ("disk.*full|disk 9[5-9]|storage full", "critical", "Disco quasi pieno", "Pulizia log/temp. Runbook: disk-cleanup"),
    ("temperature|temp high|overheat|over.*temp", "critical", "Surriscaldamento hardware", "Verificare ventole, filtri, condizionamento. Contattare Park Place/OEM per RMA se ricorrente"),
    ("fan.*fail|fan down|ventola", "high", "Ventola guasta", "Sostituzione ventola. Se in garanzia: RMA OEM"),
    ("power.*fail|psu.*fail|alimentatore", "critical", "Alimentatore guasto", "Verificare ridondanza PSU. RMA OEM se in garanzia"),
    ("smart.*fail|smart predict|disk fail|disk error", "high", "Disco con errori SMART (predictive failure)", "Sostituzione disco preventiva prima del guasto totale"),
    ("certificate.*expir|ssl.*expir|cert.*expire", "medium", "Certificato SSL in scadenza", "Rinnovo certificato. Runbook: cert-renewal"),
    ("unreachable|no response|ping fail|icmp timeout", "high", "Device non raggiungibile", "Verificare alimentazione, connessione fisica, ACL. Iniziare da ping+traceroute"),
    ("service.*down|service stopped|servizio fermo", "high", "Servizio non attivo", "Restart servizio. Verificare log applicativo"),
    ("backup.*fail|backup error", "high", "Backup fallito", "Controllare spazio destinazione, credenziali, log Veeam/VSS"),
    ("authentication.*fail|auth fail|login fail", "medium", "Tentativi login falliti", "Verificare brute force, abilitare lockout"),
    ("high latency|latency.*ms|rtt", "medium", "Alta latenza di rete", "Traceroute al target, verificare ISP/peering"),
    ("toner low|drum low|fuser", "low", "Consumabile stampante in esaurimento", "Ordinare ricambio dal catalogo OEM"),
    ("paper jam|paper out", "medium", "Problema meccanico stampante", "Intervento tecnico on-site"),
]

SEVERITY_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}


async def triage_alert(alert_id: str) -> dict:
    """Applica triage rules + match KB interna su un alert."""
    alert = await db.alerts.find_one({"id": alert_id}, {"_id": 0})
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    haystack = f"{(alert.get('title') or '').lower()} {(alert.get('message') or '').lower()} {(alert.get('type') or '').lower()}"
    import re as _re
    matches = []
    suggested_severity = alert.get("severity") or "medium"
    root_cause = None
    recommended = []
    for pattern, sev, rc, action in TRIAGE_RULES:
        try:
            if _re.search(pattern, haystack):
                matches.append({"pattern": pattern, "severity": sev, "root_cause": rc, "action": action})
                if SEVERITY_ORDER.get(sev, 0) > SEVERITY_ORDER.get(suggested_severity, 0):
                    suggested_severity = sev
                if not root_cause:
                    root_cause = rc
                recommended.append(action)
        except Exception:
            pass

    # Similar alerts recurrence in last 30d (pattern learning)
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    similar_count = await db.alerts.count_documents({
        "device_ip": alert.get("device_ip"),
        "type": alert.get("type"),
        "created_at": {"$gte": since},
    })

    # KB match (problems collection with similar keywords)
    kb_matches = []
    kb_cursor = db.problems.find({"status": {"$in": ["known_error", "resolved"]}}, {"_id": 0, "id": 1, "title": 1, "root_cause": 1, "workaround": 1, "permanent_fix": 1}).limit(50)
    async for p in kb_cursor:
        ptitle = (p.get("title") or "").lower()
        if ptitle and (ptitle in haystack or any(w in haystack for w in ptitle.split() if len(w) > 4)):
            kb_matches.append(p)
    kb_matches = kb_matches[:3]

    triage_doc = {
        "alert_id": alert_id,
        "original_severity": alert.get("severity"),
        "suggested_severity": suggested_severity,
        "root_cause": root_cause,
        "recommended_actions": list(dict.fromkeys(recommended))[:5],
        "recurrence_30d": similar_count,
        "is_recurring": similar_count >= 3,
        "kb_matches": kb_matches,
        "rule_matches": matches,
        "triaged_at": datetime.now(timezone.utc).isoformat(),
    }
    # Store on alert doc (denormalized for quick frontend access)
    await db.alerts.update_one({"id": alert_id}, {"$set": {"triage": triage_doc}})
    return triage_doc


@router.post("/triage/{alert_id}")
async def triage(alert_id: str, current_user: dict = Depends(get_current_user)):
    return await triage_alert(alert_id)


@router.post("/triage-bulk")
async def triage_bulk(hours: int = 24, current_user: dict = Depends(get_current_user)):
    """Triage di tutti gli alert attivi non ancora triaged delle ultime N ore."""
    if current_user.get("role") not in ("admin", "superadmin", "operator"):
        raise HTTPException(status_code=403, detail="Permission denied")
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    cursor = db.alerts.find({
        "status": "active",
        "created_at": {"$gte": since},
        "triage": {"$exists": False}
    }, {"_id": 0, "id": 1}).limit(500)
    done = 0
    async for a in cursor:
        try:
            await triage_alert(a["id"])
            done += 1
        except Exception:
            pass
    return {"triaged": done}


@router.get("/triage/stats")
async def triage_stats(current_user: dict = Depends(get_current_user)):
    day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    total_triaged = await db.alerts.count_documents({"triage": {"$exists": True}, "created_at": {"$gte": week_ago}})
    # count upgrades (suggested > original)
    upgrades = 0
    downgrades = 0
    recurring = 0
    cursor = db.alerts.find({"triage": {"$exists": True}, "created_at": {"$gte": week_ago}}, {"_id": 0, "triage": 1})
    async for a in cursor:
        t = a.get("triage") or {}
        o = SEVERITY_ORDER.get(t.get("original_severity"), 0)
        s = SEVERITY_ORDER.get(t.get("suggested_severity"), 0)
        if s > o: upgrades += 1
        elif s < o: downgrades += 1
        if t.get("is_recurring"): recurring += 1
    return {
        "window_days": 7,
        "total_triaged": total_triaged,
        "severity_upgrades": upgrades,
        "severity_downgrades": downgrades,
        "recurring_issues": recurring,
    }


# =========================================================
# 2. PATCH COMPLIANCE
# =========================================================

class PatchStatus(BaseModel):
    device_ip: str
    client_id: Optional[str] = None
    os_name: Optional[str] = None         # Windows 2019, Ubuntu 22.04, Cisco IOS 15.x, ...
    os_version: Optional[str] = None
    firmware_version: Optional[str] = None
    last_patch_date: Optional[str] = None
    pending_patches: int = 0
    critical_patches: int = 0
    cve_count: int = 0
    cve_list: List[str] = []
    auto_update_enabled: bool = False
    last_check_at: Optional[str] = None


@router.post("/patch/status")
async def upsert_patch_status(ps: PatchStatus, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "superadmin", "operator"):
        raise HTTPException(status_code=403, detail="Permission denied")
    now = datetime.now(timezone.utc).isoformat()
    data = ps.model_dump()
    data["updated_at"] = now
    data["updated_by"] = current_user.get("email")
    if not data.get("last_check_at"):
        data["last_check_at"] = now
    await db.patch_status.update_one(
        {"device_ip": ps.device_ip},
        {"$set": data, "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": now}},
        upsert=True
    )
    return {"ok": True}


@router.get("/patch/status")
async def list_patch_status(client_id: Optional[str] = None, only_non_compliant: bool = False,
                             current_user: dict = Depends(get_current_user)):
    q = {}
    if client_id:
        q["client_id"] = client_id
    if only_non_compliant:
        q["$or"] = [{"critical_patches": {"$gt": 0}}, {"pending_patches": {"$gt": 10}}]
    cursor = db.patch_status.find(q, {"_id": 0}).limit(1000)
    items = [d async for d in cursor]
    return {"items": items, "total": len(items)}


@router.get("/patch/compliance")
async def patch_compliance(client_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    q = {}
    if client_id:
        q["client_id"] = client_id
    cursor = db.patch_status.find(q, {"_id": 0})
    total = 0
    compliant = 0
    with_critical = 0
    stale = 0  # not checked in last 30d
    cve_total = 0
    stale_cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    async for d in cursor:
        total += 1
        crit = d.get("critical_patches", 0) or 0
        pending = d.get("pending_patches", 0) or 0
        cve_total += d.get("cve_count", 0) or 0
        if crit == 0 and pending == 0:
            compliant += 1
        if crit > 0:
            with_critical += 1
        lc = d.get("last_check_at") or ""
        if lc < stale_cutoff:
            stale += 1
    compliance_pct = round((compliant / total * 100), 1) if total else 0.0
    return {
        "total_devices": total,
        "compliant_devices": compliant,
        "compliance_percentage": compliance_pct,
        "devices_with_critical_patches": with_critical,
        "stale_devices_30d": stale,
        "total_open_cves": cve_total,
    }


# =========================================================
# 3. PREDICTIVE FAILURE ANALYSIS
# =========================================================

@router.get("/predictive/{device_ip}")
async def predictive_analysis(device_ip: str, current_user: dict = Depends(get_current_user)):
    """Analizza trend ilo_telemetry ultime 24h e ritorna risk score predittivo."""
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    cursor = db.ilo_telemetry.find({"device_ip": device_ip, "timestamp": {"$gte": since}}, {"_id": 0}).sort("timestamp", 1)
    samples = [d async for d in cursor]
    if len(samples) < 5:
        return {"device_ip": device_ip, "enough_data": False, "samples": len(samples), "message": "Insufficient data (needs 5+ snapshots)"}

    # Extract time series
    powers = [s.get("power_watts") for s in samples if isinstance(s.get("power_watts"), (int, float))]
    temps = []
    fans = []
    for s in samples:
        t_list = [t.get("reading") for t in (s.get("temperatures") or []) if isinstance(t.get("reading"), (int, float))]
        if t_list:
            temps.append(max(t_list))
        f_list = [f.get("reading") for f in (s.get("fans") or []) if isinstance(f.get("reading"), (int, float))]
        if f_list:
            fans.append(max(f_list))

    predictions = []
    risk_score = 0

    def _trend(series):
        """Simple slope: last-avg - first-avg (using halves)"""
        if len(series) < 4:
            return 0
        half = len(series) // 2
        avg_first = statistics.mean(series[:half])
        avg_last = statistics.mean(series[-half:])
        return avg_last - avg_first

    if temps:
        max_t = max(temps)
        avg_t = statistics.mean(temps)
        slope_t = _trend(temps)
        if max_t >= 85:
            predictions.append({"type": "temperature", "severity": "critical",
                                "message": f"Temperature peak {max_t:.1f}°C — hardware at thermal limit", "confidence": 0.95})
            risk_score += 40
        elif max_t >= 75:
            predictions.append({"type": "temperature", "severity": "high",
                                "message": f"Temperature peak {max_t:.1f}°C — above safe threshold", "confidence": 0.8})
            risk_score += 25
        if slope_t > 3 and avg_t > 55:
            predictions.append({"type": "temperature_trend", "severity": "medium",
                                "message": f"Temperature rising +{slope_t:.1f}°C over window — possible fan degradation", "confidence": 0.7})
            risk_score += 15

    if fans:
        max_f = max(fans)
        min_f = min(fans)
        if max_f >= 95:
            predictions.append({"type": "fan_rpm", "severity": "high",
                                "message": f"Fan RPM at {max_f:.0f}% — compensating for thermal stress or fan imbalance", "confidence": 0.75})
            risk_score += 20
        if min_f == 0:
            predictions.append({"type": "fan_stopped", "severity": "critical",
                                "message": "Detected fan at 0 RPM — likely fan failure", "confidence": 0.9})
            risk_score += 35

    if powers:
        slope_p = _trend(powers)
        avg_p = statistics.mean(powers)
        if avg_p > 0 and slope_p / avg_p > 0.15:
            predictions.append({"type": "power_draw", "severity": "medium",
                                "message": f"Power draw rising {slope_p:.0f}W (+{(slope_p/avg_p)*100:.0f}%) — load increase or PSU issue", "confidence": 0.6})
            risk_score += 10

    risk_score = min(100, risk_score)
    band = "high" if risk_score >= 50 else ("medium" if risk_score >= 25 else "low")

    # Window-based ETA estimate (heuristic)
    eta_hours = None
    if risk_score >= 70:
        eta_hours = 24
    elif risk_score >= 50:
        eta_hours = 72
    elif risk_score >= 30:
        eta_hours = 168

    return {
        "device_ip": device_ip,
        "enough_data": True,
        "samples": len(samples),
        "risk_score": risk_score,
        "risk_band": band,
        "predicted_failure_window_hours": eta_hours,
        "predictions": predictions,
        "metrics_summary": {
            "temperature_max": round(max(temps), 1) if temps else None,
            "temperature_avg": round(statistics.mean(temps), 1) if temps else None,
            "fan_rpm_max": round(max(fans), 0) if fans else None,
            "power_avg_w": round(statistics.mean(powers), 0) if powers else None,
        },
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/predictive")
async def predictive_overview(current_user: dict = Depends(get_current_user)):
    """Scansiona tutti i device con telemetria iLO disponibile e ritorna risk board."""
    # Get distinct device_ips with recent telemetry
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    ips = await db.ilo_telemetry.distinct("device_ip", {"timestamp": {"$gte": since}})
    results = []
    for ip in ips[:100]:
        try:
            r = await predictive_analysis(ip, current_user)  # type: ignore
            if r.get("enough_data"):
                results.append({
                    "device_ip": ip,
                    "risk_score": r.get("risk_score"),
                    "risk_band": r.get("risk_band"),
                    "predicted_eta_hours": r.get("predicted_failure_window_hours"),
                    "top_prediction": r["predictions"][0] if r.get("predictions") else None,
                })
        except Exception:
            pass
    results.sort(key=lambda x: x.get("risk_score", 0), reverse=True)
    return {"items": results, "total": len(results)}


async def init_indexes():
    await db.patch_status.create_index([("device_ip", 1)], unique=True)
    await db.patch_status.create_index([("client_id", 1)])
