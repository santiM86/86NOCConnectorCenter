"""Endpoint del Situation Engine — diagnosi unificata per dispositivo/cliente."""
from fastapi import APIRouter, Depends, HTTPException

from deps import get_current_user
from database import db
import situation_engine as se

router = APIRouter(prefix="/api", tags=["situation"])


@router.get("/devices/by-ip/{device_ip}/diagnosis")
async def device_diagnosis(
    device_ip: str,
    client_id: str | None = None,
    current_user: dict = Depends(get_current_user),
):
    """Verdetto UNICO e autorevole per un dispositivo (fusione di tutti i domini)."""
    result = await se.diagnose_device(db, device_ip, client_id=client_id)
    if not result.get("found"):
        raise HTTPException(status_code=404, detail="Dispositivo non trovato")
    return result


@router.get("/clients/{client_id}/diagnosis")
async def client_diagnosis(
    client_id: str,
    only_problems: bool = True,
    current_user: dict = Depends(get_current_user),
):
    """Diagnosi unificata di tutti i dispositivi vitali/infra di un cliente,
    ordinata per gravita' (CRITICAL -> WARNING -> UNKNOWN)."""
    return await se.diagnose_client(db, client_id, only_problems=only_problems)
