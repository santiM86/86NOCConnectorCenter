"""Test aggancio MAC → IP (mac_follow) + fingerprint profili TP-Link. Esegui: cd /app/backend && python tests/test_mac_follow_iter154.py"""
import asyncio
import sys
import uuid

sys.path.insert(0, "/app/backend")
from database import db  # noqa: E402
from mac_follow import apply_mac_follow  # noqa: E402
from device_profiles import fingerprint  # noqa: E402

CID = f"test-macfollow-{uuid.uuid4().hex[:6]}"
MAC = "b0:be:76:12:34:56"


async def main():
    ok = 0
    # fingerprint
    assert fingerprint("1.3.6.1.4.1.11863.1.1.1", "JetStream 24-Port Gigabit L2 Managed Switch")["key"] == "tplink_omada_switch"
    assert fingerprint("1.3.6.1.4.1.11863.1.1.1", "TL-SG3428 3.0")["key"] == "tplink_omada_switch"
    assert fingerprint("1.3.6.1.4.1.11863.5.1", "ER605 2.0")["key"] == "tplink_omada_gateway"
    assert fingerprint("1.3.6.1.4.1.11863.2.1", "EAP245 v3")["key"] == "tplink_omada_ap"
    assert fingerprint("1.3.6.1.4.1.11863.9", "TP-Link Omada")["key"] == "tplink_omada_ap"
    assert fingerprint("1.3.6.1.4.1.99999", "Generic router") is None
    ok += 1
    print("1. fingerprint TP-Link switch/gateway/ap OK")

    try:
        await db.managed_devices.insert_many([
            {"id": f"{CID}-a", "client_id": CID, "ip": "10.9.0.50", "ip_address": "10.9.0.50", "mac": MAC, "name": "PRINTER-DHCP"},
            {"id": f"{CID}-b", "client_id": CID, "ip": "10.9.0.60", "ip_address": "10.9.0.60", "mac": "aa:bb:cc:00:00:01", "name": "SRV-STATIC"},
            {"id": f"{CID}-c", "client_id": CID, "ip": "10.9.0.70", "ip_address": "10.9.0.70", "mac": "aa:bb:cc:00:00:02", "name": "NO-FOLLOW", "follow_mac": False},
        ])
        await db.device_credentials.insert_one({"client_id": CID, "device_ip": "10.9.0.50", "credential_type": "snmp", "id": f"{CID}-cred"})
        await db.port_memory.insert_one({"client_id": CID, "local_ip": "10.9.0.50", "idx": 1})

        # 2. MAC visto su nuovo IP → segue
        ch = await apply_mac_follow(CID, [{"ip": "10.9.0.73", "mac": "B0-BE-76-12-34-56"}, {"ip": "10.9.0.60", "mac": "aa:bb:cc:00:00:01"}], "test")
        assert len(ch) == 1 and ch[0]["old_ip"] == "10.9.0.50" and ch[0]["new_ip"] == "10.9.0.73", ch
        md = await db.managed_devices.find_one({"id": f"{CID}-a"}, {"_id": 0})
        assert md["ip"] == "10.9.0.73" and md["ip_address"] == "10.9.0.73" and md["ip_previous"] == "10.9.0.50" and len(md["ip_history"]) == 1
        assert await db.device_credentials.count_documents({"client_id": CID, "device_ip": "10.9.0.73"}) == 1
        assert await db.port_memory.count_documents({"client_id": CID, "local_ip": "10.9.0.73"}) == 1
        al = await db.alerts.find_one({"client_id": CID, "source_type": "mac_follow_ip_update"}, {"_id": 0})
        assert al and "10.9.0.50 → 10.9.0.73" in al["title"], al
        ok += 1
        print("2. follow applicato + rekey credenziali/port_memory + alert OK")

        # 3. idempotente: stesso batch → nessun cambio
        assert await apply_mac_follow(CID, [{"ip": "10.9.0.73", "mac": MAC}], "test") == []
        ok += 1
        print("3. idempotenza OK")

        # 4. conflitto: nuovo IP appartiene ad altro device gestito con MAC diverso → skip
        assert await apply_mac_follow(CID, [{"ip": "10.9.0.60", "mac": MAC}], "test") == []
        assert (await db.managed_devices.find_one({"id": f"{CID}-a"}))["ip"] == "10.9.0.73"
        ok += 1
        print("4. conflitto IP di altro device → skip OK")

        # 5. follow_mac=False → non segue
        assert await apply_mac_follow(CID, [{"ip": "10.9.0.99", "mac": "aa:bb:cc:00:00:02"}], "test") == []
        ok += 1
        print("5. follow_mac=False rispettato OK")

        # 6. MAC su 2 IP contemporaneamente (multi-IP) → ambiguo, skip
        assert await apply_mac_follow(CID, [{"ip": "10.9.0.80", "mac": MAC}, {"ip": "10.9.0.81", "mac": MAC}], "test") == []
        ok += 1
        print("6. MAC ambiguo su 2 IP → skip OK")

        # 7. device agganciato SOLO via MAC (ip None) → primo discovery assegna l'IP (alert low "IP rilevato")
        await db.managed_devices.insert_one({"id": f"{CID}-d", "client_id": CID, "ip": None, "mac": "00:1b:cc:00:00:09", "name": "NOTEBOOK-DHCP", "follow_mac": True, "ip_pending": True})
        ch = await apply_mac_follow(CID, [{"ip": "10.9.0.120", "mac": "00:1B:CC:00:00:09"}], "test")
        assert len(ch) == 1 and ch[0]["old_ip"] is None and ch[0]["new_ip"] == "10.9.0.120", ch
        md = await db.managed_devices.find_one({"id": f"{CID}-d"}, {"_id": 0})
        assert md["ip"] == "10.9.0.120" and md["ip_address"] == "10.9.0.120" and md["ip_pending"] is False
        al = await db.alerts.find_one({"client_id": CID, "device_ip": "10.9.0.120"}, {"_id": 0})
        assert al and al["title"].startswith("IP rilevato: NOTEBOOK-DHCP") and al["severity"] == "low", al
        ok += 1
        print("7. device solo-MAC → IP assegnato al primo discovery OK")

        # 8. resolve_ip_from_discovery: MAC già visto dal discovery recente → IP immediato
        from mac_follow import resolve_ip_from_discovery
        from datetime import datetime, timezone
        await db.discovered_endpoints.insert_one({"client_id": CID, "ip": "10.9.0.130", "mac": "00:1b:cc:00:00:10", "last_seen_at": datetime.now(timezone.utc).isoformat()})
        assert await resolve_ip_from_discovery(CID, "00-1B-CC-00-00-10") == "10.9.0.130"
        assert await resolve_ip_from_discovery(CID, "aa:bb:cc:00:00:99") is None
        ok += 1
        print("8. resolve_ip_from_discovery OK")
        # 9. Scenario NAS01: vecchio IP ancora in ARP (stantio) ma device offline + voce DUPLICATA stesso MAC sul nuovo IP → follow + merge
        await db.managed_devices.insert_many([
            {"id": f"{CID}-nas", "client_id": CID, "ip": "192.168.200.12", "ip_address": "192.168.200.12", "mac": "00:11:32:48:d6:99", "name": "NAS01", "status": "offline", "consecutive_ping_failures": 5, "profile_key": "synology_dsm", "is_vital": True},
            {"id": f"{CID}-nasdup", "client_id": CID, "ip": "10.100.110.3", "ip_address": "10.100.110.3", "mac": "00:11:32:48:d6:99", "name": "NAS01", "source": "ui_scan_button"},
        ])
        ch = await apply_mac_follow(CID, [{"ip": "192.168.200.12", "mac": "00:11:32:48:D6:99"}, {"ip": "10.100.110.3", "mac": "00:11:32:48:d6:99"}], "test")
        assert len(ch) == 1 and ch[0]["old_ip"] == "192.168.200.12" and ch[0]["new_ip"] == "10.100.110.3", ch
        nas = await db.managed_devices.find_one({"id": f"{CID}-nas"}, {"_id": 0})
        assert nas["ip"] == "10.100.110.3" and nas["profile_key"] == "synology_dsm"
        assert await db.managed_devices.count_documents({"client_id": CID, "mac": "00:11:32:48:d6:99"}) == 1  # duplicato rimosso
        al = await db.alerts.find_one({"client_id": CID, "device_ip": "10.100.110.3", "source_type": "mac_follow_ip_update"}, {"_id": 0})
        assert al and al["severity"] == "high" and "VITALE IP cambiato" in al["title"] and "duplicata" in al["message"], al
        ok += 1
        print("9. NAS01: ARP stantio + duplicato stesso MAC → follow, merge, alert HIGH OK")

        # 10. vecchio IP VIVO + MAC visto anche altrove → nessuno spostamento, alert 'stesso MAC visto anche su'
        await db.managed_devices.update_one({"id": f"{CID}-nas"}, {"$set": {"status": "online", "consecutive_ping_failures": 0}})
        ch = await apply_mac_follow(CID, [{"ip": "10.100.110.3", "mac": "00:11:32:48:d6:99"}, {"ip": "10.100.110.9", "mac": "00:11:32:48:d6:99"}], "test")
        assert ch == [] and (await db.managed_devices.find_one({"id": f"{CID}-nas"}))["ip"] == "10.100.110.3"
        mi = await db.alerts.find_one({"client_id": CID, "source_type": "mac_follow_multi_ip"}, {"_id": 0})
        assert mi and "10.100.110.9" in mi["title"] and mi["severity"] == "high", mi
        ok += 1
        print("10. multi-IP con vecchio vivo → alert informativo, nessuno spostamento OK")
    finally:
        for c in ("managed_devices", "device_credentials", "port_memory", "alerts", "discovered_endpoints"):
            await db[c].delete_many({"client_id": CID})
    print(f"PASS {ok}/10")


asyncio.run(main())
