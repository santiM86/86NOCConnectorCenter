"""Path Trace History + ISP outage correlation per la Diagnosi Percorso.

- Salva ogni traceroute (per sonda+destinazione) per confrontare, durante un
  guasto, il percorso attuale con l'ultimo percorso "buono" (reached=True) e
  capire ESATTAMENTE quale hop e' cambiato/sparito.
- Espone gli outage OPERATORE attivi (ASN) per correlarli col carrier trovato
  nel traceroute (risposta immediata: "l'operatore X e' in guasto diffuso ora").
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from database import db
from deps import get_current_user

router = APIRouter(prefix="/api/path-trace", tags=["path-trace"])


@router.post("/history")
async def save_trace(payload: dict, current_user: dict = Depends(get_current_user)):
    """Salva un risultato di traceroute. Body: {probe, target, mode, reached, hops[]}."""
    probe = (payload.get("probe") or "").strip()
    target = (payload.get("target") or "").strip()
    if not probe or not target:
        return {"ok": False, "error": "probe/target mancanti"}
    doc = {
        "id": str(uuid.uuid4()),
        "probe": probe,
        "target": target,
        "mode": payload.get("mode") or "",
        "reached": bool(payload.get("reached")),
        "hops": payload.get("hops") or [],
        "hop_count": len(payload.get("hops") or []),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "by": current_user.get("email", ""),
    }
    await db.path_trace_history.insert_one(doc)
    # Ritenzione: teniamo gli ultimi 50 per (probe,target).
    old = await db.path_trace_history.find(
        {"probe": probe, "target": target}, {"_id": 0, "id": 1}
    ).sort("created_at", -1).skip(50).to_list(500)
    if old:
        await db.path_trace_history.delete_many({"id": {"$in": [o["id"] for o in old]}})
    return {"ok": True, "id": doc["id"]}


@router.get("/history/last-good")
async def last_good(probe: str, target: str, current_user: dict = Depends(get_current_user)):
    """Ultimo percorso 'buono' (reached=True) per confronto/diff."""
    doc = await db.path_trace_history.find_one(
        {"probe": probe, "target": target, "reached": True}, {"_id": 0},
        sort=[("created_at", -1)],
    )
    return {"found": bool(doc), "trace": doc}


@router.get("/active-isp-outages")
async def active_isp_outages(current_user: dict = Depends(get_current_user)):
    """Outage operatore ATTIVI (ASN + nomi) per correlazione col carrier del trace."""
    rows = await db.alerts.find(
        {"status": "active", "source_type": "isp_outage_watch"},
        {"_id": 0, "id": 1, "title": 1, "isp_outage": 1},
    ).to_list(100)
    out = []
    for a in rows:
        io = a.get("isp_outage") or {}
        out.append({
            "id": a.get("id"),
            "title": a.get("title", ""),
            "asn": io.get("asn") or "",
            "isp_name": io.get("isp_name") or io.get("asn_name") or "",
            "summary": io.get("summary") or "",
        })
    return {"outages": out}
