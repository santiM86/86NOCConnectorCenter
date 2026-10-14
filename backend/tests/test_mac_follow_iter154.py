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
        # 9. MAC CONDIVISO (3 VM dietro la stessa NIC, BLUEEDENSRV): nessuno spostamento, merge, cancellazione o alert
        M = "00:15:5d:aa:bb:01"
        await db.managed_devices.insert_many([
            {"id": f"{CID}-be{i}", "client_id": CID, "ip": f"10.180.118.{i}", "ip_address": f"10.180.118.{i}", "mac": M, "name": f"VM{i}",
             "status": "offline" if i == 5 else "online", "consecutive_ping_failures": 4 if i == 5 else 0, "virtualization": "hyperv", "is_vital": True}
            for i in (5, 6, 7)])
        await db.alerts.insert_one({"id": "old-mi", "client_id": CID, "source_type": "mac_follow_multi_ip", "status": "active", "title": "vecchio"})
        for eps in ([{"ip": "10.180.118.6", "mac": M}, {"ip": "10.180.118.7", "mac": M}],
                    [{"ip": "10.180.118.7", "mac": M}],
                    [{"ip": "10.180.118.5", "mac": M}, {"ip": "10.180.118.6", "mac": M}, {"ip": "10.180.118.7", "mac": M}]):
            ch = await apply_mac_follow(CID, eps, "test")
            assert ch == [], ch
        docs = await db.managed_devices.find({"client_id": CID, "mac": M}, {"_id": 0}).to_list(10)
        assert sorted(d["ip"] for d in docs) == ["10.180.118.5", "10.180.118.6", "10.180.118.7"] and all(d["virtualization"] == "hyperv" for d in docs), docs
        assert await db.alerts.count_documents({"client_id": CID, "status": "active", "$or": [{"source_type": "mac_follow_multi_ip"}, {"device_ip": {"$regex": "^10\\.180\\.118\\."}}]}) == 0
        ok += 1
        print("9. MAC condiviso (VM sulla stessa NIC) → tutto agganciato, nessuna anomalia, vecchi alert multi-IP chiusi OK")

        # 10. MAC esclusivo visto su 2 IP (vecchio ARP stantio) → nessuno spostamento e nessun alert
        await db.managed_devices.insert_one({"id": f"{CID}-nas", "client_id": CID, "ip": "192.168.200.12", "ip_address": "192.168.200.12", "mac": "00:11:32:48:d6:99", "name": "NAS01", "is_vital": True})
        ch = await apply_mac_follow(CID, [{"ip": "192.168.200.12", "mac": "00:11:32:48:d6:99"}, {"ip": "10.100.110.3", "mac": "00:11:32:48:d6:99"}], "test")
        assert ch == [] and (await db.managed_devices.find_one({"id": f"{CID}-nas"}))["ip"] == "192.168.200.12"
        assert await db.alerts.count_documents({"client_id": CID, "status": "active", "device_ip": {"$in": ["192.168.200.12", "10.100.110.3"]}}) == 0
        ok += 1
        print("10. MAC su 2 IP → nessuno spostamento, nessun alert OK")

        # 11. Scheda di rete cambiata su device vitale: 1a rilevazione = pending, 2a = MAC aggiornato + alert HIGH
        NEW = "00:11:32:aa:00:01"
        ch = await apply_mac_follow(CID, [{"ip": "192.168.200.12", "mac": NEW}], "test")
        nas = await db.managed_devices.find_one({"id": f"{CID}-nas"}, {"_id": 0})
        assert ch == [] and nas["mac"] == "00:11:32:48:d6:99" and nas["mac_change_pending"]["count"] == 1, nas
        assert not await db.alerts.find_one({"client_id": CID, "source_type": "nic_changed"})
        await apply_mac_follow(CID, [{"ip": "192.168.200.12", "mac": NEW}], "test")
        nas = await db.managed_devices.find_one({"id": f"{CID}-nas"}, {"_id": 0})
        assert nas["mac"] == NEW and nas["mac_previous"] == "00:11:32:48:d6:99" and "mac_change_pending" not in nas, nas
        al = await db.alerts.find_one({"client_id": CID, "source_type": "nic_changed"}, {"_id": 0})
        assert al and al["severity"] == "high" and "Scheda di rete cambiata" in al["title"], al
        ok += 1
        print("11. Scheda di rete cambiata → confermata su 2 rilevazioni, alert HIGH vitale OK")

        # 12. MAC diverso momentaneo (1 sola rilevazione, poi torna quello giusto) → pending annullato, nessun alert; non vitale = medium
        await db.managed_devices.insert_one({"id": f"{CID}-pc", "client_id": CID, "ip": "10.1.1.50", "ip_address": "10.1.1.50", "mac": "00:1b:21:00:00:50", "name": "PC50"})
        await apply_mac_follow(CID, [{"ip": "10.1.1.50", "mac": "00:1b:21:00:00:51"}], "test")
        await apply_mac_follow(CID, [{"ip": "10.1.1.50", "mac": "00:1b:21:00:00:50"}], "test")
        pc = await db.managed_devices.find_one({"id": f"{CID}-pc"}, {"_id": 0})
        assert pc["mac"] == "00:1b:21:00:00:50" and "mac_change_pending" not in pc, pc
        for _ in range(2):
            await apply_mac_follow(CID, [{"ip": "10.1.1.50", "mac": "00:1b:21:00:00:52"}], "test")
        al = await db.alerts.find_one({"client_id": CID, "source_type": "nic_changed", "device_ip": "10.1.1.50"}, {"_id": 0})
        assert al and al["severity"] == "medium", al
        # MAC di un ALTRO device gestito (gateway/proxy ARP) sull'IP → non e' una NIC nuova
        await apply_mac_follow(CID, [{"ip": "10.1.1.50", "mac": NEW}], "test")
        await apply_mac_follow(CID, [{"ip": "10.1.1.50", "mac": NEW}], "test")
        assert (await db.managed_devices.find_one({"id": f"{CID}-pc"}))["mac"] == "00:1b:21:00:00:52"
        ok += 1
        print("12. ARP momentaneo ignorato, non vitale = medium, MAC di altro device ignorato OK")

        # 13. MAC condiviso → rescue dei vitali disattivato
        from mac_follow import mac_is_shared
        assert await mac_is_shared(CID, M) and not await mac_is_shared(CID, NEW)
        ok += 1
        print("13. mac_is_shared (rescue disattivato su MAC condiviso) OK")
    finally:
        for c in ("managed_devices", "device_credentials", "port_memory", "alerts", "discovered_endpoints"):
            await db[c].delete_many({"client_id": CID})
    print(f"PASS {ok}/13")


asyncio.run(main())
