"""Incident / Ticket Management System."""
import logging
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from database import db
from deps import get_current_user

logger = logging.getLogger("incidents")
router = APIRouter(prefix="/api/incidents", tags=["incidents"])


@router.get("")
async def list_incidents(
    client_id: str = "",
    status: str = "",
    priority: str = "",
    limit: int = 100,
    current_user: dict = Depends(get_current_user)
):
    """List incidents with optional filters."""
    query = {}
    if client_id:
        query["client_id"] = client_id
    if status:
        query["status"] = status
    if priority:
        query["priority"] = priority

    incidents = await db.incidents.find(
        query, {"_id": 0}
    ).sort("created_at", -1).to_list(limit)
    return incidents


@router.post("")
async def create_incident(body: dict, current_user: dict = Depends(get_current_user)):
    """Create a new incident manually or from an alert."""
    now = datetime.now(timezone.utc).isoformat()
    incident = {
        "id": str(uuid.uuid4()),
        "title": body.get("title", "Nuovo incidente"),
        "description": body.get("description", ""),
        "client_id": body.get("client_id", ""),
        "client_name": body.get("client_name", ""),
        "device_ip": body.get("device_ip", ""),
        "device_name": body.get("device_name", ""),
        "alert_id": body.get("alert_id", ""),
        "priority": body.get("priority", "medium"),
        "status": "open",
        "assigned_to": body.get("assigned_to", ""),
        "created_by": current_user.get("email", ""),
        "created_at": now,
        "updated_at": now,
        "resolved_at": None,
        "timeline": [{
            "action": "created",
            "user": current_user.get("email", ""),
            "timestamp": now,
            "note": "Incidente creato"
        }],
        "tags": body.get("tags", []),
    }
    await db.incidents.insert_one({**incident, "_id": incident["id"]})
    incident.pop("_id", None)
    return incident


@router.get("/{incident_id}")
async def get_incident(incident_id: str, current_user: dict = Depends(get_current_user)):
    """Get single incident detail."""
    incident = await db.incidents.find_one({"id": incident_id}, {"_id": 0})
    if not incident:
        raise HTTPException(status_code=404, detail="Incidente non trovato")
    return incident


@router.patch("/{incident_id}")
async def update_incident(incident_id: str, body: dict, current_user: dict = Depends(get_current_user)):
    """Update incident status, priority, assignment, or add a note."""
    incident = await db.incidents.find_one({"id": incident_id})
    if not incident:
        raise HTTPException(status_code=404, detail="Incidente non trovato")

    now = datetime.now(timezone.utc).isoformat()
    update_fields = {"updated_at": now}
    timeline_entry = {"user": current_user.get("email", ""), "timestamp": now}

    if "status" in body:
        new_status = body["status"]
        update_fields["status"] = new_status
        timeline_entry["action"] = f"status_changed"
        timeline_entry["note"] = f"Stato cambiato a: {new_status}"
        if new_status == "resolved":
            update_fields["resolved_at"] = now

    if "priority" in body:
        update_fields["priority"] = body["priority"]
        timeline_entry["action"] = "priority_changed"
        timeline_entry["note"] = f"Priorita' cambiata a: {body['priority']}"

    if "assigned_to" in body:
        update_fields["assigned_to"] = body["assigned_to"]
        timeline_entry["action"] = "assigned"
        timeline_entry["note"] = f"Assegnato a: {body['assigned_to']}"

    if "note" in body:
        timeline_entry["action"] = "note_added"
        timeline_entry["note"] = body["note"]

    await db.incidents.update_one(
        {"id": incident_id},
        {
            "$set": update_fields,
            "$push": {"timeline": timeline_entry}
        }
    )

    updated = await db.incidents.find_one({"id": incident_id}, {"_id": 0})
    return updated


@router.delete("/{incident_id}")
async def delete_incident(incident_id: str, current_user: dict = Depends(get_current_user)):
    """Delete an incident."""
    result = await db.incidents.delete_one({"id": incident_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Incidente non trovato")
    return {"status": "ok", "message": "Incidente eliminato"}


@router.get("/stats/summary")
async def incident_stats(client_id: str = "", current_user: dict = Depends(get_current_user)):
    """Get incident statistics."""
    query = {}
    if client_id:
        query["client_id"] = client_id

    total = await db.incidents.count_documents(query)
    open_q = {**query, "status": "open"}
    in_progress_q = {**query, "status": "in_progress"}
    resolved_q = {**query, "status": "resolved"}

    open_count = await db.incidents.count_documents(open_q)
    in_progress_count = await db.incidents.count_documents(in_progress_q)
    resolved_count = await db.incidents.count_documents(resolved_q)

    pipeline = [
        {"$match": {**query, "status": {"$ne": "resolved"}}},
        {"$group": {"_id": "$priority", "count": {"$sum": 1}}},
    ]
    by_priority = await db.incidents.aggregate(pipeline).to_list(10)
    priority_map = {r["_id"]: r["count"] for r in by_priority}

    return {
        "total": total,
        "open": open_count,
        "in_progress": in_progress_count,
        "resolved": resolved_count,
        "by_priority": {
            "critical": priority_map.get("critical", 0),
            "high": priority_map.get("high", 0),
            "medium": priority_map.get("medium", 0),
            "low": priority_map.get("low", 0),
        }
    }
