"""
SLA Management — definizione target per cliente e misurazione automatica.
Metriche: uptime %, MTTA (mean time to acknowledge), MTTR (mean time to resolve),
alert response time per severity.
Output: compliance mensile, breach list, credit dovuti (se definiti).
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone, timedelta
import uuid

from database import db
from deps import get_current_user

router = APIRouter(prefix="/api/sla", tags=["sla"])


class SLATarget(BaseModel):
    client_id: str
    name: str = "Default SLA"
    uptime_target_percent: float = 99.9
    mtta_minutes: int = 15  # Target acknowledge
    mttr_hours: int = 4  # Target resolve
    hours_coverage: str = "24x7"  # or "business_hours"
    credit_percent_per_breach: float = 5.0  # % credito su fatturato mese
    active: bool = True


@router.get("/targets")
async def list_targets(client_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    q = {}
    if client_id:
        q["client_id"] = client_id
    cursor = db.sla_targets.find(q, {"_id": 0}).limit(100)
    return {"items": [d async for d in cursor]}


@router.post("/targets")
async def upsert_target(target: SLATarget, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin only")
    now = datetime.now(timezone.utc)
    data = target.model_dump()
    data["updated_at"] = now
    await db.sla_targets.update_one(
        {"client_id": target.client_id},
        {"$set": data, "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": now}},
        upsert=True
    )
    return {"ok": True}


@router.get("/compliance/{client_id}")
async def compliance_report(client_id: str, month: Optional[str] = None,
                             current_user: dict = Depends(get_current_user)):
    """Compliance SLA per un mese (default: mese corrente). Format month=YYYY-MM."""
    target = await db.sla_targets.find_one({"client_id": client_id}, {"_id": 0})
    if not target:
        raise HTTPException(status_code=404, detail="SLA target non definito per questo cliente")

    # Finestra temporale
    if month:
        y, m = month.split("-")
        start = datetime(int(y), int(m), 1, tzinfo=timezone.utc)
    else:
        now = datetime.now(timezone.utc)
        start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    # End = primo del mese dopo
    next_m = start.month % 12 + 1
    next_y = start.year + (1 if start.month == 12 else 0)
    end = datetime(next_y, next_m, 1, tzinfo=timezone.utc)

    start_iso = start.isoformat()
    end_iso = end.isoformat()

    # Alerts del periodo
    alerts_cursor = db.alerts.find({
        "client_id": client_id,
        "created_at": {"$gte": start_iso, "$lt": end_iso}
    }, {"_id": 0})
    alerts = [a async for a in alerts_cursor]

    total_alerts = len(alerts)
    critical = [a for a in alerts if a.get("severity") == "critical"]

    # MTTA — differenza tra created_at e acknowledged_at (se presente)
    mtta_samples = []
    for a in alerts:
        if a.get("acknowledged_at") and a.get("created_at"):
            try:
                t0 = datetime.fromisoformat(a["created_at"].replace("Z", "+00:00"))
                t1 = datetime.fromisoformat(a["acknowledged_at"].replace("Z", "+00:00"))
                mtta_samples.append((t1 - t0).total_seconds() / 60)
            except Exception:
                pass
    mtta_avg_min = round(sum(mtta_samples) / len(mtta_samples), 1) if mtta_samples else None

    # MTTR — differenza tra created_at e resolved_at
    mttr_samples = []
    for a in alerts:
        if a.get("resolved_at") and a.get("created_at"):
            try:
                t0 = datetime.fromisoformat(a["created_at"].replace("Z", "+00:00"))
                t1 = datetime.fromisoformat(a["resolved_at"].replace("Z", "+00:00"))
                mttr_samples.append((t1 - t0).total_seconds() / 3600)
            except Exception:
                pass
    mttr_avg_h = round(sum(mttr_samples) / len(mttr_samples), 2) if mttr_samples else None

    # Breach analysis
    breaches = []
    if mtta_avg_min is not None and mtta_avg_min > target["mtta_minutes"]:
        breaches.append({"metric": "MTTA", "target": target["mtta_minutes"], "actual": mtta_avg_min, "unit": "min"})
    if mttr_avg_h is not None and mttr_avg_h > target["mttr_hours"]:
        breaches.append({"metric": "MTTR", "target": target["mttr_hours"], "actual": mttr_avg_h, "unit": "h"})

    # Uptime stimato dalla tabella device_poll_status (% di poll "online")
    total_polls = 0
    online_polls = 0
    async for ps in db.device_poll_status.find({"client_id": client_id}, {"total_polls": 1, "online_polls": 1}):
        total_polls += ps.get("total_polls", 0)
        online_polls += ps.get("online_polls", 0)
    uptime_pct = round(100.0 * online_polls / total_polls, 3) if total_polls > 0 else None
    if uptime_pct is not None and uptime_pct < target["uptime_target_percent"]:
        breaches.append({"metric": "Uptime", "target": target["uptime_target_percent"], "actual": uptime_pct, "unit": "%"})

    credit_due_percent = sum([target["credit_percent_per_breach"] for _ in breaches])

    return {
        "client_id": client_id,
        "period": {"start": start_iso, "end": end_iso},
        "target": target,
        "metrics": {
            "total_alerts": total_alerts,
            "critical_alerts": len(critical),
            "mtta_avg_minutes": mtta_avg_min,
            "mttr_avg_hours": mttr_avg_h,
            "uptime_percent": uptime_pct,
        },
        "breaches": breaches,
        "compliance": "compliant" if not breaches else "breach",
        "credit_due_percent": credit_due_percent,
    }
