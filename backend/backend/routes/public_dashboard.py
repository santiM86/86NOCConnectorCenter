"""Public Dashboard - Shareable client status page (no auth required)."""
import logging
import uuid
import hashlib
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Depends
from database import db
from deps import get_current_user

logger = logging.getLogger("public_dashboard")
router = APIRouter(prefix="/api/public", tags=["public-dashboard"])


def generate_share_token(client_id: str) -> str:
    """Generate a deterministic but opaque share token."""
    return hashlib.sha256(f"86bit-noc-{client_id}-share".encode()).hexdigest()[:16]


@router.post("/dashboard/create")
async def create_public_dashboard(body: dict, current_user: dict = Depends(get_current_user)):
    """Create or update a public dashboard link for a client."""
    client_id = body.get("client_id", "")
    client = await db.clients.find_one({"id": client_id}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Cliente non trovato")

    token = generate_share_token(client_id)
    now = datetime.now(timezone.utc).isoformat()

    await db.public_dashboards.update_one(
        {"client_id": client_id},
        {"$set": {
            "client_id": client_id,
            "client_name": client.get("name", ""),
            "token": token,
            "enabled": body.get("enabled", True),
            "show_alerts": body.get("show_alerts", True),
            "show_devices": body.get("show_devices", True),
            "show_sla": body.get("show_sla", True),
            "updated_at": now,
            "created_by": current_user.get("email", ""),
        }},
        upsert=True,
    )
    return {"token": token, "client_id": client_id, "enabled": True}


@router.get("/dashboard/{token}")
async def get_public_dashboard(token: str):
    """Get public dashboard data (NO AUTH REQUIRED)."""
    config = await db.public_dashboards.find_one({"token": token}, {"_id": 0})
    if not config or not config.get("enabled"):
        raise HTTPException(status_code=404, detail="Dashboard non trovata o disabilitata")

    client_id = config["client_id"]
    client_name = config.get("client_name", "")

    result = {
        "client_name": client_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    if config.get("show_devices", True):
        devices = await db.device_poll_status.find(
            {"client_id": client_id}, {"_id": 0}
        ).to_list(500)
        online = sum(1 for d in devices if d.get("reachable"))
        result["devices"] = {
            "total": len(devices),
            "online": online,
            "offline": len(devices) - online,
            "list": [{
                "name": d.get("device_name", ""),
                "ip": d.get("device_ip", ""),
                "reachable": d.get("reachable", False),
                "type": d.get("device_type", ""),
                "ping_ms": d.get("ping_ms"),
            } for d in devices],
        }

    if config.get("show_alerts", True):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        alerts = await db.alerts.find(
            {"client_id": client_id, "created_at": {"$gte": cutoff}, "status": "active"},
            {"_id": 0, "title": 1, "severity": 1, "device_name": 1, "created_at": 1}
        ).sort("created_at", -1).to_list(20)
        result["alerts"] = {
            "active_count": len(alerts),
            "list": alerts,
        }

    if config.get("show_sla", True):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        pipeline = [
            {"$match": {"client_id": client_id, "timestamp": {"$gte": cutoff}}},
            {"$group": {
                "_id": None,
                "total": {"$sum": 1},
                "up": {"$sum": {"$cond": ["$reachable", 1, 0]}},
            }},
        ]
        sla_result = await db.metrics_history.aggregate(pipeline).to_list(1)
        if sla_result:
            pct = round((sla_result[0]["up"] / sla_result[0]["total"]) * 100, 2) if sla_result[0]["total"] > 0 else 0
            result["sla"] = {"overall_pct": pct, "period_days": 30}
        else:
            result["sla"] = {"overall_pct": None, "period_days": 30}

    return result


@router.get("/dashboard/config/{client_id}")
async def get_dashboard_config(client_id: str, current_user: dict = Depends(get_current_user)):
    """Get public dashboard config for a client (admin only)."""
    config = await db.public_dashboards.find_one({"client_id": client_id}, {"_id": 0})
    return config or {"client_id": client_id, "enabled": False, "token": None}


@router.post("/dashboard/toggle")
async def toggle_public_dashboard(body: dict, current_user: dict = Depends(get_current_user)):
    """Enable or disable a public dashboard."""
    client_id = body.get("client_id", "")
    enabled = body.get("enabled", False)
    await db.public_dashboards.update_one(
        {"client_id": client_id},
        {"$set": {"enabled": enabled}}
    )
    return {"status": "ok", "enabled": enabled}
