"""Migrazioni one-shot eseguite allo startup (idempotenti, tracciate in db.migrations)."""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_NIL_NAMES = ["<nil>", "nil", "null"]


async def _already_done(db, name: str) -> bool:
    return await db.migrations.find_one({"name": name}) is not None


async def _mark_done(db, name: str, info: dict) -> None:
    await db.migrations.update_one(
        {"name": name},
        {"$set": {"name": name, "done_at": datetime.now(timezone.utc).isoformat(), **info}},
        upsert=True,
    )


async def fix_comware_fan_psu_false_positives(db, name: str = "2026-09-08_comware_fan_psu_false_positives") -> None:
    """Chiude gli alert Guasto ventola/alimentatore sugli switch HPE Comware generati
    dagli OID sbagliati (.16 VoltageHighThreshold / .18 MacAddress) o da slot PSU
    vuoti (deactive(2) mai visti attivi)."""
    if await _already_done(db, name):
        return
    ips = [d["ip"] async for d in db.managed_devices.find(
        {"profile_key": "hpe_comware", "ip": {"$exists": True}}, {"_id": 0, "ip": 1})]
    ips += [d["device_ip"] async for d in db.device_poll_status.find(
        {"profile_key": "hpe_comware", "device_ip": {"$exists": True}}, {"_id": 0, "device_ip": 1})]
    ips = sorted(set(ips))
    now = datetime.now(timezone.utc).isoformat()
    q = {"status": "active", "$or": [
        {"source_type": {"$in": ["vendor_h3cFanState_fault", "vendor_h3cPowerState_fault"]}},
        {"device_ip": {"$in": ips}, "$or": [
            {"dedup_key": {"$regex": r":(psu|fan)_fault$"}},
            {"title": {"$regex": r"^Guasto (alimentatore|ventola) su "}},
        ]},
    ]}
    res = await db.alerts.update_many(q, {"$set": {
        "status": "resolved", "resolved_at": now,
        "resolution_note": "Auto-chiuso: falso positivo da OID PSU/ventola errato (fix profilo HPE Comware)",
        "resolution_reason": "false_positive",
    }})
    await db.hardware_alert_state.delete_many({"dedup_key": {"$regex": r":(psu|fan)_fault$"}})
    await _mark_done(db, name, {"resolved": res.modified_count, "devices": len(ips)})
    logger.info("migration %s: resolved=%s comware_devices=%s", name, res.modified_count, len(ips))


async def fix_nil_device_names(db) -> None:
    """Ripulisce sys_name/name letterali '<nil>' salvati dall'agent Go."""
    name = "2026-09-08_nil_device_names"
    if await _already_done(db, name):
        return
    r1 = await db.managed_devices.update_many({"sys_name": {"$in": _NIL_NAMES}}, {"$unset": {"sys_name": ""}})
    r2 = await db.managed_devices.update_many({"name": {"$in": _NIL_NAMES}}, {"$unset": {"name": ""}})
    r3 = await db.device_poll_status.update_many({"sys_name": {"$in": _NIL_NAMES}}, {"$set": {"sys_name": None}})
    await _mark_done(db, name, {"managed_sys_name": r1.modified_count,
                                "managed_name": r2.modified_count, "poll_status": r3.modified_count})
    logger.info("migration %s: %s/%s/%s", name, r1.modified_count, r2.modified_count, r3.modified_count)


async def fix_comware_psu_deactive_absent(db) -> None:
    await fix_comware_fan_psu_false_positives(db, name="2026-09-08b_comware_psu_deactive_absent")


async def run_all(db) -> None:
    for fn in (fix_comware_fan_psu_false_positives, fix_comware_psu_deactive_absent, fix_nil_device_names):
        try:
            await fn(db)
        except Exception as e:  # noqa: BLE001
            logger.exception("migration %s failed: %s", fn.__name__, e)
