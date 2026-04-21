"""
Runbooks — procedure operative per tecnici NOC.
Ogni runbook ha: titolo, device_type/alert_type (trigger match),
steps (ordinati, con comando/spiegazione), owner, last_updated.
Quando si apre un alert, il frontend cerca runbook matching e mostra "procedura suggerita".
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone
import uuid

from database import db
from deps import get_current_user

router = APIRouter(prefix="/api/runbooks", tags=["runbooks"])


class RunbookStep(BaseModel):
    order: int
    title: str
    description: Optional[str] = None
    command: Optional[str] = None  # Comando shell/CLI opzionale
    expected_result: Optional[str] = None


class Runbook(BaseModel):
    id: Optional[str] = None
    title: str
    description: Optional[str] = None
    device_types: List[str] = []  # match: switch, router, ilo, firewall, nas, ups
    alert_keywords: List[str] = []  # match titolo/messaggio alert (case-insensitive)
    severity_match: List[str] = []  # ["critical", "warning"] — empty = any
    vendor_match: List[str] = []  # ["HPE", "Cisco"] — empty = any
    steps: List[RunbookStep] = []
    tags: List[str] = []


@router.get("")
async def list_runbooks(device_type: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    q = {}
    if device_type:
        q["device_types"] = device_type
    cursor = db.runbooks.find(q, {"_id": 0}).sort("updated_at", -1).limit(200)
    return {"items": [d async for d in cursor]}


@router.get("/{rb_id}")
async def get_runbook(rb_id: str, current_user: dict = Depends(get_current_user)):
    rb = await db.runbooks.find_one({"id": rb_id}, {"_id": 0})
    if not rb:
        raise HTTPException(status_code=404, detail="Runbook not found")
    return rb


@router.post("")
async def create_runbook(rb: Runbook, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "superadmin", "operator"):
        raise HTTPException(status_code=403, detail="Permission denied")
    now = datetime.now(timezone.utc)
    data = rb.model_dump()
    data["id"] = data.get("id") or str(uuid.uuid4())
    data["created_at"] = now
    data["updated_at"] = now
    data["created_by"] = current_user.get("email")
    # Normalize keywords to lowercase
    data["alert_keywords"] = [k.lower() for k in (data.get("alert_keywords") or [])]
    data["device_types"] = [k.lower() for k in (data.get("device_types") or [])]
    await db.runbooks.insert_one(data)
    return data


@router.put("/{rb_id}")
async def update_runbook(rb_id: str, rb: Runbook, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "superadmin", "operator"):
        raise HTTPException(status_code=403, detail="Permission denied")
    data = rb.model_dump()
    data["updated_at"] = datetime.now(timezone.utc)
    data["updated_by"] = current_user.get("email")
    data["alert_keywords"] = [k.lower() for k in (data.get("alert_keywords") or [])]
    data["device_types"] = [k.lower() for k in (data.get("device_types") or [])]
    data.pop("id", None)
    res = await db.runbooks.update_one({"id": rb_id}, {"$set": data})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


@router.delete("/{rb_id}")
async def delete_runbook(rb_id: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Admin only")
    res = await db.runbooks.delete_one({"id": rb_id})
    return {"deleted": res.deleted_count > 0}


@router.get("/match/alert/{alert_id}")
async def match_alert(alert_id: str, current_user: dict = Depends(get_current_user)):
    """Trova i runbook rilevanti per un alert specifico (matching smart su device_type/severity/keywords)."""
    alert = await db.alerts.find_one({"id": alert_id}, {"_id": 0})
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    device_type = (alert.get("device_type") or "").lower()
    severity = alert.get("severity") or ""
    title = (alert.get("title") or "").lower()
    message = (alert.get("message") or "").lower()
    haystack = f"{title} {message}"

    cursor = db.runbooks.find({}, {"_id": 0}).limit(100)
    matches = []
    async for rb in cursor:
        score = 0
        if device_type and (not rb.get("device_types") or device_type in rb["device_types"]):
            score += 2 if device_type in (rb.get("device_types") or []) else 0
        if severity and rb.get("severity_match") and severity in rb["severity_match"]:
            score += 1
        for kw in (rb.get("alert_keywords") or []):
            if kw in haystack:
                score += 3
        if score > 0:
            rb["_match_score"] = score
            matches.append(rb)
    matches.sort(key=lambda x: x.get("_match_score", 0), reverse=True)
    return {"alert": alert, "matches": matches[:5]}
