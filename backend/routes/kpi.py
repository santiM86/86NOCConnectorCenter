"""KPI dashboard (Panoramica): fascia di indicatori con trend e sparkline.

- `GET /api/overview/kpi?period=24h|7d|30d`
- `record_kpi_snapshot(db)` (cron 10 min) → `kpi_snapshots` alimenta sparkline/trend
  dei KPI "di stato" (disponibilità, clienti rossi, alert attivi, agent, backup, hw).
  I KPI "di flusso" (alert aperti, MTTR, auto-chiusi) sono calcolati dalla collection alerts.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query

from database import db
from deps import get_current_user
from liveness_resolver import AGENT_HEARTBEAT_STALE_SECONDS

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/overview", tags=["kpi"])

PERIODS = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}
HW_RISK_RX = re.compile(r"^(predictive_|threshold_temp|vendor_disk|vendor_qnap_smart|redfish|hw_|hardware|ilo_)")
NOISE_REASONS = {"unconfirmed", "false_positive", "expired"}
SPARK_POINTS = 40


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(v) -> Optional[datetime]:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


async def _current_state(user: Optional[dict] = None) -> dict:
    """Stato attuale (riusa la cache di /overview/clients)."""
    from routes.overview import get_clients_overview
    ov = await get_clients_overview(user or {"role": "admin"})
    g = ov.get("global") or {}
    clients = ov.get("clients") or []
    backup_ko = sum(int((c.get("backup") or {}).get("error") or 0) for c in clients)
    backup_total = sum(int((c.get("backup") or {}).get("total") or 0) for c in clients)
    connectors_total = sum(1 for c in clients if c.get("connector_online") is not None)
    connectors_off = sum(1 for c in clients if c.get("connector_online") is False)

    cutoff = (_now() - timedelta(seconds=AGENT_HEARTBEAT_STALE_SECONDS)).isoformat()
    agents_total = await db.managed_agents.count_documents({})
    agents_online = await db.managed_agents.count_documents({"last_heartbeat_at": {"$gte": cutoff}})

    sev = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    hw_devices: set = set()
    hw_predicted = 0
    async for g_ in db.alerts.aggregate([
        {"$match": {"status": {"$in": ["active", "acknowledged"]}}},
        {"$group": {"_id": {"sev": {"$toLower": {"$ifNull": ["$severity", "low"]}}, "st": {"$ifNull": ["$source_type", ""]}},
                    "n": {"$sum": 1}, "devices": {"$addToSet": {"$ifNull": ["$device_ip", "$id"]}}}},
    ]):
        s = g_["_id"]["sev"] or "low"
        sev[s] = sev.get(s, 0) + g_["n"]
        st = g_["_id"]["st"]
        if HW_RISK_RX.match(st):
            hw_devices.update(d for d in g_["devices"] if d)
            if st.startswith("predictive_"):
                hw_predicted += g_["n"]

    vital_total = int(g.get("total_devices") or 0)
    vital_online = int(g.get("devices_online") or 0)
    return {
        "at": _now().isoformat(),
        "availability_pct": round(vital_online / vital_total * 100, 1) if vital_total else None,
        "vital_online": vital_online, "vital_total": vital_total,
        "clients_total": int(g.get("total_clients") or 0),
        "clients_critical": int(g.get("clients_critical") or 0),
        "clients_warning": int(g.get("clients_warning") or 0),
        "alerts_active": sev,
        "agents_total": agents_total + connectors_total,
        "agents_offline": (agents_total - agents_online) + connectors_off,
        "backup_ko": backup_ko, "backup_total": backup_total,
        "hw_risk": len(hw_devices), "hw_predicted": hw_predicted,
    }


async def record_kpi_snapshot(db_) -> dict:
    snap = await _current_state()
    await db_.kpi_snapshots.insert_one(dict(snap))
    snap.pop("_id", None)
    return snap


def _downsample(points: list, n: int = SPARK_POINTS) -> list:
    if len(points) <= n:
        return points
    step = len(points) / n
    return [points[int(i * step)] for i in range(n)]


def _trend(cur, prev, invert: bool = False) -> Optional[dict]:
    """Delta assoluto e %; `good` = True se il movimento è positivo per l'operatore."""
    if cur is None or prev is None:
        return None
    delta = round(cur - prev, 1)
    pct = round(delta / prev * 100, 1) if prev else None
    good = (delta <= 0) if invert else (delta >= 0)
    return {"delta": delta, "pct": pct, "good": good if delta != 0 else None}


def _hist(dts: list[datetime], start: datetime, end: datetime, buckets: int = 24) -> list:
    width = (end - start) / buckets
    out = [0] * buckets
    for d in dts:
        i = int((d - start) / width)
        if 0 <= i < buckets:
            out[i] += 1
    return out


@router.get("/kpi")
async def get_kpi(period: str = Query("24h"), current_user: dict = Depends(get_current_user)):
    if period not in PERIODS:
        period = "24h"
    span = PERIODS[period]
    now = _now()
    start = now - span
    prev_start = start - span

    cur = await _current_state(current_user)

    # --- snapshot storici (sparkline + trend "di stato") ---
    snaps = [s async for s in db.kpi_snapshots.find(
        {"at": {"$gte": prev_start.isoformat()}}, {"_id": 0}).sort("at", 1)]
    in_period = [s for s in snaps if s.get("at", "") >= start.isoformat()]
    before = [s for s in snaps if s.get("at", "") < start.isoformat()]
    baseline = (before[-1] if before else (in_period[0] if in_period else None))

    def series(key, sub=None):
        vals = []
        for s in in_period + [cur]:
            v = s.get(key)
            if sub and isinstance(v, dict):
                v = v.get(sub)
            vals.append(v if v is not None else 0)
        return _downsample(vals)

    def base(key, sub=None):
        if not baseline:
            return None
        v = baseline.get(key)
        if sub and isinstance(v, dict):
            v = v.get(sub)
        return v

    # --- KPI di flusso dagli alert ---
    from routes.alerts import derive_resolution_reason
    opened: list[datetime] = []
    opened_prev = 0
    mttr: list[float] = []
    mttr_prev: list[float] = []
    closed = {"auto": 0, "manual": 0, "noise": 0}
    closed_prev = {"auto": 0, "manual": 0, "noise": 0}
    async for a in db.alerts.find(
            {"$or": [{"created_at": {"$gte": prev_start.isoformat()}}, {"resolved_at": {"$gte": prev_start.isoformat()}}]},
            {"_id": 0, "created_at": 1, "resolved_at": 1, "resolution_note": 1, "resolution_reason": 1,
             "auto_expired": 1, "resolved_by": 1, "status": 1}):
        c = _parse(a.get("created_at"))
        r = _parse(a.get("resolved_at"))
        if c:
            if c >= start:
                opened.append(c)
            elif c >= prev_start:
                opened_prev += 1
        if r and a.get("status") == "resolved":
            reason = a.get("resolution_reason") or derive_resolution_reason(a)
            bucket = closed if r >= start else (closed_prev if r >= prev_start else None)
            if bucket is not None:
                if reason == "manual":
                    bucket["manual"] += 1
                else:
                    bucket["auto"] += 1
                    if reason in NOISE_REASONS:
                        bucket["noise"] += 1
                if c and r >= c:
                    (mttr if r >= start else mttr_prev).append((r - c).total_seconds() / 60)

    mttr_val = round(sum(mttr) / len(mttr), 1) if mttr else None
    mttr_prev_val = round(sum(mttr_prev) / len(mttr_prev), 1) if mttr_prev else None
    closed_tot = closed["auto"] + closed["manual"]
    closed_prev_tot = closed_prev["auto"] + closed_prev["manual"]
    noise_pct = round(closed["noise"] / closed_tot * 100, 1) if closed_tot else None
    noise_prev_pct = round(closed_prev["noise"] / closed_prev_tot * 100, 1) if closed_prev_tot else None

    sev = cur["alerts_active"]
    kpis = [
        {"key": "availability", "label": "Disponibilità vitali", "value": cur["availability_pct"], "unit": "%",
         "sub": f"{cur['vital_online']}/{cur['vital_total']} online",
         "trend": _trend(cur["availability_pct"], base("availability_pct")),
         "series": series("availability_pct"), "link": "/network-status", "tone": "ok" if (cur["availability_pct"] or 0) >= 99 else ("warn" if (cur["availability_pct"] or 0) >= 95 else "crit")},
        {"key": "clients", "label": "Clienti con problemi", "value": cur["clients_critical"], "unit": "",
         "sub": f"{cur['clients_warning']} warning · {cur['clients_total']} totali",
         "trend": _trend(cur["clients_critical"], base("clients_critical"), invert=True),
         "series": series("clients_critical"), "link": "/clients", "tone": "crit" if cur["clients_critical"] else "ok"},
        {"key": "alerts", "label": "Alert attivi", "value": sum(sev.values()), "unit": "",
         "sub": f"{sev['critical']} crit · {sev['high']} high · {sev['medium']} med",
         "trend": _trend(sum(sev.values()), (sum((base("alerts_active") or {}).values()) if baseline else None), invert=True),
         "series": series("alerts_active", "critical"), "link": "/alerts?status=active",
         "tone": "crit" if sev["critical"] else ("warn" if sev["high"] else "ok"), "breakdown": sev},
        {"key": "opened", "label": f"Alert aperti ({period})", "value": len(opened), "unit": "",
         "sub": f"{opened_prev} nel periodo precedente",
         "trend": _trend(len(opened), opened_prev, invert=True),
         "series": _hist(opened, start, now), "link": "/alerts", "tone": "info"},
        {"key": "mttr", "label": "MTTR medio", "value": mttr_val, "unit": "min",
         "sub": f"{len(mttr)} alert risolti",
         "trend": _trend(mttr_val, mttr_prev_val, invert=True), "series": [], "link": "/alerts?status=resolved", "tone": "info"},
        {"key": "noise", "label": "Rumore (auto-chiusi)", "value": noise_pct, "unit": "%",
         "sub": f"{closed['auto']} auto · {closed['manual']} manuali",
         "trend": _trend(noise_pct, noise_prev_pct, invert=True), "series": [], "link": "/alerts?status=resolved&reason=unconfirmed",
         "tone": "warn" if (noise_pct or 0) > 30 else "ok"},
        {"key": "backup", "label": "Backup KO", "value": cur["backup_ko"], "unit": "",
         "sub": f"su {cur['backup_total']} job",
         "trend": _trend(cur["backup_ko"], base("backup_ko"), invert=True), "series": series("backup_ko"),
         "link": "/settings/hornetsecurity", "tone": "crit" if cur["backup_ko"] else "ok"},
        {"key": "hw", "label": "Hardware a rischio", "value": cur["hw_risk"], "unit": "",
         "sub": f"{cur['hw_predicted']} guasti predetti",
         "trend": _trend(cur["hw_risk"], base("hw_risk"), invert=True), "series": series("hw_risk"),
         "link": "/lifecycle", "tone": "warn" if cur["hw_risk"] else "ok"},
        {"key": "agents", "label": "Agent / Connector offline", "value": cur["agents_offline"], "unit": "",
         "sub": f"su {cur['agents_total']}",
         "trend": _trend(cur["agents_offline"], base("agents_offline"), invert=True), "series": series("agents_offline"),
         "link": "/agents", "tone": "crit" if cur["agents_offline"] else "ok"},
    ]
    return {"period": period, "from": start.isoformat(), "to": now.isoformat(), "snapshots": len(in_period),
            "baseline_at": (baseline or {}).get("at"), "kpis": kpis}
