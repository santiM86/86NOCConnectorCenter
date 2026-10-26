"""Admin endpoint per gestione integrazioni 3rd party (Fingerbank, ecc.)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deps import get_current_user, require_admin
from services import fingerbank_service

router = APIRouter(prefix="/api/admin/integrations", tags=["admin-integrations"])


class FingerbankSetRequest(BaseModel):
    api_key: str = Field(..., min_length=8, max_length=256)


@router.get("/fingerbank")
async def fingerbank_get(current_user: dict = Depends(get_current_user)):
    """Ritorna stato configurazione Fingerbank (senza esporre la key in chiaro).

    Output: {configured: bool, updated_at: iso, masked_key: '****abcd'}
    """
    require_admin(current_user)
    return await fingerbank_service.get_status()


@router.put("/fingerbank")
async def fingerbank_set(payload: FingerbankSetRequest, current_user: dict = Depends(get_current_user)):
    """Salva (cifrata, AES-256-GCM) la API key Fingerbank."""
    require_admin(current_user)
    try:
        await fingerbank_service.set_api_key(payload.api_key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "status": await fingerbank_service.get_status()}


@router.delete("/fingerbank")
async def fingerbank_delete(current_user: dict = Depends(get_current_user)):
    """Rimuove la API key Fingerbank dal DB."""
    require_admin(current_user)
    deleted = await fingerbank_service.delete_api_key()
    return {"ok": True, "deleted": deleted}


@router.post("/fingerbank/test")
async def fingerbank_test(current_user: dict = Depends(get_current_user)):
    """Esegue una query di test su Fingerbank con un MAC noto (HP printer)
    per verificare che la API key sia valida.
    """
    require_admin(current_user)
    if not await fingerbank_service.is_configured():
        raise HTTPException(status_code=400, detail="API key non configurata")
    result = await fingerbank_service.interrogate("00:1B:78:00:00:00")
    return {
        "ok": result is not None,
        "result": result,
        "note": "Test con MAC OUI HP. Se result e' None, la key potrebbe essere invalida o il MAC non e' nel DB Fingerbank.",
    }
