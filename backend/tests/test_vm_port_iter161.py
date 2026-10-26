"""Test porte con piu' dispositivi / host VM (iter161)."""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db  # noqa: E402
import port_memory as pm  # noqa: E402
from vm_port import build_vm_host  # noqa: E402

CID, SW = "test-vmport-161", "10.161.0.1"
DC, DATI, NEWVM, ALIEN = "00:15:5D:60:06:01", "00:15:5D:60:06:00", "00:15:5D:60:06:09", "3C:52:82:11:22:33"


async def eps(*macs):
    await db.discovered_endpoints.delete_many({"client_id": CID})
    now = datetime.now(timezone.utc).isoformat()
    for i, m in enumerate(macs):
        await db.discovered_endpoints.insert_one({"client_id": CID, "switch_ip": SW, "port": 52, "mac": m, "ip": f"192.168.1.{10 + i}", "last_seen_at": now})
    await db.port_memory.update_one({"client_id": CID, "local_ip": SW, "idx": 52}, {"$unset": {"device_refreshed_at": ""}})


async def main():
    ok = 0
    now = datetime.now(timezone.utc)
    try:
        await db.clients.insert_one({"id": CID, "name": "TEST VM PORT"})
        await db.port_memory.insert_one({"client_id": CID, "local_ip": SW, "idx": 52, "name": "Ten-GigabitEthernet1/0/52",
                                         "first_seen": (now - timedelta(days=30)).isoformat(),
                                         "last_device": {"mac": DC, "ip": "192.168.1.11", "name": "SRVDC"},
                                         "prev_device": {"mac": DC, "name": "SRVDC"}, "device_changed_at": now.isoformat()})
        await db.alerts.insert_one({"id": "false-1", "client_id": CID, "device_ip": SW, "source_type": "port_device_change", "status": "active",
                                    "raw_data": {"idx": 52, "prev_device": {"mac": DC}, "new_device": {"mac": DATI}}})
        await eps(DATI, DC)
        await pm._refresh_devices(db, CID, SW, [52], now)
        doc = await db.port_memory.find_one({"client_id": CID, "idx": 52}, {"_id": 0})
        assert doc["is_vm_port"] and {d["mac"] for d in doc["port_devices"]} == {DC, DATI} and "prev_device" not in doc, doc
        assert doc["last_device"]["mac"] == DC  # rappresentante stabile
        assert (await db.alerts.find_one({"id": "false-1"}))["status"] == "resolved"
        assert await db.alerts.count_documents({"client_id": CID, "status": "active"}) == 0
        ok += 1
        print("1. 2 VM sulla porta → nessun cambio, alert falso chiuso, insieme memorizzato OK")

        for _ in range(3):  # alternanza SRVDC/SRVDATI → mai alert
            await eps(DC)
            await pm._refresh_devices(db, CID, SW, [52], now)
            await eps(DATI)
            await pm._refresh_devices(db, CID, SW, [52], now)
        assert await db.alerts.count_documents({"client_id": CID, "status": "active"}) == 0
        ok += 1
        print("2. alternanza VM → nessun alert OK")

        await eps(DC, DATI, NEWVM)
        await pm._refresh_devices(db, CID, SW, [52], now)
        al = await db.alerts.find_one({"client_id": CID, "source_type": "port_new_vm"}, {"_id": 0})
        assert al and al["severity"] == "low" and not await db.alerts.find_one({"client_id": CID, "source_type": "port_device_change", "status": "active"}), al
        ok += 1
        print("3. VM nuova → alert informativo low OK")

        await eps(ALIEN)
        await pm._refresh_devices(db, CID, SW, [52], now)
        ch = await db.alerts.find_one({"client_id": CID, "source_type": "port_device_change", "status": "active"}, {"_id": 0})
        assert ch and ch["raw_data"]["new_device"]["mac"] == ALIEN, ch
        ok += 1
        print("4. sparito tutto l'insieme + device nuovo → Dispositivo cambiato OK")

        att = [{"mac": DATI, "ip": "192.168.1.6", "name": "SRVDATI"}, {"mac": DC, "ip": "192.168.1.7", "name": "SRVDC"},
               {"mac": "D4:F5:EF:00:00:01", "ip": "192.168.1.5", "name": "HOSTHV"}]
        h = build_vm_host(att, [], {})
        assert h["kind"] == "Hyper-V" and h["host_ip"] == "192.168.1.5" and len(h["vms"]) == 2, h
        assert build_vm_host([att[2]], [], {}) is None
        assert build_vm_host([{"mac": "AA:BB:CC:00:00:01", "name": "a"}, {"mac": "AA:BB:CC:00:00:02", "name": "b"}], [], {}) is None
        ok += 1
        print("5. build_vm_host: host fisico + VM OK")
    finally:
        for c in ("port_memory", "discovered_endpoints", "alerts", "clients"):
            await db[c].delete_many({"client_id": CID} if c != "clients" else {"id": CID})
    print(f"PASS {ok}/5")


asyncio.run(main())
