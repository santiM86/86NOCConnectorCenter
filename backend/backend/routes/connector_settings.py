"""Connector Settings — dynamic configuration pushed to connectors via heartbeat.
Admin can add/remove allowed Web Console ports without redeploying the PowerShell connector.
"""
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from typing import Any

from database import db
from deps import get_current_user

router = APIRouter(prefix="/api/connector/settings", tags=["connector-settings"])


@router.get("/allowed-ports")
async def get_allowed_ports(current_user: dict = Depends(get_current_user)):
    """Returns the dynamic allowed ports list + hard-coded defaults for reference."""
    doc = await db.connector_settings.find_one({"key": "allowed_ports_extra"}, {"_id": 0})
    extra = (doc or {}).get("value") or []
    return {
        "defaults": [
            80, 443, 8080, 8443, 8000, 8888, 4443, 4080, 9090, 10000,
            5000, 5001, 8006, 81, 8088, 3000, 19999, 4444, 2222, 8083, 17988, 17990,
        ],
        "extra": extra,
        "updated_by": (doc or {}).get("updated_by"),
        "updated_at": (doc or {}).get("updated_at"),
    }


@router.put("/allowed-ports")
async def update_allowed_ports(body: dict, current_user: dict = Depends(get_current_user)):
    """Admin only. Body: {ports: [int]}. Replaces the extra list.
    Defaults cannot be removed (always in whitelist).
    """
    if current_user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Solo admin")
    raw = body.get("ports") or []
    cleaned: list[int] = []
    for p in raw:
        try:
            pi = int(p)
            if 1 <= pi <= 65535:
                cleaned.append(pi)
        except (ValueError, TypeError):
            continue
    cleaned = sorted(set(cleaned))
    await db.connector_settings.update_one(
        {"key": "allowed_ports_extra"},
        {"$set": {
            "key": "allowed_ports_extra",
            "value": cleaned,
            "updated_by": current_user.get("email"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    return {"ok": True, "ports": cleaned, "count": len(cleaned)}
