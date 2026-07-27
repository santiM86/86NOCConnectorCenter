"""Escalation config endpoints (admin) + manual trigger."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import List

from database import db
from deps import get_current_user
import escalation as escalation_service

router = APIRouter(prefix="/api/escalation", tags=["escalation"])


def _require_admin(user: dict):
    if user.get("role") != "admin":
        raise HTTPException(403, "Solo gli admin possono modificare l'escalation")


class EscalationConfig(BaseModel):
    enabled: bool = False
    wait_minutes: int = Field(5, ge=1, le=1440)
    severities: List[str] = ["critical"]
    escalate_to_roles: List[str] = ["admin"]


@router.get("/config")
async def get_config(current_user: dict = Depends(get_current_user)):
    return await escalation_service.get_config(db)


@router.put("/config")
async def update_config(
    cfg: EscalationConfig, current_user: dict = Depends(get_current_user)
):
    _require_admin(current_user)
    allowed_sev = {"critical", "high", "medium", "low"}
    allowed_roles = {"admin", "operator", "viewer"}
    for s in cfg.severities:
        if s not in allowed_sev:
            raise HTTPException(400, f"Severity non valida: {s}")
    for r in cfg.escalate_to_roles:
        if r not in allowed_roles:
            raise HTTPException(400, f"Ruolo non valido: {r}")

    payload = cfg.model_dump()
    await escalation_service.save_config(db, payload)
    return {"success": True, "config": payload}


@router.post("/run-now")
async def run_now(current_user: dict = Depends(get_current_user)):
    """Admin-only: esegue subito un ciclo di escalation e ritorna quanti alert sono stati escalati."""
    _require_admin(current_user)
    count = await escalation_service._run_once(db)
    return {"success": True, "escalated": count}
