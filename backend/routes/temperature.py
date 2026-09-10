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
_KIND_FIELDS = {
    "general": ("temp_warn_c", "temp_crit_c", "warn", "crit"),
    "inlet": ("inlet_temp_warn_c", "inlet_temp_crit_c", "inlet_warn", "inlet_crit"),
    "disk": ("disk_temp_warn_c", "disk_temp_crit_c", "disk_warn", "disk_crit"),
}
_INLET_KEYS = ("inlet", "intake", "ambient", "ingress")


def _dov(md: dict) -> dict:
    return {ok: md.get(f) for _k, (fw, fc, ow, oc) in _KIND_FIELDS.items() for ok, f in ((ow, fw), (oc, fc))}


def _state(cur, warn, crit) -> str:
    if cur is None:
        return "ok"
    return "crit" if (crit is not None and cur >= crit) else "warn" if (warn is not None and cur >= warn) else "ok"


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
    # Ultima telemetria iLO per device → temperatura INLET (ambiente) più alta
    inlet_by_dev: Dict[tuple, float] = {}
    try:
        async for t in db.ilo_telemetry.aggregate([
            {"$sort": {"timestamp": -1}},
            {"$group": {"_id": {"c": "$client_id", "ip": "$device_ip"}, "temperatures": {"$first": "$temperatures"}}},
        ]):
            vals = [x.get("celsius") for x in (t.get("temperatures") or [])
                    if isinstance(x.get("celsius"), (int, float)) and any(k in (x.get("name") or "").lower() for k in _INLET_KEYS)]
            if vals:
                inlet_by_dev[(t["_id"].get("c"), t["_id"].get("ip"))] = max(vals)
    except Exception:  # noqa: BLE001
        pass
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
        inlet_cur = inlet_by_dev.get((cid, ip))
        disk_vals = [float(v) for v in (vm.get("diskTemperature") or {}).values()
                     if str(v).replace(".", "", 1).isdigit() and _temp_ok(float(v))] if isinstance(vm.get("diskTemperature"), dict) else []
        disk_cur = max(disk_vals) if disk_vals else None
        has_override = any(isinstance(md.get(f), (int, float)) for f in _OVERRIDE_FIELDS)
        if cur is None and inlet_cur is None and disk_cur is None and not has_override and not pk:
            continue
        if pk and pk not in prof_cache:
            prof_cache[pk] = (await get_effective_profile(db, pk) or {}).get("thresholds") or {}
        prof_thr = prof_cache.get(pk or "", {})
        dtype = (md.get("device_type") or "").lower()
        cbt = thr_by_client.get(cid, {})
        dov = _dov(md)
        warn, crit = resolve_temp_thresholds(prof_thr, dtype, dov, cbt)
        state = _state(cur, warn, crit)
        extra: Dict[str, Any] = {}
        if inlet_cur is not None or dtype == "ilo" or md.get("inlet_temp_warn_c") is not None:
            iw, ic = resolve_temp_thresholds(prof_thr, dtype, dov, cbt, kind="inlet", fallback=(warn, crit))
            extra["inlet"] = {"temp_c": inlet_cur, "warn_c": iw, "crit_c": ic, "state": _state(inlet_cur, iw, ic),
                              "override": md.get("inlet_temp_warn_c") is not None or md.get("inlet_temp_crit_c") is not None}
        if disk_cur is not None or md.get("disk_temp_warn_c") is not None:
            dw, dc = resolve_temp_thresholds(prof_thr, dtype, dov, cbt, kind="disk", fallback=(50, 60))
            extra["disk"] = {"temp_c": disk_cur, "warn_c": dw, "crit_c": dc, "state": _state(disk_cur, dw, dc),
                             "override": md.get("disk_temp_warn_c") is not None or md.get("disk_temp_crit_c") is not None}
        worst = max([state] + [e["state"] for e in extra.values()], key=lambda x: {"crit": 2, "warn": 1, "ok": 0}[x])
        rows.append({
            **extra, "worst": worst,
            "client_id": cid, "client_name": clients[cid], "ip": ip,
            "name": best_display_name(md, pd, ip),
            "device_type": dtype or "—", "profile_key": pk or "",
            "temp_c": cur, "warn_c": warn, "crit_c": crit,
            "source": _source(md, cbt, dtype, prof_thr),
            "override_warn": md.get("temp_warn_c"), "override_crit": md.get("temp_crit_c"),
            "state": state,
            "last_poll": pd.get("last_poll") or pd.get("updated_at"),
        })
    rows.sort(key=lambda r: ({"crit": 0, "warn": 1, "ok": 2}[r["worst"]], r["client_name"], r["name"]))
    defaults = {k: {"warn": v[0], "crit": v[1]} for k, v in _DEFAULT_TEMP_THRESHOLDS.items()}
    return {"devices": rows, "defaults": defaults,
            "fallback": {"warn": _DEFAULT_TEMP_FALLBACK[0], "crit": _DEFAULT_TEMP_FALLBACK[1]}}


@router.post("/bulk")
async def temperature_bulk(payload: dict, current_user: dict = Depends(get_current_user)):
    """Body: {targets:[{client_id, ip}], kind?: general|inlet|disk, warn?: n|null, crit?: n|null, clear?: bool}
    clear=true rimuove l'override del kind (il device torna a cliente/profilo/default)."""
    require_admin(current_user)
    targets = payload.get("targets") or []
    if not isinstance(targets, list) or not targets:
        raise HTTPException(status_code=400, detail="targets[] obbligatorio")
    kind = payload.get("kind") or "general"
    if kind not in _KIND_FIELDS:
        raise HTTPException(status_code=400, detail="kind deve essere general|inlet|disk")
    fw, fc, _, _ = _KIND_FIELDS[kind]
    clear = bool(payload.get("clear"))
    upd: Dict[str, Any] = {}
    if clear:
        upd["$unset"] = {fw: "", fc: ""}
    else:
        sets: Dict[str, Any] = {}
        for key, fld in (("warn", fw), ("crit", fc)):
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
        if fw in sets and fc in sets and sets[fw] > sets[fc]:
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
    return {"status": "ok", "updated": n, "clients": len(by_client), "cleared": clear, "kind": kind}
