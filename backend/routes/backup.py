"""Backup monitoring routes - Hornetsecurity VM Backup + Hyper-V integration."""
import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from database import db
from deps import get_current_user, validate_api_key

logger = logging.getLogger("backup")
router = APIRouter(prefix="/api", tags=["backup"])


@router.post("/backup/process-status")
async def process_backup_status(request: Request):
    """Receive backup status data from the connector."""
    client_data = await validate_api_key(request)
    body = await request.json()

    now = datetime.now(timezone.utc).isoformat()
    client_id = client_data["id"]

    vms = body.get("vms", [])
    summary = body.get("summary", {})
    hyperv_vms = body.get("hyperv_vms", [])

    # Store current status
    status_doc = {
        "client_id": client_id,
        "vms": vms,
        "summary": summary,
        "hyperv_vms": hyperv_vms,
        "altaro_connected": body.get("altaro_connected", False),
        "hyperv_connected": body.get("hyperv_connected", False),
        "updated_at": now,
    }
    await db.backup_status.update_one(
        {"client_id": client_id},
        {"$set": status_doc},
        upsert=True
    )

    # Store history snapshot (one per hour max)
    hour_bucket = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0).isoformat()
    existing = await db.backup_history.find_one({
        "client_id": client_id, "hour_bucket": hour_bucket
    })
    if not existing:
        history_doc = {
            "client_id": client_id,
            "hour_bucket": hour_bucket,
            "timestamp": now,
            "total_vms": summary.get("total_vms", 0),
            "backup_ok": summary.get("backup_ok", 0),
            "backup_warning": summary.get("backup_warning", 0),
            "backup_failed": summary.get("backup_failed", 0),
            "backup_missing": summary.get("backup_missing", 0),
        }
        await db.backup_history.insert_one(history_doc)

    # Cleanup old history (keep 30 days)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    await db.backup_history.delete_many({"timestamp": {"$lt": cutoff}})

    # Generate alerts for failed/missing backups
    for vm in vms:
        if vm.get("backup_status") in ("failed", "missing"):
            severity = "critical" if vm["backup_status"] == "failed" else "high"
            title = f"Backup {'FALLITO' if vm['backup_status'] == 'failed' else 'MANCANTE'}: {vm.get('vm_name', 'Unknown')}"

            existing_alert = await db.alerts.find_one({
                "client_id": client_id,
                "device_name": vm.get("vm_name", ""),
                "alert_type": "backup_failure",
                "resolved": {"$ne": True},
            })
            if not existing_alert:
                alert = {
                    "client_id": client_id,
                    "severity": severity,
                    "title": title,
                    "description": f"VM: {vm.get('vm_name')} - Ultimo backup: {vm.get('last_backup_time', 'Mai')}",
                    "device_name": vm.get("vm_name", ""),
                    "device_ip": "",
                    "alert_type": "backup_failure",
                    "source": "backup_monitor",
                    "resolved": False,
                    "created_at": now,
                }
                await db.alerts.insert_one(alert)
                try:
                    import webpush as _wp
                    await _wp.notify_new_alert(db, alert)
                except Exception:
                    pass
                logger.warning(f"Backup alert: {title}")

    # Auto-resolve alerts for VMs that are now OK
    for vm in vms:
        if vm.get("backup_status") == "success":
            await db.alerts.update_many(
                {
                    "client_id": client_id,
                    "device_name": vm.get("vm_name", ""),
                    "alert_type": "backup_failure",
                    "resolved": {"$ne": True},
                },
                {"$set": {"resolved": True, "resolved_at": now, "resolved_by": "auto"}}
            )

    return {"status": "ok", "vms_processed": len(vms)}


@router.get("/backup/dashboard/{client_id}")
async def backup_dashboard(client_id: str, current_user: dict = Depends(get_current_user)):
    """Get backup monitoring dashboard data for a client."""
    status = await db.backup_status.find_one({"client_id": client_id}, {"_id": 0})
    if not status:
        return {
            "client_id": client_id,
            "has_data": False,
            "vms": [],
            "hyperv_vms": [],
            "summary": {"total_vms": 0, "backup_ok": 0, "backup_warning": 0, "backup_failed": 0, "backup_missing": 0},
            "altaro_connected": False,
            "hyperv_connected": False,
        }

    status["has_data"] = True
    return status


@router.get("/backup/history/{client_id}")
async def backup_history(client_id: str, days: int = 7, current_user: dict = Depends(get_current_user)):
    """Get backup status history for charts."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    records = await db.backup_history.find(
        {"client_id": client_id, "timestamp": {"$gte": cutoff}},
        {"_id": 0}
    ).sort("timestamp", 1).to_list(1000)
    return {"client_id": client_id, "days": days, "data": records}


@router.get("/backup/vm/{client_id}/{vm_name}")
async def backup_vm_detail(client_id: str, vm_name: str, current_user: dict = Depends(get_current_user)):
    """Get detailed backup info for a specific VM."""
    status = await db.backup_status.find_one({"client_id": client_id}, {"_id": 0})
    if not status:
        raise HTTPException(status_code=404, detail="Nessun dato backup")

    vm = next((v for v in status.get("vms", []) if v.get("vm_name") == vm_name), None)
    hyperv = next((h for h in status.get("hyperv_vms", []) if h.get("name") == vm_name), None)

    if not vm and not hyperv:
        raise HTTPException(status_code=404, detail="VM non trovata")

    # Get alert history for this VM
    alerts = await db.alerts.find(
        {"client_id": client_id, "device_name": vm_name, "alert_type": "backup_failure"},
        {"_id": 0}
    ).sort("created_at", -1).to_list(20)

    return {
        "vm_name": vm_name,
        "backup": vm,
        "hyperv": hyperv,
        "alerts": alerts,
    }


@router.get("/backup/summary-all")
async def backup_summary_all(current_user: dict = Depends(get_current_user)):
    """Get backup summary across all clients (for TV dashboard)."""
    statuses = await db.backup_status.find({}, {"_id": 0}).to_list(100)

    total = {"total_vms": 0, "backup_ok": 0, "backup_warning": 0, "backup_failed": 0, "backup_missing": 0}
    clients = []

    for s in statuses:
        summary = s.get("summary", {})
        total["total_vms"] += summary.get("total_vms", 0)
        total["backup_ok"] += summary.get("backup_ok", 0)
        total["backup_warning"] += summary.get("backup_warning", 0)
        total["backup_failed"] += summary.get("backup_failed", 0)
        total["backup_missing"] += summary.get("backup_missing", 0)

        client = await db.clients.find_one({"id": s["client_id"]}, {"_id": 0, "api_key": 0})
        client_name = client.get("name", s["client_id"]) if client else s["client_id"]

        failed_vms = [v.get("vm_name") for v in s.get("vms", []) if v.get("backup_status") in ("failed", "missing")]

        clients.append({
            "client_id": s["client_id"],
            "client_name": client_name,
            "summary": summary,
            "altaro_connected": s.get("altaro_connected", False),
            "updated_at": s.get("updated_at", ""),
            "failed_vms": failed_vms,
        })

    return {"total": total, "clients": clients}
