"""API base di conoscenza AI + feedback sulle analisi + impostazioni memoria porte."""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import ai_knowledge as kb
from database import db
from deps import get_current_user, require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai", tags=["ai-knowledge"])


class KbEntry(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    vendor: str = Field(default="Generico", max_length=60)
    tags: list[str] = []
    content: str = Field(min_length=10, max_length=6000)
    enabled: bool = True


class Feedback(BaseModel):
    analysis_kind: str  # port_explain | port_audit | ilo
    analysis_id: Optional[str] = None
    client_id: str
    device_ip: str
    port_name: Optional[str] = None
    port_idx: Optional[int] = None
    ai_verdict: Optional[str] = None
    correct: bool
    note: Optional[str] = Field(default=None, max_length=1500)


@router.get("/knowledge")
async def list_kb(q: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    user = [d async for d in db.ai_knowledge.find({}, {"_id": 0}).sort("created_at", -1)]
    builtin = [{**e, "source": "builtin"} for e in kb.BUILTIN_KB]
    items = [{**u, "source": "user"} for u in user] + builtin
    if q:
        toks = kb._tokens(q)
        items = [i for i in items if kb._score(i, toks, None) >= 2.0]
    return {"total": len(items), "user_count": len(user), "builtin_count": len(builtin), "items": items}


@router.post("/knowledge")
async def add_kb(body: KbEntry, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    doc = {"id": f"user-{uuid.uuid4().hex[:8]}", **body.model_dump(), "tags": [t.strip().lower() for t in body.tags if t.strip()],
           "created_at": kb.now_iso(), "created_by": current_user.get("email")}
    await db.ai_knowledge.insert_one(dict(doc))
    return doc


@router.put("/knowledge/{kb_id}")
async def update_kb(kb_id: str, body: KbEntry, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    res = await db.ai_knowledge.update_one({"id": kb_id}, {"$set": {**body.model_dump(), "tags": [t.strip().lower() for t in body.tags if t.strip()],
                                                                    "updated_at": kb.now_iso(), "updated_by": current_user.get("email")}})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="Voce non trovata (le voci builtin non sono modificabili)")
    return {"ok": True}


@router.delete("/knowledge/{kb_id}")
async def delete_kb(kb_id: str, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    res = await db.ai_knowledge.delete_one({"id": kb_id})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Voce non trovata")
    return {"ok": True}


@router.get("/knowledge/search")
async def search_kb(text: str, vendor: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    return {"items": await kb.search_kb(db, text, vendor)}


@router.post("/feedback")
async def add_feedback(body: Feedback, current_user: dict = Depends(get_current_user)):
    doc = {"id": str(uuid.uuid4()), **body.model_dump(), "by": current_user.get("email"), "created_at": kb.now_iso()}
    await db.ai_feedback.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


@router.get("/feedback")
async def list_feedback(client_id: Optional[str] = None, device_ip: Optional[str] = None, limit: int = 100,
                        current_user: dict = Depends(get_current_user)):
    q: dict = {}
    if client_id:
        q["client_id"] = client_id
    if device_ip:
        q["device_ip"] = device_ip
    items = [d async for d in db.ai_feedback.find(q, {"_id": 0}).sort("created_at", -1).limit(min(limit, 500))]
    tot = await db.ai_feedback.count_documents({})
    ok = await db.ai_feedback.count_documents({"correct": True})
    return {"items": items, "stats": {"total": tot, "correct": ok, "accuracy_pct": round(100 * ok / tot) if tot else None}}


@router.get("/cases")
async def cases(client_id: str, device_ip: str, port_name: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    return {"items": await kb.case_memory(db, client_id, device_ip, port_name)}


class PortMemorySettings(BaseModel):
    learning_days: int = Field(ge=1, le=60)


@router.get("/port-memory/settings")
async def get_pm_settings(current_user: dict = Depends(get_current_user)):
    import port_memory as pm
    pm._LD_CACHE["at"] = None
    return {"learning_days": await pm.refresh_learning_days(db)}


@router.put("/port-memory/settings")
async def put_pm_settings(body: PortMemorySettings, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    import port_memory as pm
    await db.alert_engine_config.update_one({"_id": "global"}, {"$set": {"port_memory_learning_days": body.learning_days}}, upsert=True)
    pm._LD_CACHE["at"] = None
    logger.info("port memory learning_days=%s by %s", body.learning_days, current_user.get("email"))
    return {"learning_days": await pm.refresh_learning_days(db)}
