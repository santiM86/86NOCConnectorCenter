"""Gestione TEMPERATURE in blocco su tutti i dispositivi (cross-cliente).
Vista unica: temperatura attuale, soglia EFFETTIVA e sua provenienza, override.
Azioni bulk: imposta/rimuovi override su N device di N clienti in una chiamata."""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from database import db
from deps import get_current_user, require_admin
from device_profiles import get_effective_profile
from display_name import best_display_name
from hardware_alerts import (
    _DEFAULT_TEMP_THRESHOLDS, _DEFAULT_TEMP_FALLBACK, _eval_percent, _temp_ok,
    _threshold, resolve_temp_thresholds,
)

router = APIRouter(prefix="/api/temperature", tags=["temperature"])

_OVERRIDE_FIELDS = ("temp_warn_c", "temp_crit_c")


def _source(md: dict, cbt: dict, dtype: str, prof_thr: dict) -> str:
    if any(isinstance(md.get(f), (int, float)) for f in _OVERRIDE_FIELDS):
        return "device"
    if (cbt or {}).get(dtype):
        return "cliente"
    if _threshold(prof_thr or {}, "temp_warn_c") is not None or _threshold(prof_thr or {}, "temp_crit_c") is not None:
        return "profilo"
    return "default"


@router.get("/overview")
async def temperature_overview(current_user: dict = Depends(get_current_user)):
    clients = {c["id"]: c.get("name") or c["id"] async for c in db.clients.find({}, {"_id": 0, "id": 1, "name": 1})}
    thr_by_client = {t["client_id"]: t.get("temp_by_type") or {} async for t in
                     db.alert_thresholds.find({}, {"_id": 0, "client_id": 1, "temp_by_type": 1})}
    polls = {(p["client_id"], p["device_ip"]): p async for p in db.device_poll_status.find(
        {"vendor_metrics": {"$exists": True}},
        {"_id": 0, "client_id": 1, "device_ip": 1, "vendor_metrics": 1, "profile_key": 1, "sys_name": 1,
         "hostname": 1, "updated_at": 1, "last_poll": 1})}
    prof_cache: Dict[str, dict] = {}
    rows: List[Dict[str, Any]] = []
    async for md in db.managed_devices.find({}, {"_id": 0}):
        cid, ip = md.get("client_id"), md.get("ip") or md.get("ip_address")
        if not cid or not ip or cid not in clients:
            continue
        pd = polls.get((cid, ip)) or {}
        pk = md.get("profile_key") or pd.get("profile_key")
        vm = pd.get("vendor_metrics") or {}
        _, cur = _eval_percent(vm, "temp", None, None, ok=_temp_ok)
        has_override = any(isinstance(md.get(f), (int, float)) for f in _OVERRIDE_FIELDS)
        if cur is None and not has_override and not pk:
            continue
        if pk and pk not in prof_cache:
            prof_cache[pk] = (await get_effective_profile(db, pk) or {}).get("thresholds") or {}
        prof_thr = prof_cache.get(pk or "", {})
        dtype = (md.get("device_type") or "").lower()
        cbt = thr_by_client.get(cid, {})
        warn, crit = resolve_temp_thresholds(prof_thr, dtype, {"warn": md.get("temp_warn_c"), "crit": md.get("temp_crit_c")}, cbt)
        state = "ok"
        if cur is not None:
            state = "crit" if (crit is not None and cur >= crit) else "warn" if (warn is not None and cur >= warn) else "ok"
        rows.append({
            "client_id": cid, "client_name": clients[cid], "ip": ip,
            "name": best_display_name(md, pd, ip),
            "device_type": dtype or "—", "profile_key": pk or "",
            "temp_c": cur, "warn_c": warn, "crit_c": crit,
            "source": _source(md, cbt, dtype, prof_thr),
            "override_warn": md.get("temp_warn_c"), "override_crit": md.get("temp_crit_c"),
            "state": state,
            "last_poll": pd.get("last_poll") or pd.get("updated_at"),
        })
    rows.sort(key=lambda r: ({"crit": 0, "warn": 1, "ok": 2}[r["state"]], r["client_name"], r["name"]))
    defaults = {k: {"warn": v[0], "crit": v[1]} for k, v in _DEFAULT_TEMP_THRESHOLDS.items()}
    return {"devices": rows, "defaults": defaults,
            "fallback": {"warn": _DEFAULT_TEMP_FALLBACK[0], "crit": _DEFAULT_TEMP_FALLBACK[1]}}


@router.post("/bulk")
async def temperature_bulk(payload: dict, current_user: dict = Depends(get_current_user)):
    """Body: {targets:[{client_id, ip}], warn?: n|null, crit?: n|null, clear?: bool}
    clear=true rimuove l'override (il device torna a cliente/profilo/default)."""
    require_admin(current_user)
    targets = payload.get("targets") or []
    if not isinstance(targets, list) or not targets:
        raise HTTPException(status_code=400, detail="targets[] obbligatorio")
    clear = bool(payload.get("clear"))
    upd: Dict[str, Any] = {}
    if clear:
        upd["$unset"] = {f: "" for f in _OVERRIDE_FIELDS}
    else:
        sets: Dict[str, Any] = {}
        for key, fld in (("warn", "temp_warn_c"), ("crit", "temp_crit_c")):
            if key in payload and payload[key] not in (None, ""):
                try:
                    v = float(payload[key])
                except (TypeError, ValueError):
                    raise HTTPException(status_code=400, detail=f"{key} non numerico")
                if not 0 <= v <= 150:
                    raise HTTPException(status_code=400, detail=f"{key} fuori range 0–150 °C")
                sets[fld] = v
        if not sets:
            raise HTTPException(status_code=400, detail="Indicare warn e/o crit oppure clear=true")
        if "temp_warn_c" in sets and "temp_crit_c" in sets and sets["temp_warn_c"] > sets["temp_crit_c"]:
            raise HTTPException(status_code=400, detail="warn deve essere ≤ crit")
        upd["$set"] = sets
    upd.setdefault("$set", {}).update({
        "temp_override_set_by": current_user.get("email"),
        "temp_override_set_at": datetime.now(timezone.utc).isoformat(),
    })
    by_client: Dict[str, List[str]] = {}
    for t in targets:
        if isinstance(t, dict) and t.get("client_id") and t.get("ip"):
            by_client.setdefault(t["client_id"], []).append(t["ip"])
    n = 0
    for cid, ips in by_client.items():
        r = await db.managed_devices.update_many(
            {"client_id": cid, "$or": [{"ip": {"$in": ips}}, {"ip_address": {"$in": ips}}]}, upd)
        n += r.modified_count
    return {"status": "ok", "updated": n, "clients": len(by_client), "cleared": clear}
