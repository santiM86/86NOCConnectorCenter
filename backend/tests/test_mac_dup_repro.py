"""Repro indipendente scenario NAS01 duplicato per iter157."""
import asyncio
import sys

sys.path.insert(0, "/app/backend")
from database import db  # noqa: E402
from mac_follow import apply_mac_follow  # noqa: E402

CID = "test-qa-macdup"
MAC_NAS = "00:11:32:48:d6:99"
MAC_PRN = "00:1b:cc:00:00:55"


async def cleanup():
    for c in ("managed_devices", "alerts", "device_credentials", "port_memory", "discovered_endpoints"):
        await db[c].delete_many({"client_id": CID})


async def main():
    await cleanup()
    ok = 0
    try:
        # (a) NAS01 offline + duplicato stesso MAC
        await db.managed_devices.insert_many([
            {"id": f"{CID}-A", "client_id": CID, "ip": "192.168.200.12", "ip_address": "192.168.200.12",
             "mac": MAC_NAS, "name": "NAS01", "status": "offline", "consecutive_ping_failures": 5,
             "is_vital": True, "profile_key": "synology_dsm"},
            {"id": f"{CID}-B", "client_id": CID, "ip": "10.100.110.3", "ip_address": "10.100.110.3",
             "mac": MAC_NAS, "name": "NAS01", "source": "ui_scan_button"},
        ])
        ch = await apply_mac_follow(CID, [
            {"ip": "192.168.200.12", "mac": MAC_NAS},
            {"ip": "10.100.110.3", "mac": MAC_NAS},
        ], "test")
        assert len(ch) == 1, f"expected 1 change got {ch}"
        assert ch[0]["old_ip"] == "192.168.200.12" and ch[0]["new_ip"] == "10.100.110.3", ch
        A = await db.managed_devices.find_one({"id": f"{CID}-A"}, {"_id": 0})
        assert A["ip"] == "10.100.110.3" and A["ip_address"] == "10.100.110.3", A
        B = await db.managed_devices.find_one({"id": f"{CID}-B"})
        assert B is None, "duplicato non eliminato"
        cnt = await db.managed_devices.count_documents({"client_id": CID, "mac": MAC_NAS})
        assert cnt == 1, f"expected 1 device con MAC, got {cnt}"
        al = await db.alerts.find_one({"client_id": CID, "source_type": "mac_follow_ip_update"}, {"_id": 0})
        assert al, "alert mac_follow_ip_update mancante"
        assert al["severity"] == "high", al
        assert al["title"].startswith("VITALE IP cambiato"), al["title"]
        assert "duplicata" in al["message"], al["message"]
        ok += 1
        print("(a) NAS01 offline + duplicato → follow + merge + alert HIGH VITALE 'duplicata' OK")

        # (b) ora A online, endpoints su 10.100.110.3 + 10.100.110.9 → multi-ip alert, no change
        await db.managed_devices.update_one({"id": f"{CID}-A"}, {"$set": {"status": "online", "consecutive_ping_failures": 0}})
        ch2 = await apply_mac_follow(CID, [
            {"ip": "10.100.110.3", "mac": MAC_NAS},
            {"ip": "10.100.110.9", "mac": MAC_NAS},
        ], "test")
        assert ch2 == [], f"expected no change got {ch2}"
        A2 = await db.managed_devices.find_one({"id": f"{CID}-A"}, {"_id": 0})
        assert A2["ip"] == "10.100.110.3", A2
        mi = await db.alerts.find_one({"client_id": CID, "source_type": "mac_follow_multi_ip"}, {"_id": 0})
        assert mi, "alert multi_ip mancante"
        assert "10.100.110.9" in mi["title"], mi["title"]
        assert mi["severity"] == "high", mi
        ok += 1
        print("(b) vecchio vivo + MAC anche altrove → alert mac_follow_multi_ip con 10.100.110.9 OK")

        # (c) regressione: device C online, endpoint su nuovo IP; vecchio IP NON negli endpoints
        await db.managed_devices.insert_one({
            "id": f"{CID}-C", "client_id": CID, "ip": "10.9.0.50", "ip_address": "10.9.0.50",
            "mac": MAC_PRN, "name": "PRINTER", "status": "online",
        })
        ch3 = await apply_mac_follow(CID, [{"ip": "10.9.0.73", "mac": MAC_PRN}], "test")
        assert len(ch3) == 1 and ch3[0]["old_ip"] == "10.9.0.50" and ch3[0]["new_ip"] == "10.9.0.73", ch3
        C = await db.managed_devices.find_one({"id": f"{CID}-C"}, {"_id": 0})
        assert C["ip"] == "10.9.0.73", C
        al3 = await db.alerts.find_one({"client_id": CID, "device_ip": "10.9.0.73", "source_type": "mac_follow_ip_update"}, {"_id": 0})
        assert al3 and al3["severity"] == "medium" and al3["title"].startswith("IP cambiato"), al3
        ok += 1
        print("(c) regressione: vecchio IP assente negli endpoints → change medium 'IP cambiato' OK")
    finally:
        await cleanup()
    print(f"PASS {ok}/3")


asyncio.run(main())
