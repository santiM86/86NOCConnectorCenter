"""Endpoint CMDB unificata (entity resolution)."""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional

from deps import get_current_user
from database import db
import entity_resolver as er
import graph_builder as gb

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
        r = await gb.build_relationships(db, client_id)
        return {"client_id": client_id, "entities": n, "relationships": r}
    ents = await er.reconcile_all(db)
    rels = await gb.build_all(db)
    return {"result": ents, "relationships": rels}


@router.get("/entities/{entity_id}/impact")
async def entity_impact(entity_id: str, current_user: dict = Depends(get_current_user)):
    """Impact analysis: entita' a valle impattate se questa cade."""
    res = await gb.compute_impact(db, entity_id)
    if not res.get("found"):
        raise HTTPException(status_code=404, detail="Entita' non trovata")
    return res


@router.get("/graph")
async def graph(client_id: str, current_user: dict = Depends(get_current_user)):
    """Nodi + archi del grafo dipendenze di un cliente (per la mappa)."""
    nodes = await db.cmdb_entities.find(
        {"client_id": client_id},
        {"_id": 0, "entity_id": 1, "name": 1, "primary_ip": 1, "device_type": 1, "is_vital": 1},
    ).to_list(5000)
    edges = await db.cmdb_relationships.find(
        {"client_id": client_id},
        {"_id": 0, "src_entity": 1, "dst_entity": 1, "rel_type": 1, "via_port": 1},
    ).to_list(20000)
    return {"nodes": nodes, "edges": edges}
