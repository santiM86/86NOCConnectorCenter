"""API Regole Alert Engine: regole su metrica, dipendenze padre → figli, gruppi MAC condiviso, storico MAC."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from alert_rules import METRICS, nic_groups, run_metric_rules
from database import db
from deps import get_current_user, require_admin
from mac_follow import norm_mac

router = APIRouter(prefix="/api", tags=["alert-rules"])


class MetricRuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    metric: Literal["packet_loss", "latency", "cpu", "ram", "disk", "temperature"]
    operator: Literal[">", "<"] = ">"
    threshold: float
    duration_min: int = Field(ge=0, le=1440, default=15)
    severity: Literal["low", "medium", "high", "critical"] = "high"
    scope: Literal["all", "client", "device"] = "all"
    client_id: Optional[str] = None
    device_ip: Optional[str] = None
    enabled: bool = True


class DependencyIn(BaseModel):
    client_id: str
    parent_ip: str
    child_ips: list[str] = Field(min_length=1)
    source: Literal["manual", "suggested"] = "manual"


class NicHostIn(BaseModel):
    mac: str
    host_ip: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_scope(r: MetricRuleIn) -> dict:
    if r.scope in ("client", "device") and not r.client_id:
        raise HTTPException(400, "Seleziona il cliente per questa regola")
    if r.scope == "device" and not r.device_ip:
        raise HTTPException(400, "Seleziona il dispositivo per questa regola")
    d = r.model_dump()
    if r.scope == "all":
        d["client_id"] = None
        d["device_ip"] = None
    elif r.scope == "client":
        d["device_ip"] = None
    return d


@router.get("/alert-rules/metrics")
async def list_metrics(current_user: dict = Depends(get_current_user)):
    return [{"key": k, "label": v} for k, v in METRICS.items()]


@router.get("/alert-rules")
async def list_rules(current_user: dict = Depends(get_current_user)):
    return await db.alert_metric_rules.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)


@router.post("/alert-rules")
async def create_rule(body: MetricRuleIn, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    doc = {"id": str(uuid.uuid4()), **_validate_scope(body), "created_at": _now(), "created_by": current_user.get("email")}
    await db.alert_metric_rules.insert_one(dict(doc))
    return doc


@router.put("/alert-rules/{rule_id}")
async def update_rule(rule_id: str, body: MetricRuleIn, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    res = await db.alert_metric_rules.update_one({"id": rule_id}, {"$set": {**_validate_scope(body), "updated_at": _now()}})
    if not res.matched_count:
        raise HTTPException(404, "Regola non trovata")
    await db.metric_rule_state.delete_many({"rule_id": rule_id})
    return await db.alert_metric_rules.find_one({"id": rule_id}, {"_id": 0})


@router.delete("/alert-rules/{rule_id}")
async def delete_rule(rule_id: str, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    await db.alert_metric_rules.delete_one({"id": rule_id})
    await db.metric_rule_state.delete_many({"rule_id": rule_id})
    return {"ok": True}


@router.post("/alert-rules/run")
async def run_rules_now(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    return {"ok": True, "emitted": await run_metric_rules()}


@router.get("/alert-dependencies")
async def list_dependencies(client_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    q = {"client_id": client_id} if client_id else {}
    return await db.alert_dependencies.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)


@router.post("/alert-dependencies")
async def create_dependency(body: DependencyIn, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    kids = sorted({c.strip() for c in body.child_ips if c.strip() and c.strip() != body.parent_ip})
    if not kids:
        raise HTTPException(400, "Seleziona almeno un figlio diverso dal padre")
    existing = await db.alert_dependencies.find_one({"client_id": body.client_id, "parent_ip": body.parent_ip}, {"_id": 0})
    if existing:
        merged = sorted(set(existing.get("child_ips") or []) | set(kids))
        await db.alert_dependencies.update_one({"id": existing["id"]}, {"$set": {"child_ips": merged, "updated_at": _now()}})
        return {**existing, "child_ips": merged}
    doc = {"id": str(uuid.uuid4()), "client_id": body.client_id, "parent_ip": body.parent_ip, "child_ips": kids,
           "source": body.source, "created_at": _now(), "created_by": current_user.get("email")}
    await db.alert_dependencies.insert_one(dict(doc))
    return doc


@router.delete("/alert-dependencies/{dep_id}")
async def delete_dependency(dep_id: str, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    await db.alert_dependencies.delete_one({"id": dep_id})
    return {"ok": True}


@router.get("/alert-dependencies/suggestions")
async def dependency_suggestions(client_id: str, current_user: dict = Depends(get_current_user)):
    """Proposte 'host → sue VM' dai gruppi MAC condiviso non ancora coperti da una dipendenza."""
    deps = await db.alert_dependencies.find({"client_id": client_id}, {"_id": 0}).to_list(1000)
    covered = {(d["parent_ip"], c) for d in deps for c in d.get("child_ips") or []}
    out = []
    for g in await nic_groups(client_id):
        missing = [c for c in g["child_ips"] if (g["host_ip"], c) not in covered]
        if missing:
            out.append({**g, "child_ips": missing})
    return out


@router.get("/clients/{client_id}/nic-groups")
async def get_nic_groups(client_id: str, current_user: dict = Depends(get_current_user)):
    return await nic_groups(client_id)


@router.post("/clients/{client_id}/nic-groups/host")
async def set_nic_host(client_id: str, body: NicHostIn, current_user: dict = Depends(get_current_user)):
    mac = norm_mac(body.mac)
    groups = {g["mac"]: g for g in await nic_groups(client_id)}
    g = groups.get(mac)
    if not g or body.host_ip not in {m["ip"] for m in g["members"]}:
        raise HTTPException(400, "Il server host deve essere uno dei dispositivi che condividono questo MAC")
    await db.nic_hosts.update_one({"client_id": client_id, "mac": mac},
                                  {"$set": {"host_ip": body.host_ip, "set_by": current_user.get("email"), "set_at": _now()}}, upsert=True)
    return {"ok": True, "mac": mac, "host_ip": body.host_ip}


@router.get("/devices/by-ip/{device_ip}/mac-history")
async def mac_history(device_ip: str, client_id: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    q = {"$or": [{"ip": device_ip}, {"ip_address": device_ip}]}
    if client_id:
        q["client_id"] = client_id
    md = await db.managed_devices.find_one(q, {"_id": 0, "mac": 1, "mac_address": 1, "mac_history": 1, "mac_previous": 1,
                                               "mac_changed_at": 1, "mac_change_pending": 1})
    if not md:
        return {"current_mac": None, "history": [], "pending": None}
    hist = sorted(md.get("mac_history") or [], key=lambda h: h.get("at") or "", reverse=True)
    return {"current_mac": norm_mac(md.get("mac") or md.get("mac_address")) or None, "history": hist,
            "pending": md.get("mac_change_pending")}
