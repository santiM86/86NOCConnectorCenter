"""Shodan provider: lookup senza key, risky_ports, alert nuove porte/servizi rischiosi (mock HTTP). cd /app/backend && set -a && . ./.env && set +a && python tests/test_shodan_iter157.py"""
import asyncio
import sys
import uuid

sys.path.insert(0, "/app/backend")
from database import db  # noqa: E402
from services import osint_service as osint  # noqa: E402
from services import osint_poller as poller  # noqa: E402

CID = f"test-shodan-{uuid.uuid4().hex[:6]}"
IP = "8.8.4.4"
TID = f"wan-{CID}"

SHODAN_FAKE = {"found": True, "ports": [443, 3389, 8443], "vulns": ["CVE-2024-1234"], "hostnames": ["vpn.example.it"], "domains": ["example.it"],
               "tags": [], "os": "Windows", "org": "Telecom Italia", "isp": "TIM", "asn": "AS3269", "country": "Italy", "city": "Milano",
               "last_update": "2026-06-01T10:00:00", "services": [{"port": 3389, "transport": "tcp", "module": "rdp", "product": "Remote Desktop Protocol", "version": None, "banner": "", "cpe": [], "vulns": []},
                                                                 {"port": 443, "transport": "tcp", "module": "https", "product": "nginx", "version": "1.24.0", "banner": "", "cpe": [], "vulns": []}]}


async def main():
    ok = 0
    assert "shodan" in osint.KEYED_PROVIDERS
    assert osint.risky_ports([80, 443, 3389, 445, 22]) == [{"port": 445, "service": "SMB"}, {"port": 3389, "service": "RDP"}]
    assert await osint._shodan_host(IP) is None  # nessuna key → None (InternetDB resta la fonte)
    ok += 1
    print("1. provider registrato, risky_ports, no-key → None OK")

    try:
        await db.wan_targets.insert_one({"id": TID, "client_id": CID, "public_ip": IP, "label": "FW-TEST", "monitor_type": "ping"})
        osint._internetdb = lambda ip: asyncio.sleep(0, result={"ports": [443], "vulns": [], "hostnames": [], "tags": []})  # type: ignore
        osint._shodan_host = lambda ip: asyncio.sleep(0, result=SHODAN_FAKE)  # type: ignore
        poller.EXPOSURE_BATCH = 50
        await poller.osint_exposure_tick()
        doc = await db.osint_exposure.find_one({"target_id": TID}, {"_id": 0})
        assert doc and doc["ports"] == [443, 3389, 8443] and doc["source"] == "shodan+internetdb" and doc["shodan"]["org"] == "Telecom Italia", doc
        assert doc["risky_ports"] == [{"port": 3389, "service": "RDP"}] and doc["new_ports"] == []
        titles = [a["title"] for a in await db.alerts.find({"client_id": CID}, {"_id": 0, "title": 1, "severity": 1}).to_list(20)]
        assert any("servizi rischiosi esposti" in t for t in titles), titles
        ok += 1
        print("2. tick: merge Shodan+InternetDB, risky RDP → alert high OK")

        # seconda scansione: nuova porta 22 → alert medium "nuove porte"; forzo re-scan azzerando last_scan
        SHODAN_FAKE["ports"] = [22, 443, 3389, 8443]
        await db.osint_exposure.update_one({"target_id": TID}, {"$set": {"last_scan": "2020-01-01T00:00:00+00:00"}})
        await poller.osint_exposure_tick()
        doc = await db.osint_exposure.find_one({"target_id": TID}, {"_id": 0})
        assert doc["new_ports"] == [22], doc["new_ports"]
        titles = [a["title"] for a in await db.alerts.find({"client_id": CID}, {"_id": 0, "title": 1}).to_list(20)]
        assert any("nuove porte esposte" in t and "22" in t for t in titles), titles
        n_risky = await db.alerts.count_documents({"client_id": CID, "source_type": "osint_exposed_service"})
        assert n_risky == 1, n_risky  # dedup
        ok += 1
        print("3. nuova porta → alert medium, dedup servizi rischiosi OK")

        # terza: RDP chiuso → auto-resolve alert servizi rischiosi
        SHODAN_FAKE["ports"] = [22, 443, 8443]
        SHODAN_FAKE["services"] = [s for s in SHODAN_FAKE["services"] if s["port"] != 3389]
        await db.osint_exposure.update_one({"target_id": TID}, {"$set": {"last_scan": "2020-01-01T00:00:00+00:00"}})
        await poller.osint_exposure_tick()
        a = await db.alerts.find_one({"client_id": CID, "source_type": "osint_exposed_service"}, {"_id": 0, "status": 1})
        assert a["status"] == "resolved", a
        ok += 1
        print("4. servizio rischioso chiuso → auto-resolve OK")
    finally:
        await db.wan_targets.delete_many({"client_id": CID})
        await db.osint_exposure.delete_many({"client_id": CID})
        await db.alerts.delete_many({"client_id": CID})
    print(f"PASS {ok}/4")


asyncio.run(main())
