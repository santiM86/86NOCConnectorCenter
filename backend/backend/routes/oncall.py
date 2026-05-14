"""On-Call rotation API — schedule and current-on-call endpoints."""
import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from database import db
from deps import get_current_user
import oncall as oncall_service

router = APIRouter(prefix="/api/oncall", tags=["oncall"])


class OnCallSlot(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    day_of_week: int = Field(..., ge=0, le=6, description="0=Mon, 6=Sun")
    start: str = Field(..., description="HH:MM")
    end: str = Field(..., description="HH:MM")
    user_id: str
    user_email: str | None = None
    label: str | None = ""


class OnCallConfig(BaseModel):
    rotation_enabled: bool = False
    timezone: str = "Europe/Rome"
    slots: List[OnCallSlot] = []


def _require_admin(user: dict):
    if user.get("role") != "admin":
        raise HTTPException(403, "Solo gli admin possono modificare la rotazione on-call")


def _validate_hhmm(s: str, field: str):
    try:
        h, m = s.split(":")
        h_i, m_i = int(h), int(m)
        if not (0 <= h_i <= 23 and 0 <= m_i <= 59):
            raise ValueError
    except Exception:
        raise HTTPException(400, f"{field} deve essere HH:MM (es. 08:00)")


@router.get("/schedule")
async def get_schedule(current_user: dict = Depends(get_current_user)):
    """Return the full on-call schedule."""
    cfg = await oncall_service.get_config(db)
    return cfg


@router.put("/schedule")
async def update_schedule(cfg: OnCallConfig, current_user: dict = Depends(get_current_user)):
    """Replace the on-call schedule. Admin only."""
    _require_admin(current_user)

    for slot in cfg.slots:
        _validate_hhmm(slot.start, f"slot.{slot.id}.start")
        _validate_hhmm(slot.end, f"slot.{slot.id}.end")

        # Optional: fill user_email from user_id when missing
        if not slot.user_email:
            user = await db.users.find_one({"id": slot.user_id}, {"_id": 0, "email": 1})
            if user:
                slot.user_email = user.get("email")

    payload = cfg.model_dump()
    await oncall_service.save_config(db, payload)
    return {"success": True, "config": payload}


@router.get("/current")
async def get_current(current_user: dict = Depends(get_current_user)):
    """Return who is on-call right now (for UI banner)."""
    return await oncall_service.get_current_on_call(db)


@router.get("/users")
async def list_users(current_user: dict = Depends(get_current_user)):
    """List admin + operator users available for rotation assignment."""
    users = await db.users.find(
        {"role": {"$in": ["admin", "operator"]}},
        {"_id": 0, "id": 1, "name": 1, "email": 1, "role": 1},
    ).to_list(length=200)
    return users
