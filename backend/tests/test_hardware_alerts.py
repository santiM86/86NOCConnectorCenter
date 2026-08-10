"""Test emissione/dedup/auto-risoluzione alert hardware SNMP (H3C/HPE Comware)."""
import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db  # noqa: E402
from hardware_alerts import evaluate_hardware_alerts, SOURCE_TYPE  # noqa: E402


async def _active(cid, ip, metric):
    return await db.alerts.find_one(
        {"dedup_key": f"{cid}:{ip}:{metric}", "status": "active"}, {"_id": 0})


async def main():
    cid = f"test-hw-{uuid.uuid4().hex[:8]}"
    ip = "10.99.99.99"
    # seed managed_device con profilo hpe_comware
    await db.managed_devices.insert_one({
        "id": str(uuid.uuid4()), "client_id": cid, "ip": ip,
        "hostname": "SW-TEST", "device_type": "switch", "profile_key": "hpe_comware",
    })
    try:
        # 1) CPU critica (>90), mem warn (>80), temp crit (>70), fan fault, psu ok
        vm = {
            "h3cEntityExtCpuUsage": {"1": "95"},
            "h3cEntityExtMemUsage": {"1": "85"},
            "h3cEntityExtTemperature": {"1": "75"},
            "h3cFanState": {"1": "2", "2": "41"},   # 41 = fanError -> guasto
            "h3cPowerState": {"1": "2"},            # normal
        }
        # 1° ciclo: mem/temp/fan immediati; CPU NON ancora (debounce 3 cicli)
        await evaluate_hardware_alerts(db, client_id=cid, device_ip=ip, vendor_metrics=vm)
        assert await _active(cid, ip, "cpu") is None, "CPU non deve alertare al 1° ciclo (debounce)"
        assert await _active(cid, ip, "mem"), "MEM deve alertare subito"
        assert await _active(cid, ip, "temp"), "TEMP deve alertare subito"
        assert await _active(cid, ip, "fan_fault"), "FAN deve alertare subito"
        assert await _active(cid, ip, "psu_fault") is None, "PSU non deve alertare"
        print("STEP1a OK: 1° ciclo -> mem/temp/fan attivi, cpu pending, psu no")

        # 2° e 3° ciclo: CPU supera il debounce -> alert critical
        await evaluate_hardware_alerts(db, client_id=cid, device_ip=ip, vendor_metrics=vm)
        assert await _active(cid, ip, "cpu") is None, "CPU ancora pending al 2° ciclo"
        await evaluate_hardware_alerts(db, client_id=cid, device_ip=ip, vendor_metrics=vm)
        cpu = await _active(cid, ip, "cpu")
        mem = await _active(cid, ip, "mem")
        temp = await _active(cid, ip, "temp")
        fan = await _active(cid, ip, "fan_fault")
        assert cpu and cpu["severity"] == "critical", f"CPU crit atteso al 3° ciclo, got {cpu}"
        assert mem and mem["severity"] == "high", f"MEM warn atteso, got {mem}"
        assert temp and temp["severity"] == "critical", f"TEMP crit atteso, got {temp}"
        assert fan and fan["severity"] == "critical", f"FAN fault atteso, got {fan}"
        assert cpu["source_type"] == SOURCE_TYPE
        print("STEP1b OK: CPU emessa dopo 3 cicli consecutivi (debounce)")

        # 2) dedup: rieseguo stesso payload -> nessun nuovo alert attivo (1 solo per metrica)
        await evaluate_hardware_alerts(db, client_id=cid, device_ip=ip, vendor_metrics=vm)
        n_cpu = await db.alerts.count_documents({"dedup_key": f"{cid}:{ip}:cpu", "status": "active"})
        assert n_cpu == 1, f"dedup fallito: {n_cpu} alert cpu attivi"
        print("STEP2 OK: dedup, 1 solo alert cpu attivo")

        # 3) escalation: CPU scende in warn band (80) -> severity aggiornata high
        vm2 = dict(vm)
        vm2["h3cEntityExtCpuUsage"] = {"1": "80"}
        await evaluate_hardware_alerts(db, client_id=cid, device_ip=ip, vendor_metrics=vm2)
        cpu2 = await _active(cid, ip, "cpu")
        assert cpu2 and cpu2["severity"] == "high", f"escalation warn atteso, got {cpu2}"
        n_cpu = await db.alerts.count_documents({"dedup_key": f"{cid}:{ip}:cpu", "status": "active"})
        assert n_cpu == 1, f"escalation deve aggiornare non duplicare: {n_cpu}"
        print("STEP3 OK: escalation crit->warn su stesso alert")

        # 4) auto-risoluzione: tutto rientra -> alert attivi risolti
        vm_ok = {
            "h3cEntityExtCpuUsage": {"1": "10"},
            "h3cEntityExtMemUsage": {"1": "20"},
            "h3cEntityExtTemperature": {"1": "35"},
            "h3cFanState": {"1": "2", "2": "2"},
            "h3cPowerState": {"1": "2"},
        }
        await evaluate_hardware_alerts(db, client_id=cid, device_ip=ip, vendor_metrics=vm_ok)
        for m in ("cpu", "mem", "temp", "fan_fault"):
            a = await _active(cid, ip, m)
            assert a is None, f"{m} doveva essere risolto, ancora attivo: {a}"
        resolved = await db.alerts.count_documents(
            {"dedup_key": {"$regex": f"^{cid}:{ip}:"}, "status": "resolved"})
        assert resolved >= 4, f"attesi >=4 resolved, got {resolved}"
        print("STEP4 OK: auto-risoluzione di cpu/mem/temp/fan")

        # 5) profilo senza thresholds/fan map non deve alertare fan/psu
        ip2 = "10.99.99.98"
        await db.managed_devices.insert_one({
            "id": str(uuid.uuid4()), "client_id": cid, "ip": ip2,
            "hostname": "SW-GEN", "device_type": "switch", "profile_key": "generic_snmp",
        })
        await evaluate_hardware_alerts(db, client_id=cid, device_ip=ip2,
                                       vendor_metrics={"fanStatus": {"1": "99"}})
        assert await _active(cid, ip2, "fan_fault") is None, "generic non deve alertare fan"
        print("STEP5 OK: profilo senza enum fan non alerta ventole")

        # 6) sentinelle SNMP (65535/0) NON devono generare alert
        ip3 = "10.99.99.97"
        await db.managed_devices.insert_one({
            "id": str(uuid.uuid4()), "client_id": cid, "ip": ip3,
            "hostname": "SW-SENT", "device_type": "switch", "profile_key": "hpe_comware",
        })
        vm_sent = {
            "h3cEntityExtCpuUsage": {"1": "8"},        # valido -> ma sotto soglia
            "h3cEntityExtMemUsage": {"1": "35"},
            "h3cEntityExtTemperature": {"1": "65535"},  # sentinella -> NO alert temp
            "h3cFanState": {"1": "65535", "2": "0"},    # entita' fantasma -> NO fault
            "h3cPowerState": {str(i): "65535" for i in range(1, 28)},  # 27 PSU fantasma
        }
        await evaluate_hardware_alerts(db, client_id=cid, device_ip=ip3, vendor_metrics=vm_sent)
        assert await _active(cid, ip3, "temp") is None, "temp 65535 non deve alertare"
        assert await _active(cid, ip3, "fan_fault") is None, "fan sentinella non deve alertare"
        assert await _active(cid, ip3, "psu_fault") is None, "psu 65535 non deve alertare"
        print("STEP6 OK: sentinelle 65535/0 ignorate (no falsi alert temp/fan/psu)")

        print("\nALL HARDWARE ALERT TESTS PASSED")
    finally:
        await db.managed_devices.delete_many({"client_id": cid})
        await db.alerts.delete_many({"dedup_key": {"$regex": f"^{cid}:"}})
        await db.hardware_alert_state.delete_many({"dedup_key": {"$regex": f"^{cid}:"}})


if __name__ == "__main__":
    asyncio.run(main())
