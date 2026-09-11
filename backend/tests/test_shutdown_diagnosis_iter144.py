"""Iter144 — Diagnosi spegnimento (porta switch + orario abituale + Datto lastSeen).
Esecuzione: cd /app/backend && python tests/test_shutdown_diagnosis_iter144.py
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

import pyotp
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv("/app/backend/.env")

API = "https://noc-alert-hub-2.preview.emergentagent.com"
CID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"
SW = "10.77.0.2"
PCS = {"crash": "10.77.0.11", "intent": "10.77.0.12", "down": "10.77.0.13", "datto": "10.77.0.14", "noport": "10.77.0.15"}
MACS = {k: f"AA:77:00:00:00:{i + 10:02X}" for i, k in enumerate(PCS)}


def login():
    r = requests.post(f"{API}/api/auth/login", json={"email": "info@86bit.it", "password": "Ariel17051986@!@86"}).json()
    tok = r.get("token") or r.get("access_token")
    r2 = requests.post(f"{API}/api/auth/verify-2fa", json={"code": pyotp.TOTP("NMHDJNO53WLTOSREUXWERE6FDH5TAKC3").now()},
                       headers={"Authorization": f"Bearer {tok}"}).json()
    return r2.get("token") or r2.get("access_token") or tok


async def cleanup(db):
    ips = list(PCS.values()) + [SW]
    await db.managed_devices.delete_many({"client_id": CID, "ip": {"$in": ips}})
    await db.device_poll_status.delete_many({"client_id": CID, "device_ip": {"$in": ips}})
    await db.discovered_endpoints.delete_many({"client_id": CID, "switch_ip": SW})
    await db.switch_ports.delete_many({"client_id": CID, "local_ip": SW})
    await db.device_status_state.delete_many({"client_id": CID, "device_ip": {"$in": ips}})
    await db.device_status_events.delete_many({"client_id": CID, "device_ip": {"$in": ips}})
    await db.datto_devices.delete_many({"uid": "test-datto-iter144"})


async def main():
    from shutdown_diagnosis import diagnose, record_status_transitions_tick
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    await cleanup(db)
    now = datetime.now(timezone.utc)
    # martedì 10:25 locale (~08:25 UTC estate) → orario lavorativo
    off_work = now.replace(hour=8, minute=25, second=0, microsecond=0)
    while off_work.weekday() >= 5:
        off_work -= timedelta(days=1)
    # sera 18:30 locale (16:30 UTC)
    off_evening = off_work.replace(hour=16, minute=30)
    try:
        await db.managed_devices.insert_one({"client_id": CID, "ip": SW, "name": "SW-CORE-TEST", "device_type": "switch"})
        for k, ip in PCS.items():
            await db.managed_devices.insert_one({"client_id": CID, "ip": ip, "name": f"PC-{k.upper()}", "device_type": "endpoint",
                                                 "mac": MACS[k], **({"datto_uid": "test-datto-iter144"} if k == "datto" else {})})
        # FDB: ogni PC su una porta; porta 24 = uplink con 3 MAC (deve essere scartata per il pc "intent")
        eps = [{"client_id": CID, "switch_ip": SW, "port": i + 1, "mac": MACS[k].replace(":", ""), "ip": ip} for i, (k, ip) in enumerate(PCS.items()) if k != "noport"]
        eps += [{"client_id": CID, "switch_ip": SW, "port": 24, "mac": MACS["intent"].replace(":", ""), "ip": PCS["intent"]},
                {"client_id": CID, "switch_ip": SW, "port": 24, "mac": "AABBCCDDEE01", "ip": ""},
                {"client_id": CID, "switch_ip": SW, "port": 24, "mac": "AABBCCDDEE02", "ip": ""}]
        await db.discovered_endpoints.insert_many(eps)
        ports = {1: ("up", 1000), 2: ("up", 100), 3: ("down", 0), 4: ("up", 1000), 24: ("up", 10000)}
        await db.switch_ports.insert_many([{"client_id": CID, "local_ip": SW, "idx": i, "name": f"GigabitEthernet1/0/{i}",
                                            "oper": o, "admin": "up", "speed_mbps": s, "updated_at": now.isoformat()} for i, (o, s) in ports.items()])
        # Baseline: pc intent a 1G quando acceso
        await db.device_status_state.insert_one({"client_id": CID, "device_ip": PCS["intent"], "reachable": True, "since": (now - timedelta(days=1)).isoformat(), "usual_speed_mbps": 1000})
        # Storico: pc intent va giù sempre alle 18:30 locali nei giorni lavorativi (8 eventi)
        evs = []
        d = off_evening
        while len(evs) < 8:
            d -= timedelta(days=1)
            if d.weekday() < 5:
                evs.append({"client_id": CID, "device_ip": PCS["intent"], "event": "down", "at": d.isoformat()})
        await db.device_status_events.insert_many(evs)
        # Datto: agente online adesso per pc "datto"
        await db.datto_devices.insert_one({"uid": "test-datto-iter144", "client_id": CID, "name": "PC-DATTO", "ip": PCS["datto"],
                                           "online": True, "datto_last_seen": now.isoformat(), "fetched_at": now.isoformat()})
        # Poll status: tutti offline
        for k, ip in PCS.items():
            since = off_evening if k == "intent" else off_work
            await db.device_poll_status.insert_one({"client_id": CID, "device_ip": ip, "device_name": f"PC-{k.upper()}", "reachable": False,
                                                    "unreachable_since": since.isoformat(), "last_reachable_at": since.isoformat(), "last_poll": now.isoformat()})

        # ---- unit: diagnose ----
        r = await diagnose(db, CID, PCS["crash"])
        assert r["verdict"] == "crash" and r["signals"]["port"] == "up_full" and r["signals"]["schedule"] == "unusual", r
        assert r["port"]["port"] == 1 and r["confidence"] >= 80, r
        print(f"STEP1 OK: porta UP 1G + orario lavorativo → CRASH {r['confidence']}%")

        r = await diagnose(db, CID, PCS["intent"])
        assert r["verdict"] == "intentional" and r["signals"]["port"] == "low_speed" and r["signals"]["schedule"] == "usual", r
        assert r["port"]["port"] == 2, f"doveva scartare l'uplink 24: {r['port']}"
        assert r["history"]["events"] == 8 and r["confidence"] >= 90, r
        print(f"STEP2 OK: porta 100M (baseline 1G) + orario abituale 18:30 → SPENTO VOLUTAMENTE {r['confidence']}% (uplink scartato)")

        r = await diagnose(db, CID, PCS["down"])
        assert r["verdict"] == "disconnected" and r["signals"]["port"] == "down", r
        print(f"STEP3 OK: porta DOWN + orario lavorativo → SPENTO O SCOLLEGATO {r['confidence']}%")

        r = await diagnose(db, CID, PCS["datto"])
        assert r["verdict"] == "reachable_elsewhere" and r["signals"]["datto"] == "online_now", r
        print(f"STEP4 OK: Datto online → ACCESO MA NON RAGGIUNGIBILE {r['confidence']}%")

        r = await diagnose(db, CID, PCS["noport"])
        assert r["signals"]["port"] == "unknown" and r["verdict"] in ("crash", "unknown"), r
        assert r["evidence"][0]["level"] == "na" and r["evidence"][1]["kind"] == "schedule", r
        print(f"STEP5 OK: nessuna porta → verdetto {r['verdict']} {r['confidence']}% basato su orario (fallback business hours)")

        # ---- cron: transizioni ----
        await db.device_poll_status.update_one({"client_id": CID, "device_ip": PCS["crash"]}, {"$set": {"reachable": True, "unreachable_since": None}})
        res = await record_status_transitions_tick(db)
        st = await db.device_status_state.find_one({"client_id": CID, "device_ip": PCS["crash"]})
        assert st and st["reachable"] is True and st.get("usual_speed_mbps") == 1000 and st["port_ref"]["port"] == 1, st
        n_down = await db.device_status_events.count_documents({"client_id": CID, "device_ip": PCS["down"], "event": "down"})
        assert n_down == 1, n_down
        print(f"STEP6 OK: tick registra down confermati ({res}) e baseline 1G per il PC tornato online")
        await db.device_poll_status.update_one({"client_id": CID, "device_ip": PCS["crash"]}, {"$set": {"reachable": False, "unreachable_since": (now - timedelta(minutes=10)).isoformat()}})
        await record_status_transitions_tick(db)
        ev = await db.device_status_events.find_one({"client_id": CID, "device_ip": PCS["crash"], "event": "down"})
        assert ev and ev.get("duration_s") is not None, ev
        r = await diagnose(db, CID, PCS["crash"])
        assert r["verdict"] == "crash", r
        print("STEP7 OK: up→down registrato con durata; diagnosi coerente")

        # ---- API ----
        H = {"Authorization": f"Bearer {login()}"}
        r = requests.get(f"{API}/api/devices/shutdown-diagnosis/{PCS['intent']}", params={"client_id": CID}, headers=H)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["verdict"] == "intentional" and len(d["evidence"]) == 3 and d["label"] == "Spento volutamente", d
        r = requests.get(f"{API}/api/devices/shutdown-diagnosis/10.77.0.99", params={"client_id": CID}, headers=H)
        assert r.status_code == 200 and r.json()["verdict"] in ("unknown", "crash", "intentional"), r.text
        r = requests.get(f"{API}/api/devices/shutdown-diagnosis/{PCS['intent']}")
        assert r.status_code in (401, 403), r.status_code
        print("STEP8 OK: API GET /api/devices/shutdown-diagnosis/{ip} (auth richiesta)")
        print("\nALL SHUTDOWN DIAGNOSIS TESTS PASSED")
    finally:
        await cleanup(db)


if __name__ == "__main__":
    asyncio.run(main())
