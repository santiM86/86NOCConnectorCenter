"""Iter146 — Analisi AI log iLO (GPT-5.4 via Universal Key) + trigger automatico.
Esecuzione: cd /app/backend && python tests/test_ilo_ai_iter146.py
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
IP = "10.88.0.50"


def login():
    r = requests.post(f"{API}/api/auth/login", json={"email": "info@86bit.it", "password": "Ariel17051986@!@86"}).json()
    tok = r.get("token") or r.get("access_token")
    r2 = requests.post(f"{API}/api/auth/verify-2fa", json={"code": pyotp.TOTP("NMHDJNO53WLTOSREUXWERE6FDH5TAKC3").now()},
                       headers={"Authorization": f"Bearer {tok}"}).json()
    return r2.get("token") or r2.get("access_token") or tok


def events():
    now = datetime.now(timezone.utc)
    ev = []
    for d in (1, 2, 5, 9, 30):
        t = (now - timedelta(days=d)).replace(hour=22, minute=19, second=0)
        ev.append({"id": f"n{d}", "severity": "informational", "created": t.isoformat(), "class": 17, "code": 10, "repaired": True,
                   "message": "HPE Eth 10Gb 2p 562T Adptr Connectivity status changed to OK for adapter in slot 2, port 2"})
        ev.append({"id": f"f{d}", "severity": "caution", "created": (t - timedelta(minutes=3)).isoformat(), "class": 17, "code": 9, "repaired": True,
                   "message": "HPE Eth 10Gb 2p 562T Adptr Connectivity status changed to Failed for adapter in slot 2, port 2"})
    ev.append({"id": "d1", "severity": "caution", "created": (now - timedelta(days=3)).isoformat(), "class": 11, "code": 4, "repaired": False,
               "message": "Smart Array P408i-a: Physical drive predictive failure (Port 1I Box 3 Bay 3)"})
    ev.append({"id": "m1", "severity": "critical", "created": (now - timedelta(days=12)).isoformat(), "class": 3, "code": 10, "repaired": False, "count": 3,
               "message": "Corrected Memory Error threshold exceeded (Processor 1, DIMM 5)"})
    ev.sort(key=lambda e: e["created"], reverse=True)
    return ev


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    await db.ilo_events.delete_many({"device_ip": IP}); await db.ilo_ai_analyses.delete_many({"device_ip": IP})
    await db.managed_devices.delete_many({"ip": IP}); await db.ilo_status.delete_many({"device_ip": IP})
    try:
        await db.managed_devices.insert_one({"client_id": CID, "ip": IP, "name": "SRV-TEST-ILO", "device_type": "ilo"})
        await db.ilo_status.insert_one({"client_id": CID, "device_ip": IP, "server_model": "ProLiant DL380 Gen10", "bios_version": "U30 v2.90", "ilo_firmware": "iLO 5 v3.19",
                                        "health_status": "Warning", "power_watts": 265,
                                        "temperatures": [{"locale": "01-Inlet Ambient", "value": 24, "condition": "OK"}, {"locale": "13-CPU 1", "value": 62, "condition": "OK"}],
                                        "fans": [{"locale": "Fan 1", "speed": 38, "condition": "OK"}],
                                        "power_supplies": [{"name": "PSU 1", "status": "OK"}, {"name": "PSU 2", "status": "OK"}],
                                        "storage_controllers": [{"name": "Smart Array P408i-a", "status": "Warning",
                                                                 "drives": [{"location": "1I:3:3", "model": "EG001200JWJNQ", "health": "Warning", "predicted_failure": True, "power_on_hours": 42100},
                                                                            {"location": "1I:3:1", "model": "EG001200JWJNQ", "health": "OK", "power_on_hours": 21440}],
                                                                 "logical_drives": [{"name": "LogicalDrive 1", "raid": "RAID5", "status": "OK"}]}]})
        base_events = events()
        await db.ilo_events.insert_one({"client_id": CID, "device_ip": IP, "events": base_events, "log_path": "/redfish/v1/Systems/1/LogServices/IML/Entries/",
                                        "source": "direct", "fetched_at": datetime.now(timezone.utc).isoformat()})
        H = {"Authorization": f"Bearer {login()}"}

        r = requests.post(f"{API}/api/servers/ilo-ai-analysis/{IP}", params={"client_id": CID}, headers=H, timeout=180)
        assert r.status_code == 200, r.text
        d = r.json()
        res = d["result"]
        assert d["risk_level"] in ("low", "medium", "high", "critical"), d["risk_level"]
        assert res.get("headline") and res.get("diagnosis") and isinstance(res.get("actions"), list) and res["actions"], res
        assert d["events_count"] == len(base_events) and d["unrepaired"] == 2 and d["trigger"] == "manual" and d["model"] == "openai/gpt-5.4", d
        txt = str(res).lower()
        assert ("dimm" in txt or "memor" in txt) and ("bay 3" in txt or "disco" in txt or "drive" in txt or "predi" in txt), txt[:500]
        print(f"STEP1 OK: analisi manuale in {d['duration_s']}s → rischio {d['risk_level'].upper()} | {res['headline']}")
        for a in res["actions"][:3]:
            print(f"   {a.get('priority')}. {a.get('action')} [{a.get('when')}]")
        if res.get("patterns"):
            print(f"   pattern: {res['patterns'][0].get('title')}")

        r = requests.get(f"{API}/api/servers/ilo-ai-analysis/{IP}", params={"client_id": CID}, headers=H)
        assert r.status_code == 200 and r.json()["latest"]["id"] == d["id"] and len(r.json()["history"]) == 1
        print("STEP2 OK: GET latest/history")

        # trigger automatico: nuovo evento critico non riparato via store_ilo_events_cache
        from routes.server_intelligence import store_ilo_events_cache
        from routes import ilo_ai
        ilo_ai.AUTO_DEBOUNCE_H = 0
        new_ev = [{"id": "p1", "severity": "critical", "created": datetime.now(timezone.utc).isoformat(), "class": 5, "code": 7, "repaired": False,
                   "message": "Power Supply Failure (Power Supply 2)"}] + base_events
        await store_ilo_events_cache(CID, IP, new_ev, "/redfish/v1/Systems/1/LogServices/IML/Entries/", "direct")
        for _ in range(60):
            await asyncio.sleep(2)
            auto = await db.ilo_ai_analyses.find_one({"device_ip": IP, "trigger": "auto"}, {"_id": 0})
            if auto:
                break
        assert auto, "analisi automatica non generata"
        assert auto["events_count"] == len(new_ev) and auto["unrepaired"] == 3, auto
        print(f"STEP3 OK: trigger automatico su nuovo evento critico → rischio {auto['risk_level'].upper()} | {auto['result'].get('headline')}")

        # nessuna analisi auto se solo eventi riparati/informativi
        n_before = await db.ilo_ai_analyses.count_documents({"device_ip": IP})
        await store_ilo_events_cache(CID, IP, [{"id": "ok1", "severity": "informational", "created": datetime.now(timezone.utc).isoformat(), "repaired": True, "message": "IML cleared"}] + new_ev,
                                     "/redfish/v1/Systems/1/LogServices/IML/Entries/", "direct")
        await asyncio.sleep(3)
        assert await db.ilo_ai_analyses.count_documents({"device_ip": IP}) == n_before
        print("STEP4 OK: nessun trigger per eventi informativi/riparati")

        r = requests.post(f"{API}/api/servers/ilo-ai-analysis/10.88.0.99", params={"client_id": CID}, headers=H, timeout=60)
        assert r.status_code == 404, r.text
        r = requests.post(f"{API}/api/servers/ilo-ai-analysis/{IP}", params={"client_id": CID})
        assert r.status_code in (401, 403)
        print("STEP5 OK: 404 senza dati, auth richiesta")
        print("\nALL ILO AI TESTS PASSED")
    finally:
        await db.ilo_events.delete_many({"device_ip": IP}); await db.ilo_ai_analyses.delete_many({"device_ip": IP})
        await db.managed_devices.delete_many({"ip": IP}); await db.ilo_status.delete_many({"device_ip": IP})


if __name__ == "__main__":
    asyncio.run(main())
