"""Iter149 — Memoria porte: apprendimento abitudini, verdetti, filtro alert, API topology.
Esecuzione: cd /app/backend && python tests/test_port_memory_iter149.py
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
SW = "10.55.0.2"


def login():
    r = requests.post(f"{API}/api/auth/login", json={"email": "info@86bit.it", "password": "Ariel17051986@!@86"}).json()
    tok = r.get("token") or r.get("access_token")
    r2 = requests.post(f"{API}/api/auth/verify-2fa", json={"code": pyotp.TOTP("NMHDJNO53WLTOSREUXWERE6FDH5TAKC3").now()},
                       headers={"Authorization": f"Bearer {tok}"}).json()
    return r2.get("token") or r2.get("access_token") or tok


def mem(idx, days, up_pattern, poe=0.0, speed=1000):
    """Costruisce un doc port_memory sintetico: up_pattern(hour, weekday) -> bool, 1 campione/ora."""
    how_up, how_tot = {}, {}
    samples = ups = 0
    for wd in range(7):
        for h in range(24):
            b = str(wd * 24 + h)
            n = max(1, int(days / 7))
            how_tot[b] = n
            u = n if up_pattern(h, wd) else 0
            how_up[b] = u
            samples += n
            ups += u
    return {"client_id": CID, "local_ip": SW, "idx": idx, "name": f"GigabitEthernet1/0/{idx}",
            "first_seen": (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(),
            "samples": samples, "up_samples": ups, "how_up": how_up, "how_total": how_tot,
            "usual_speed_mbps": speed, "poe_samples": 10 if poe else 0, "poe_w_sum": poe * 10,
            "last_oper_up": False, "last_poe_w": 0.0, "last_device": {"mac": "AA:BB:CC:00:00:%02X" % idx, "ip": f"10.55.0.{100 + idx}", "name": f"DEV-{idx}", "seen_at": datetime.now(timezone.utc).isoformat()}}


async def main():
    from port_memory import classify, record_ports, classify_port
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    await db.port_memory.delete_many({"local_ip": SW}); await db.switch_ports.delete_many({"local_ip": SW})
    await db.managed_devices.delete_many({"ip": SW}); await db.alerts.delete_many({"dedup_key": {"$regex": f"^{CID}:{SW}:portlink"}})
    try:
        now = datetime.now(timezone.utc)
        # 1 sempre attiva | 2 a orario (up lun-ven 8-18) | 3 saltuaria | 4 mai usata | 5 in apprendimento | 6 PoE standby
        docs = [mem(1, 30, lambda h, wd: True), mem(2, 30, lambda h, wd: wd < 5 and 8 <= h < 18),
                mem(3, 30, lambda h, wd: h in (10, 11) and wd == 2), mem(4, 30, lambda h, wd: False),
                mem(5, 2, lambda h, wd: True), mem(6, 30, lambda h, wd: True, poe=6.5)]
        await db.port_memory.insert_many(docs)
        c = classify(docs[0], False); assert c["verdict"] == "anomalous" and c["profile"] == "always_on", c
        c = classify(docs[3], False); assert c["verdict"] == "unused", c
        c = classify(docs[2], False); assert c["verdict"] == "habitual" and c["profile"] == "sporadic", c
        c = classify(docs[4], False); assert c["verdict"] == "learning" and c["learning_days_left"] > 0, c
        c = classify(docs[5], False, poe_w=5.9); assert c["verdict"] == "standby_poe", c
        c = classify(docs[0], True); assert c["verdict"] == "up", c
        # a orario: martedì 21:00 locale → abituale ; martedì 10:00 → anomalo
        tue = now
        while tue.weekday() != 1:
            tue += timedelta(days=1)
        night = tue.replace(hour=19, minute=0)   # 19 UTC = 21 locale (estate) / 20 (inverno) → fuori 8-18
        morn = tue.replace(hour=8, minute=30)    # 8:30 UTC = 10:30/9:30 locale → dentro
        c1 = classify(docs[1], False, at=night); c2 = classify(docs[1], False, at=morn)
        assert c1["verdict"] == "habitual" and c2["verdict"] == "anomalous", (c1["verdict"], c2["verdict"])
        print("STEP1 OK: classify → always_on=anomalo, orario=abituale/anomalo per fascia, saltuaria, mai usata, learning, standby PoE, up")

        # record_ports: incrementa istogrammi e first_seen
        ports = [{"idx": 7, "name": "Gi1/0/7", "oper": 1, "admin": 1, "speed_mbps": 1000, "poe_watt": 4.2},
                 {"idx": 8, "name": "Gi1/0/8", "oper": 2, "admin": 1, "speed_mbps": 0}, {"idx": 9, "name": "Gi1/0/9", "oper": 2, "admin": 2}]
        n = await record_ports(db, CID, SW, ports)
        assert n == 2, n
        m7 = await db.port_memory.find_one({"local_ip": SW, "idx": 7}, {"_id": 0})
        assert m7["samples"] == 1 and m7["up_samples"] == 1 and m7["usual_speed_mbps"] == 1000 and m7["poe_samples"] == 1 and m7.get("first_seen"), m7
        await record_ports(db, CID, SW, ports)
        m8 = await db.port_memory.find_one({"local_ip": SW, "idx": 8}, {"_id": 0})
        assert m8["samples"] == 2 and m8.get("up_samples", 0) == 0 and m8.get("last_down_at"), m8
        assert await db.port_memory.count_documents({"local_ip": SW, "idx": 9}) == 0
        print("STEP2 OK: record_ports aggiorna istogrammi, velocità/PoE abituali, ignora admin-down")

        # Filtro alert porta giù: porta 3 (saltuaria) verso device vitale → soppresso; porta 1 (sempre attiva) → alert
        from port_link_alerts import evaluate_port_links
        await db.managed_devices.insert_one({"client_id": CID, "ip": SW, "name": "SW-TEST", "device_type": "switch"})
        await db.managed_devices.insert_many([{"client_id": CID, "ip": f"10.55.0.{100 + i}", "name": f"DEV-{i}", "device_type": "server", "is_vital": True} for i in (1, 3)])
        await db.mac_connections.delete_many({"from_ip": SW})
        await db.mac_connections.insert_many([{"client_id": CID, "from_ip": SW, "from_port": i, "to_ip": f"10.55.0.{100 + i}"} for i in (1, 3)])
        prev = {1: {"oper": 1, "admin": 1}, 3: {"oper": 1, "admin": 1}}
        new = [{"idx": 1, "name": "Gi1/0/1", "oper": 2, "admin": 1}, {"idx": 3, "name": "Gi1/0/3", "oper": 2, "admin": 1}]
        await evaluate_port_links(db, CID, SW, prev, new)
        a1 = await db.alerts.find_one({"dedup_key": f"{CID}:{SW}:portlink:1"}, {"_id": 0, "message": 1})
        a3 = await db.alerts.find_one({"dedup_key": f"{CID}:{SW}:portlink:3"})
        assert a1 and "Abitudine porta" in a1["message"], a1
        assert a3 is None, "alert porta saltuaria doveva essere soppresso"
        print("STEP3 OK: alert porta giù solo per porta 'sempre attiva' (con nota abitudine), soppresso per saltuaria")

        # API topology: habit per porta
        await db.switch_ports.insert_many([{"client_id": CID, "local_ip": SW, "idx": i, "name": f"GigabitEthernet1/0/{i}", "oper": 2 if i != 7 else 1, "admin": 1,
                                            "speed_mbps": 1000, "updated_at": now.isoformat()} for i in (1, 2, 3, 4, 5, 7)])
        H = {"Authorization": f"Bearer {login()}"}
        r = requests.get(f"{API}/api/devices/{SW}/switch-ports", params={"client_id": CID}, headers=H)
        assert r.status_code == 200, r.text
        by = {p["idx"]: p for p in r.json()["ports"]}
        assert by[1]["habit"]["verdict"] == "anomalous" and by[1]["habit"]["last_device"]["name"] == "DEV-1", by[1]["habit"]
        assert by[4]["habit"]["verdict"] == "unused" and by[5]["habit"]["verdict"] == "learning" and by[3]["habit"]["verdict"] == "habitual"
        assert by[7]["habit"] is not None and by[7]["habit"]["verdict"] == "up"
        print("STEP4 OK: GET /switch-ports espone habit per porta (verdetto, ultimo device, profilo)")
        c = await classify_port(db, CID, SW, 1, False); assert c["verdict"] == "anomalous"
        print("\nALL PORT MEMORY TESTS PASSED")
    finally:
        await db.port_memory.delete_many({"local_ip": SW}); await db.switch_ports.delete_many({"local_ip": SW})
        await db.managed_devices.delete_many({"client_id": CID, "ip": {"$regex": "^10\\.55\\.0\\."}})
        await db.mac_connections.delete_many({"from_ip": SW})
        await db.alerts.delete_many({"dedup_key": {"$regex": f"^{CID}:{SW}:portlink"}})


if __name__ == "__main__":
    asyncio.run(main())
