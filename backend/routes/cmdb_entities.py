"""Endpoint CMDB unificata (entity resolution)."""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional

from deps import get_current_user
from database import db
import entity_resolver as er

router = APIRouter(prefix="/api/cmdb", tags=["cmdb-entities"])


@router.get("/entities")
async def list_entities(client_id: Optional[str] = None, source: Optional[str] = None,
                        current_user: dict = Depends(get_current_user)):
    q: dict = {}
    if client_id:
        q["client_id"] = client_id
    if source:
        q["sources"] = source
    ents = await db.cmdb_entities.find(q, {"_id": 0}).sort("name", 1).limit(2000).to_list(2000)
    return {"count": len(ents), "entities": ents}


@router.get("/entities/{entity_id}")
async def get_entity(entity_id: str, current_user: dict = Depends(get_current_user)):
    ent = await db.cmdb_entities.find_one({"entity_id": entity_id}, {"_id": 0})
    if not ent:
        raise HTTPException(status_code=404, detail="Entita' non trovata")
    return ent


@router.post("/entities/rebuild")
async def rebuild(client_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    if client_id:
        n = await er.reconcile_client(db, client_id)
        return {"client_id": client_id, "entities": n}
    return {"result": await er.reconcile_all(db)}
