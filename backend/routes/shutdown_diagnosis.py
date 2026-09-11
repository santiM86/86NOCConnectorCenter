"""API Diagnosi spegnimento (spento volutamente vs crash)."""
from fastapi import APIRouter, Depends, HTTPException

from database import db
from deps import get_current_user
from shutdown_diagnosis import diagnose

router = APIRouter(prefix="/api/devices", tags=["shutdown-diagnosis"])


@router.get("/shutdown-diagnosis/{device_ip}")
async def get_shutdown_diagnosis(device_ip: str, client_id: str = None, current_user: dict = Depends(get_current_user)):
    from .tenant_scope import resolve_device_client_id
    cid = await resolve_device_client_id(device_ip, client_id)
    if not cid:
        raise HTTPException(status_code=404, detail="Dispositivo non trovato")
    return await diagnose(db, cid, device_ip)
