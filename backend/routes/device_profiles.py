"""Device Profile routes — expose the profile library + DB overrides.

Endpoints:
- GET  /api/device-profiles              → list effective profiles (seed + overrides)
- GET  /api/device-profiles/{key}        → single profile (effective)
- POST /api/device-profiles/fingerprint  → match {sysobjectid, sysdescr} → profile
- PUT  /api/device-profiles/{key}/override → save user overrides (admin)
- DELETE /api/device-profiles/{key}/override → reset to seed (admin)
- POST /api/device-profiles/apply        → given device_ip, auto-apply profile
                                            to managed_devices/device_poll_status
"""
from __future__ import annotations
import logging
import traceback
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from typing import Any

from database import db
from deps import get_current_user
from device_profiles import PROFILES, fingerprint as _fingerprint, get_profile, SEED_VERSION

router = APIRouter(prefix="/api/device-profiles", tags=["device-profiles"])
logger = logging.getLogger("device_profiles")


async def _get_overrides_map() -> dict[str, dict]:
    """Return {key: overrides_dict} from Mongo, sanitizzando documenti corrotti."""
    out: dict[str, dict] = {}
    try:
        cursor = db.device_profile_overrides.find({}, {"_id": 0})
        async for doc in cursor:
            try:
                key = doc.get("key")
                if not key or not isinstance(key, str):
                    logger.warning("device_profile_overrides: doc senza key valida, skip: %r", doc)
                    continue
                ov = doc.get("overrides")
                # Tollera overrides null o malformati: trattiamo come dict vuoto
                if ov is None:
                    out[key] = {}
                elif isinstance(ov, dict):
                    out[key] = ov
                else:
                    logger.warning("device_profile_overrides[%s]: overrides non dict (%s), skip", key, type(ov).__name__)
                    out[key] = {}
            except Exception as e_doc:
                logger.exception("device_profile_overrides: errore parsing doc %r: %s", doc, e_doc)
    except Exception as e:
        logger.exception("device_profile_overrides: errore fetch collection: %s", e)
    return out


def _merge(seed: dict, overrides: dict) -> dict:
    """Shallow-merge overrides into seed (overrides wins). Difensivo: non solleva mai."""
    merged = dict(seed) if isinstance(seed, dict) else {}
    try:
        if isinstance(overrides, dict):
            for k, v in overrides.items():
                merged[k] = v
        merged["_has_overrides"] = bool(overrides)
    except Exception as e:
        logger.exception("Errore merge profilo %r: %s", seed.get("key") if isinstance(seed, dict) else "?", e)
        merged["_has_overrides"] = False
        merged["_merge_error"] = str(e)
    return merged


@router.get("")
async def list_profiles(current_user: dict = Depends(get_current_user)):
    """Ritorna la lista completa dei profili effettivi.

    Resiliente: se UN profilo fallisce nel merge, continua con gli altri e
    riporta gli errori nel campo `errors` invece di 500. Indispensabile
    perché un singolo override corrotto in DB non oscuri tutta la UI.
    """
    overrides_map = await _get_overrides_map()
    effective: list[dict] = []
    errors: list[dict] = []
    for p in PROFILES:
        try:
            key = p.get("key") if isinstance(p, dict) else None
            if not key:
                errors.append({"key": None, "error": "seed profile senza key"})
                continue
            merged = _merge(p, overrides_map.get(key, {}))
            effective.append(merged)
        except Exception as e:
            tb = traceback.format_exc()
            logger.error("list_profiles: errore su profilo %r: %s\n%s",
                         p.get("key") if isinstance(p, dict) else "?", e, tb)
            errors.append({
                "key": p.get("key") if isinstance(p, dict) else None,
                "error": str(e),
            })
    return {
        "seed_version": SEED_VERSION,
        "count": len(effective),
        "profiles": effective,
        "errors": errors,  # vuoto = tutto ok; pieno = inspect su quali profili falliscono
    }


@router.get("/{key}")
async def get_one(key: str, current_user: dict = Depends(get_current_user)):
    seed = get_profile(key)
    if not seed:
        raise HTTPException(status_code=404, detail="Profilo non trovato")
    overrides = (await db.device_profile_overrides.find_one({"key": key}, {"_id": 0})) or {}
    return _merge(seed, overrides.get("overrides") or {})


@router.post("/fingerprint")
async def fingerprint_device(body: dict, current_user: dict = Depends(get_current_user)):
    """Match a device identity (sysObjectID + sysDescr) to a profile.
    Body: {sysobjectid?: str, sysdescr?: str, device_ip?: str}
    Returns: {matched: bool, profile: {...} | null, confidence: 'high'|'medium'|'low'|'none'}
    """
    sysoid = (body.get("sysobjectid") or "").strip()
    sysdesc = (body.get("sysdescr") or "").strip()
    device_ip = (body.get("device_ip") or "").strip()

    # Auto-fetch from device_poll_status if only device_ip given
    if device_ip and not (sysoid or sysdesc):
        ps = await db.device_poll_status.find_one(
            {"device_ip": device_ip},
            {"_id": 0, "sys_descr": 1, "sys_object_id": 1, "sysObjectID": 1}
        ) or {}
        sysdesc = sysdesc or ps.get("sys_descr") or ""
        sysoid = sysoid or ps.get("sys_object_id") or ps.get("sysObjectID") or ""

    matched = _fingerprint(sysoid or None, sysdesc or None)
    confidence = "none"
    if matched:
        fp = matched.get("fingerprint") or {}
        if sysoid and any(sysoid.startswith(p) for p in (fp.get("sysobjectid_prefixes") or [])):
            confidence = "high"
        elif sysdesc:
            confidence = "medium"
        else:
            confidence = "low"

    # Apply overrides on match
    if matched:
        ov = await db.device_profile_overrides.find_one({"key": matched["key"]}, {"_id": 0})
        matched = _merge(matched, (ov or {}).get("overrides") or {})

    return {
        "matched": bool(matched),
        "profile": matched,
        "confidence": confidence,
        "input": {"sysobjectid": sysoid, "sysdescr": sysdesc, "device_ip": device_ip},
    }


@router.put("/{key}/override")
async def save_override(key: str, body: dict, current_user: dict = Depends(get_current_user)):
    """Save user override for a profile. Admin only. Body = dict with fields to override."""
    if current_user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Solo admin può modificare i profili")
    if not get_profile(key):
        raise HTTPException(status_code=404, detail="Profilo non trovato")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be a dict")
    # Whitelist overridable keys (prevent weird injections)
    ALLOWED: set[str] = {"snmp", "web_console", "oids", "thresholds", "polling_interval_seconds", "api_endpoints", "label", "description"}
    cleaned = {k: v for k, v in body.items() if k in ALLOWED}
    await db.device_profile_overrides.update_one(
        {"key": key},
        {"$set": {
            "key": key,
            "overrides": cleaned,
            "updated_by": current_user.get("email"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    return {"ok": True, "key": key, "override_fields": list(cleaned.keys())}


@router.delete("/{key}/override")
async def reset_override(key: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Solo admin può modificare i profili")
    res = await db.device_profile_overrides.delete_one({"key": key})
    return {"ok": True, "removed": res.deleted_count}


@router.post("/apply")
async def apply_profile(body: dict, current_user: dict = Depends(get_current_user)):
    """Apply a profile to a managed device (auto-detect or forced).
    Body: {device_ip: str, profile_key?: str, force?: bool}
    - If profile_key omitted → run fingerprint automatically
    - Updates managed_devices (if exists) + device_poll_status with:
        device_type, snmp config, web_console defaults, profile_key
    Returns the applied profile + affected collections count.
    """
    if current_user.get("role") not in ("admin", "superadmin", "operator"):
        raise HTTPException(status_code=403, detail="Permessi insufficienti")
    device_ip = (body.get("device_ip") or "").strip()
    if not device_ip:
        raise HTTPException(status_code=400, detail="device_ip required")
    force = bool(body.get("force"))
    pkey = (body.get("profile_key") or "").strip() or None

    # Resolve profile
    if pkey:
        profile = get_profile(pkey)
        if not profile:
            raise HTTPException(status_code=404, detail="Profilo non trovato")
    else:
        ps = await db.device_poll_status.find_one(
            {"device_ip": device_ip},
            {"_id": 0, "sys_descr": 1, "sys_object_id": 1, "sysObjectID": 1}
        ) or {}
        profile = _fingerprint(
            ps.get("sys_object_id") or ps.get("sysObjectID"),
            ps.get("sys_descr"),
        )
        if not profile:
            raise HTTPException(status_code=404, detail="Nessun profilo matcha questo device. Specifica profile_key manualmente.")

    # Apply overrides
    ov = await db.device_profile_overrides.find_one({"key": profile["key"]}, {"_id": 0})
    eff = _merge(profile, (ov or {}).get("overrides") or {})

    snmp = eff.get("snmp") or {}
    wc = eff.get("web_console") or {}

    md_patch = {
        "profile_key": eff["key"],
        "device_type": eff["family"],
        "vendor": eff["vendor"],
        "snmp_version": snmp.get("version"),
        "snmp_port": snmp.get("port", 161),
        "snmp_timeout": snmp.get("timeout_seconds"),
        "web_console_port": wc.get("port"),
        "web_console_scheme": wc.get("scheme"),
        "web_console_path": wc.get("path"),
        "web_console_user_configured": True,  # Admin applied profile → do not overwrite from auto-detect
        "polling_interval_seconds": eff.get("polling_interval_seconds"),
        "profile_applied_at": datetime.now(timezone.utc).isoformat(),
        "profile_applied_by": current_user.get("email"),
        # v4.14.x BUG-FIX "profili non si agganciano": flag che proteggono il
        # device_type/vendor scelto manualmente dall'enrichment OUI/Fingerbank
        # automatico (che altrimenti rimette device_type="endpoint" e vendor=OUI).
        "device_type_user_locked": True,
        "profile_auto_matched": False,
    }

    md_res = await db.managed_devices.update_many(
        {"ip": device_ip},
        {"$set": md_patch},
    )
    ps_res = await db.device_poll_status.update_one(
        {"device_ip": device_ip},
        {"$set": {"profile_key": eff["key"], "device_type": eff["family"], "vendor": eff["vendor"]}},
    )

    # Auto-populate allowed_ports_extra se la porta del profilo non è nelle default
    DEFAULT_WHITELIST = {
        80, 443, 8080, 8443, 8000, 8888, 4443, 4080, 9090, 10000,
        5000, 5001, 8006, 81, 8088, 3000, 19999, 4444, 2222, 8083, 17988, 17990,
    }
    port_added = False
    try:
        profile_port = (snmp.get("port") if False else wc.get("port"))
        if profile_port and int(profile_port) not in DEFAULT_WHITELIST:
            cur = await db.connector_settings.find_one({"key": "allowed_ports_extra"}, {"_id": 0}) or {}
            extra = set(int(p) for p in (cur.get("value") or []) if isinstance(p, (int, str)))
            if int(profile_port) not in extra:
                extra.add(int(profile_port))
                await db.connector_settings.update_one(
                    {"key": "allowed_ports_extra"},
                    {"$set": {
                        "key": "allowed_ports_extra",
                        "value": sorted(extra),
                        "updated_by": current_user.get("email"),
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }},
                    upsert=True,
                )
                port_added = True
    except Exception:
        pass

    return {
        "ok": True,
        "profile": eff,
        "applied": {
            "managed_devices_matched": md_res.matched_count,
            "managed_devices_modified": md_res.modified_count,
            "poll_status_matched": ps_res.matched_count,
            "poll_status_modified": ps_res.modified_count,
            "port_added_to_whitelist": port_added,
        },
        "forced": force,
    }


@router.get("/list/vendors")
async def list_vendors(current_user: dict = Depends(get_current_user)):
    """Quick dropdown helper: returns {vendor, label, key, family} per profile."""
    return {
        "items": [
            {"key": p["key"], "vendor": p["vendor"], "family": p["family"], "label": p["label"]}
            for p in PROFILES
        ]
    }
