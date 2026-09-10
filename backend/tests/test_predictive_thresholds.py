"""Test predictive.evaluate_predictive_alerts threshold resolution + heartbeat fix.

Retest (iteration 140) after fix on _emit heartbeat (both predictive.py and
hardware_alerts.py now call alert_filter.touch_alert on the "unchanged" branch).

Cases:
  A) default -> alert attivo predictive_temp per NAS a 64C
     A.heartbeat) forzare last_seen_at=2000, rieseguire con stessi valori
                  -> last_seen_at aggiornato a ora
  B) override device (temp_warn/crit_c 80/90) -> alert risolto (recovered)
  C) client temp_by_type nas warn/crit 80/90 -> alert risolto/non ricreato
  D) hardware_alerts._emit_or_update heartbeat: hpe_comware temp 75
     - 1st call crea alert :temp
     - forza last_seen_at=2000
     - 2nd call stessi valori -> last_seen_at aggiornato
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta

sys.path.insert(0, "/app/backend")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
import predictive  # noqa: E402
import hardware_alerts  # noqa: E402

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

FROZEN_PAST_ISO = "2000-01-01T00:00:00+00:00"


async def _seed_series(db, client_id, device_ip, metric, values):
    now = datetime.now(timezone.utc)
    docs = []
    n = len(values)
    for i, v in enumerate(values):
        ts = now - timedelta(minutes=(n - 1 - i) * 10)
        docs.append({"client_id": client_id, "device_ip": device_ip,
                     "metric": metric, "value": float(v), "ts": ts})
    await db.metric_history.insert_many(docs)


async def _active_alert(db, dedup_key):
    return await db.alerts.find_one({"dedup_key": dedup_key, "status": "active"}, {"_id": 0})


async def _force_last_seen_past(db, dedup_key):
    await db.alerts.update_many(
        {"dedup_key": dedup_key, "status": "active"},
        {"$set": {"last_seen_at": FROZEN_PAST_ISO}},
    )


async def _cleanup(db, client_id):
    await db.metric_history.delete_many({"client_id": client_id})
    await db.alerts.delete_many({"client_id": client_id})
    await db.managed_devices.delete_many({"client_id": client_id})
    await db.clients.delete_many({"id": client_id})
    await db.alert_thresholds.delete_many({"client_id": client_id})
    await db.pre_blackout_events.delete_many({"client_id": client_id})
    await db.hardware_alert_state.delete_many({"dedup_key": {"$regex": f"^{client_id}:"}})


async def run():
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    client_id = f"TEST_pred_{uuid.uuid4().hex[:8]}"
    device_ip = "10.99.99.99"
    dk_temp = f"{client_id}:{device_ip}:predictive_temp"

    # hardware_alerts test uses a separate switch device
    sw_ip = "10.99.99.98"
    dk_hw_temp = f"{client_id}:{sw_ip}:temp"

    results = {}

    try:
        await _cleanup(db, client_id)
        await db.clients.insert_one({"id": client_id, "name": "TEST Client Predictive"})
        await db.managed_devices.insert_one({
            "client_id": client_id, "ip": device_ip, "hostname": "NAS01",
            "device_type": "nas", "profile_key": None,
        })

        temp_values = [60, 61, 62, 63, 64, 64]
        await _seed_series(db, client_id, device_ip, "temperature", temp_values)

        vm = {"temperature": {"1": "64"}}

        # ---------- CASO A: default -> alert atteso ----------
        await predictive.evaluate_predictive_alerts(
            db, client_id=client_id, device_ip=device_ip,
            vendor_metrics=vm, sys_name="NAS01")
        a1 = await _active_alert(db, dk_temp)
        results["A_alert_created"] = bool(a1)
        assert a1 is not None, "CASO A: alert predictive_temp NON creato con default nas"
        assert "GUASTO IMMINENTE: Temperatura su NAS01" in a1.get("title", "")
        assert a1.get("source_type") == "predictive_temp"

        # ---------- CASO A.heartbeat: forza last_seen_at=2000, rieseguire ----------
        await _force_last_seen_past(db, dk_temp)
        a_before = await _active_alert(db, dk_temp)
        assert a_before.get("last_seen_at") == FROZEN_PAST_ISO
        await predictive.evaluate_predictive_alerts(
            db, client_id=client_id, device_ip=device_ip,
            vendor_metrics=vm, sys_name="NAS01")
        a_after = await _active_alert(db, dk_temp)
        ls_after = a_after.get("last_seen_at")
        results["A_heartbeat_last_seen_after"] = ls_after
        assert ls_after and ls_after != FROZEN_PAST_ISO, \
            f"HEARTBEAT NOT UPDATED (predictive._emit): last_seen_at still {ls_after}"
        # verify it's "now" (year 2025+)
        assert ls_after.startswith("20") and int(ls_after[:4]) >= 2025, \
            f"last_seen_at non ha timestamp corrente: {ls_after}"
        results["A_heartbeat_updated"] = True

        # ---------- CASO B: override device 80/90 -> resolved (regressione) ----------
        await db.managed_devices.update_one(
            {"client_id": client_id, "ip": device_ip},
            {"$set": {"temp_warn_c": 80, "temp_crit_c": 90}})
        await predictive.evaluate_predictive_alerts(
            db, client_id=client_id, device_ip=device_ip,
            vendor_metrics=vm, sys_name="NAS01")
        aB = await _active_alert(db, dk_temp)
        results["B_alert_resolved"] = aB is None
        resB = await db.alerts.find_one(
            {"dedup_key": dk_temp, "status": "resolved"},
            sort=[("resolved_at", -1)])
        results["B_resolution_reason"] = (resB or {}).get("resolution_reason")
        assert aB is None, "CASO B: alert predictive_temp NON risolto dopo override device"
        assert (resB or {}).get("resolution_reason") == "recovered"

        # ---------- CASO D: hardware_alerts heartbeat (hpe_comware temp) ----------
        # Setup switch device with hpe_comware profile (defaults temp warn 55 crit 70)
        await db.managed_devices.insert_one({
            "client_id": client_id, "ip": sw_ip, "hostname": "SW01",
            "device_type": "switch", "profile_key": "hpe_comware",
        })
        vm_hw = {"h3cEntityExtTemperature": {"1": "75"}}  # 75 >= 70 crit

        # 1st call: crea alert :temp critical
        await hardware_alerts.evaluate_hardware_alerts(
            db, client_id=client_id, device_ip=sw_ip,
            vendor_metrics=vm_hw, sys_name="SW01")
        h1 = await _active_alert(db, dk_hw_temp)
        results["D_hw_alert_created"] = bool(h1)
        assert h1 is not None, "hardware_alerts: alert :temp NON creato con hpe_comware 75C"
        assert h1.get("severity") == "critical"

        # Force last_seen_at to 2000
        await _force_last_seen_past(db, dk_hw_temp)
        h_before = await _active_alert(db, dk_hw_temp)
        assert h_before.get("last_seen_at") == FROZEN_PAST_ISO

        # 2nd call same values -> heartbeat must update last_seen_at
        await hardware_alerts.evaluate_hardware_alerts(
            db, client_id=client_id, device_ip=sw_ip,
            vendor_metrics=vm_hw, sys_name="SW01")
        h_after = await _active_alert(db, dk_hw_temp)
        ls_hw = h_after.get("last_seen_at")
        results["D_hw_heartbeat_last_seen_after"] = ls_hw
        assert ls_hw and ls_hw != FROZEN_PAST_ISO, \
            f"HEARTBEAT NOT UPDATED (hardware_alerts._emit_or_update): {ls_hw}"
        assert ls_hw.startswith("20") and int(ls_hw[:4]) >= 2025
        results["D_hw_heartbeat_updated"] = True

        print("=" * 60)
        print("ALL PREDICTIVE + HARDWARE HEARTBEAT TESTS PASSED")
        for k, v in results.items():
            print(f"  {k}: {v}")
        print("=" * 60)
        return 0
    except AssertionError as e:
        print(f"FAIL: {e}")
        for k, v in results.items():
            print(f"  {k}: {v}")
        return 1
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"ERROR: {e}")
        return 2
    finally:
        await _cleanup(db, client_id)
        client.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
