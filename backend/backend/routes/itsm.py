"""
ITSM workflows — Change Management (RFC), Problem Management, Shift Handoff, Service Billing.
Schema compatti ITIL-like.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone, timedelta
import uuid

from database import db
from deps import get_current_user

router = APIRouter(prefix="/api/itsm", tags=["itsm"])


# ======================== CHANGE MANAGEMENT (RFC) ========================

class ChangeRequest(BaseModel):
    title: str
    description: Optional[str] = None
    client_id: Optional[str] = None
    device_ips: List[str] = []
    risk: str = "medium"  # low | medium | high | critical
    impact: str = "medium"
    planned_start: Optional[str] = None
    planned_end: Optional[str] = None
    implementation_plan: Optional[str] = None
    rollback_plan: Optional[str] = None
    category: Optional[str] = None  # normal | standard | emergency


@router.post("/changes")
async def create_change(cr: ChangeRequest, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "superadmin", "operator"):
        raise HTTPException(status_code=403, detail="Permission denied")
    now = datetime.now(timezone.utc)
    data = cr.model_dump()
    data["id"] = str(uuid.uuid4())
    data["status"] = "pending_approval"
    data["created_at"] = now.isoformat()
    data["created_by"] = current_user.get("email")
    data["approved_at"] = None
    data["approved_by"] = None
    data["implemented_at"] = None
    data["pir_notes"] = None
    await db.changes.insert_one(data)
    return data


@router.get("/changes")
async def list_changes(status: Optional[str] = None, client_id: Optional[str] = None,
                       current_user: dict = Depends(get_current_user)):
    q = {}
    if status:
        q["status"] = status
    if client_id:
        q["client_id"] = client_id
    cursor = db.changes.find(q, {"_id": 0}).sort("created_at", -1).limit(300)
    return {"items": [c async for c in cursor]}


@router.post("/changes/{change_id}/approve")
async def approve_change(change_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin only")
    await db.changes.update_one({"id": change_id}, {"$set": {
        "status": "approved",
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "approved_by": current_user.get("email"),
    }})
    return {"ok": True}


@router.post("/changes/{change_id}/reject")
async def reject_change(change_id: str, reason: str = "", current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin only")
    await db.changes.update_one({"id": change_id}, {"$set": {
        "status": "rejected",
        "rejection_reason": reason,
        "rejected_by": current_user.get("email"),
        "rejected_at": datetime.now(timezone.utc).isoformat(),
    }})
    return {"ok": True}


@router.post("/changes/{change_id}/complete")
async def complete_change(change_id: str, pir_notes: Optional[str] = None,
                           current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "superadmin", "operator"):
        raise HTTPException(status_code=403, detail="Permission denied")
    await db.changes.update_one({"id": change_id}, {"$set": {
        "status": "completed",
        "implemented_at": datetime.now(timezone.utc).isoformat(),
        "implemented_by": current_user.get("email"),
        "pir_notes": pir_notes,
    }})
    return {"ok": True}


# ======================== PROBLEM MANAGEMENT ========================

class ProblemRecord(BaseModel):
    title: str
    description: Optional[str] = None
    client_id: Optional[str] = None
    linked_incident_ids: List[str] = []
    root_cause: Optional[str] = None
    five_whys: List[str] = []
    workaround: Optional[str] = None
    permanent_fix: Optional[str] = None
    status: str = "investigating"  # investigating | known_error | resolved


@router.post("/problems")
async def create_problem(p: ProblemRecord, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "superadmin", "operator"):
        raise HTTPException(status_code=403, detail="Permission denied")
    now = datetime.now(timezone.utc)
    data = p.model_dump()
    data["id"] = str(uuid.uuid4())
    data["created_at"] = now.isoformat()
    data["created_by"] = current_user.get("email")
    data["updated_at"] = now.isoformat()
    await db.problems.insert_one(data)
    return data


@router.get("/problems")
async def list_problems(status: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    q = {}
    if status:
        q["status"] = status
    cursor = db.problems.find(q, {"_id": 0}).sort("created_at", -1).limit(200)
    return {"items": [p async for p in cursor]}


@router.put("/problems/{pid}")
async def update_problem(pid: str, p: ProblemRecord, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "superadmin", "operator"):
        raise HTTPException(status_code=403, detail="Permission denied")
    data = p.model_dump()
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    data["updated_by"] = current_user.get("email")
    await db.problems.update_one({"id": pid}, {"$set": data})
    return {"ok": True}


@router.get("/problems/recurrence")
async def recurrence_kpi(current_user: dict = Depends(get_current_user)):
    """KPI: quanti problem hanno causato multiple incident (>= 3 linked incidents)."""
    cursor = db.problems.find({}, {"_id": 0, "id": 1, "title": 1, "linked_incident_ids": 1, "status": 1})
    recurring = []
    async for p in cursor:
        if len(p.get("linked_incident_ids") or []) >= 3:
            recurring.append(p)
    return {"recurring_problems": recurring, "total": len(recurring)}


# ======================== SHIFT HANDOFF ========================

@router.get("/shift-handoff")
async def shift_handoff_report(hours: int = 8, current_user: dict = Depends(get_current_user)):
    """Report auto delle ultime N ore (default 8) per handoff turno successivo."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    since_iso = since.isoformat()

    # Nuovi alert
    new_alerts_cursor = db.alerts.find(
        {"created_at": {"$gte": since_iso}},
        {"_id": 0, "id": 1, "title": 1, "severity": 1, "status": 1, "device_ip": 1, "client_id": 1, "created_at": 1}
    ).sort("created_at", -1).limit(100)
    new_alerts = [a async for a in new_alerts_cursor]

    # Alert critici ancora aperti
    critical_open_cursor = db.alerts.find(
        {"status": "active", "severity": "critical"},
        {"_id": 0, "id": 1, "title": 1, "device_ip": 1, "client_id": 1, "created_at": 1}
    ).limit(50)
    critical_open = [a async for a in critical_open_cursor]

    # Incidenti in corso
    incidents_open_cursor = db.incidents.find(
        {"status": {"$in": ["open", "investigating", "identified", "in_progress"]}},
        {"_id": 0, "id": 1, "title": 1, "status": 1, "severity": 1, "client_id": 1, "created_at": 1, "assigned_to": 1}
    ).limit(50)
    incidents_open = [i async for i in incidents_open_cursor]

    # Change in esecuzione o approvati da eseguire
    changes_active_cursor = db.changes.find(
        {"status": {"$in": ["approved", "in_progress"]}},
        {"_id": 0, "id": 1, "title": 1, "status": 1, "planned_start": 1, "planned_end": 1}
    ).limit(30)
    changes_active = [c async for c in changes_active_cursor]

    return {
        "report_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": hours,
        "new_alerts_count": len(new_alerts),
        "new_alerts": new_alerts[:20],  # top 20
        "critical_open": critical_open,
        "incidents_open": incidents_open,
        "changes_active": changes_active,
        "handoff_summary": _build_handoff_text(new_alerts, critical_open, incidents_open, changes_active, hours),
    }


def _build_handoff_text(new_alerts, critical_open, incidents_open, changes_active, hours):
    lines = [f"### SHIFT HANDOFF — ultime {hours}h"]
    lines.append(f"- Nuovi alert: **{len(new_alerts)}** totali, {sum(1 for a in new_alerts if a.get('severity')=='critical')} critici.")
    if critical_open:
        lines.append(f"- ATTENZIONE: **{len(critical_open)}** alert CRITICI ancora aperti:")
        for a in critical_open[:5]:
            lines.append(f"  - {a.get('device_ip','?')} — {a.get('title','?')[:80]}")
    if incidents_open:
        lines.append(f"- Incident in corso: **{len(incidents_open)}**")
        for i in incidents_open[:5]:
            lines.append(f"  - [{i.get('status')}] {i.get('title','?')[:80]} (assigned: {i.get('assigned_to') or 'n/a'})")
    if changes_active:
        lines.append(f"- Change attivi/approvati: **{len(changes_active)}**")
    return "\n".join(lines)


# ======================== SERVICE BILLING ========================

@router.get("/billing/monthly/{client_id}")
async def billing_monthly(client_id: str, month: Optional[str] = None,
                           current_user: dict = Depends(get_current_user)):
    """Billing stimato per un cliente: #device × device_rate + #ticket × ticket_rate + add-on."""
    if current_user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin only")

    if month:
        y, m = month.split("-")
        start = datetime(int(y), int(m), 1, tzinfo=timezone.utc)
    else:
        now = datetime.now(timezone.utc)
        start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    next_m = start.month % 12 + 1
    next_y = start.year + (1 if start.month == 12 else 0)
    end = datetime(next_y, next_m, 1, tzinfo=timezone.utc)

    # Rate (default, configurabili via settings.billing)
    billing_cfg = await db.settings.find_one({"key": "billing_rates"}) or {}
    device_rate = billing_cfg.get("device_rate_eur", 8.0)
    ticket_rate = billing_cfg.get("ticket_rate_eur", 15.0)

    # Device count snapshot
    device_count = await db.managed_devices.count_documents({"client_id": client_id})

    # Ticket/incident count nel periodo
    ticket_count = await db.incidents.count_documents({
        "client_id": client_id,
        "created_at": {"$gte": start.isoformat(), "$lt": end.isoformat()}
    })

    device_cost = device_count * device_rate
    ticket_cost = ticket_count * ticket_rate
    total = device_cost + ticket_cost

    return {
        "client_id": client_id,
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "devices_monitored": device_count,
        "device_rate_eur": device_rate,
        "device_cost_eur": round(device_cost, 2),
        "tickets_count": ticket_count,
        "ticket_rate_eur": ticket_rate,
        "ticket_cost_eur": round(ticket_cost, 2),
        "total_eur": round(total, 2),
    }
