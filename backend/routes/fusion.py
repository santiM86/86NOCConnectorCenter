"""Evidence Fusion v2 — API.

- GET  /api/fusion/certainty/{client_id}   → copertura fonti per device + verdetto v2 per i device giù + % device ≥90
- GET  /api/fusion/device/{ip}?client_id=  → registro prove completo per un device
- GET  /api/fusion/shadow?client_id=        → confronto motore v1 vs v2 (ultimo tick) + statistiche accordo
- GET/PUT /api/fusion/config                → {fusion_v2_enabled}
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import alert_engine as ae
import correlation_engine as ce
import evidence_fusion as ef
from database import db
from deps import get_current_user, require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/fusion", tags=["fusion"])
_cache: dict = {}
CACHE_S = 60


class FusionConfig(BaseModel):
    fusion_v2_enabled: bool


async def _best_pd(ip: str, cid: str) -> Optional[dict]:
    recs = await db.device_poll_status.find({"device_ip": ip, "client_id": cid}, {"_id": 0}).to_list(10)
    return await ae._best_poll_record(recs) if recs else None


async def _v2_for(md: dict, ctx: dict) -> dict:
    ip = md.get("ip") or md.get("ip_address")
    pd = await _best_pd(ip, md["client_id"])
    s = ce.gather_signals(md, pd, ctx)
    return await ef.fuse(db, md, pd, s, ce.device_family(md))


@router.get("/certainty/{client_id}")
async def certainty(client_id: str, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    hit = _cache.get(client_id)
    if hit and time.time() - hit[0] < CACHE_S:
        return hit[1]
    cfg = await ae.get_config(db)
    ctx = await ce.build_context(db, cfg)
    mds = await db.managed_devices.find({"client_id": client_id, "$or": [{"ip": {"$nin": [None, ""]}}, {"ip_address": {"$nin": [None, ""]}}]},
                                        {"_id": 0}).to_list(3000)
    sem = asyncio.Semaphore(8)

    async def one(md):
        async with sem:
            ip = md.get("ip") or md.get("ip_address")
            fam = ce.device_family(md)
            pd = await _best_pd(ip, client_id)
            s = ce.gather_signals(md, pd, ctx)
            cov = await ef.coverage(db, md, bool(s.get("datto_matched")), fam)
            row = {"ip": ip, "name": ae._best_device_name(md, ip), "device_type": md.get("device_type"), "family": fam,
                   "is_vital": bool(md.get("is_vital")), "reachable": s.get("ping"), **cov}
            if s.get("ping") is False:
                v = await ef.fuse(db, md, pd, s, fam)
                row.update({"verdict": v["root_cause"], "verdict_label": v["label"], "confidence": v["confidence"],
                            "conflict": v["conflict"], "sources_used": v["sources"], "missing": v["missing"] or cov["missing"]})
            return row

    rows = [r for r in await asyncio.gather(*(one(m) for m in mds), return_exceptions=True) if isinstance(r, dict)]
    rows.sort(key=lambda r: (r.get("reachable") is not False, r.get("max_confidence", 0), r["name"]))
    down = [r for r in rows if r.get("reachable") is False]
    out = {"client_id": client_id, "total": len(rows),
           "ready_90": sum(1 for r in rows if r["max_confidence"] >= 90),
           "down": len(down), "down_ge_90": sum(1 for r in down if (r.get("confidence") or 0) >= 90),
           "avg_max_confidence": round(sum(r["max_confidence"] for r in rows) / len(rows)) if rows else 0,
           "missing_summary": _summ(rows), "devices": rows}
    _cache[client_id] = (time.time(), out)
    return out


def _summ(rows: list) -> list:
    c: dict = {}
    for r in rows:
        for m in r.get("missing") or []:
            k = m["key"]
            c.setdefault(k, {"key": k, "count": 0, "example": m["action"], "gain": m["gain"]})["count"] += 1
    return sorted(c.values(), key=lambda x: -x["count"])


@router.get("/device/{device_ip}")
async def device_fusion(device_ip: str, client_id: str = None, current_user: dict = Depends(get_current_user)):
    from .tenant_scope import resolve_device_client_id
    cid = await resolve_device_client_id(device_ip, client_id)
    md = await db.managed_devices.find_one({"client_id": cid, "$or": [{"ip": device_ip}, {"ip_address": device_ip}]}, {"_id": 0}) if cid else None
    if not md:
        raise HTTPException(status_code=404, detail="Dispositivo non trovato")
    cfg = await ae.get_config(db)
    ctx = await ce.build_context(db, cfg)
    v = await _v2_for(md, ctx)
    v["coverage"] = await ef.coverage(db, md, bool(ce.gather_signals(md, await _best_pd(device_ip, cid), ctx).get("datto_matched")), ce.device_family(md))
    return v


@router.get("/shadow")
async def shadow(client_id: str = None, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    q = {"client_id": client_id} if client_id else {}
    rows = await db.fusion_shadow.find(q, {"_id": 0}).sort("ts", -1).to_list(500)
    agree = sum(1 for r in rows if r.get("agree"))
    return {"total": len(rows), "agree": agree, "disagree": len(rows) - agree,
            "avg_conf_v1": round(sum(r["v1"]["confidence"] for r in rows) / len(rows)) if rows else 0,
            "avg_conf_v2": round(sum(r["v2"]["confidence"] for r in rows) / len(rows)) if rows else 0,
            "v2_ge_90": sum(1 for r in rows if r["v2"]["confidence"] >= 90),
            "v1_ge_90": sum(1 for r in rows if r["v1"]["confidence"] >= 90), "rows": rows}


@router.get("/config")
async def get_cfg(current_user: dict = Depends(get_current_user)):
    cfg = await ae.get_config(db)
    return {"fusion_v2_enabled": bool(cfg.get("fusion_v2_enabled"))}


@router.put("/config")
async def put_cfg(body: FusionConfig, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    cfg = await ae.save_config(db, {"fusion_v2_enabled": body.fusion_v2_enabled})
    logger.warning("fusion v2 %s by %s", "ENABLED" if body.fusion_v2_enabled else "disabled", current_user.get("email"))
    return {"fusion_v2_enabled": bool(cfg.get("fusion_v2_enabled"))}
