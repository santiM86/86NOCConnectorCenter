"""Verifica auto-link iLO↔host via serial number e hostname (DB preview reale, con cleanup)."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

from database import db
from routes.devices import autolink_ilo_hosts

CID = "__test_autolink_client__"
FAKE_USER = {"id": "u", "role": "admin"}


async def _seed():
    await _clean()
    # iLO 1: match per SERIAL con host .200
    await db.device_poll_status.insert_one({
        "client_id": CID, "device_ip": "10.9.9.203", "device_name": "GALVANSRV-iLO",
        "device_class": "hpe-ilo", "monitor_type": "redfish_direct",
        "redfish": {"serial_number": "CZ 21290-ABC", "host_name": "galvansrv.local"},
    })
    await db.device_credentials.insert_one({
        "client_id": CID, "credential_type": "ilo", "device_ip": "10.9.9.203",
    })
    # iLO 2: no serial → match per HOSTNAME con host .210
    await db.device_poll_status.insert_one({
        "client_id": CID, "device_ip": "10.9.9.211", "device_name": "WEBSRV-iLO",
        "device_class": "hpe-ilo", "monitor_type": "redfish_direct",
        "redfish": {"serial_number": "", "host_name": "WEBSRV.corp.example.com"},
    })
    await db.device_credentials.insert_one({
        "client_id": CID, "credential_type": "ilo", "device_ip": "10.9.9.211",
    })
    # Host .200 con serial via datto_uid (match iLO 1)
    await db.managed_devices.insert_one({
        "client_id": CID, "ip": "10.9.9.200", "name": "GALVANSRV",
        "device_type": "server", "datto_uid": "uid-200",
    })
    await db.datto_devices.insert_one({
        "client_id": CID, "uid": "uid-200", "serial": "CZ21290ABC",
        "name": "GALVANSRV", "hostname_short": "galvansrv",
    })
    # Host .210 con hostname (match iLO 2)
    await db.managed_devices.insert_one({
        "client_id": CID, "ip": "10.9.9.210", "name": "WEBSRV",
        "device_type": "server", "hostname": "websrv",
    })


async def _clean():
    for c in ("device_poll_status", "device_credentials", "managed_devices", "datto_devices"):
        await db[c].delete_many({"client_id": CID})


async def run():
    await _seed()
    try:
        # dry-run: 2 suggerimenti, nessuna modifica
        res = await autolink_ilo_hosts(CID, dry_run=True, current_user=FAKE_USER)
        assert res["summary"]["suggested"] == 2, res["summary"]
        assert res["summary"]["linked"] == 0
        by = {s["ilo_ip"]: s for s in res["suggestions"]}
        assert by["10.9.9.203"]["match_by"] == "serial" and by["10.9.9.203"]["host_ip"] == "10.9.9.200"
        assert by["10.9.9.211"]["match_by"] == "hostname" and by["10.9.9.211"]["host_ip"] == "10.9.9.210"
        cred = await db.device_credentials.find_one({"client_id": CID, "device_ip": "10.9.9.203"})
        assert not cred.get("host_ip"), "dry_run non deve modificare"
        print("[OK] dry_run: 2 match (serial + hostname), nessuna modifica")

        # apply: collega davvero
        res2 = await autolink_ilo_hosts(CID, dry_run=False, current_user=FAKE_USER)
        assert res2["summary"]["linked"] == 2, res2["summary"]
        c1 = await db.device_credentials.find_one({"client_id": CID, "device_ip": "10.9.9.203"})
        c2 = await db.device_credentials.find_one({"client_id": CID, "device_ip": "10.9.9.211"})
        assert c1.get("host_ip") == "10.9.9.200"
        assert c2.get("host_ip") == "10.9.9.210"
        print("[OK] apply: 2 iLO collegate (serial→.200, hostname→.210)")

        # idempotenza: ri-eseguendo → 0 nuovi link, 2 already_linked
        res3 = await autolink_ilo_hosts(CID, dry_run=False, current_user=FAKE_USER)
        assert res3["summary"]["linked"] == 0 and res3["summary"]["already_linked"] == 2, res3["summary"]
        print("[OK] idempotente: 0 nuovi, 2 già collegate")

        print("\nTUTTI I TEST PASSATI")
    finally:
        await _clean()


if __name__ == "__main__":
    asyncio.run(run())
