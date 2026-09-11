"""Iter147 — Regressione overview KeyError (endpoint vitale prima di device infra) + VPN rimossa."""
import asyncio
import os
import sys
import uuid

import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv("/app/backend/.env")
API = "https://noc-alert-hub-2.preview.emergentagent.com"


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    cid = f"test-ov-{uuid.uuid4().hex[:8]}"
    try:
        await db.clients.insert_one({"id": cid, "name": "TEST-OVERVIEW-KEYERROR", "status": "active"})
        # 1) PC (endpoint) VITALE inserito per primo → crea devices_by_client[cid] nel blocco vitali
        await db.managed_devices.insert_one({"id": str(uuid.uuid4()), "client_id": cid, "ip": "10.66.0.10", "name": "PC-VITALE",
                                             "device_type": "endpoint", "is_vital": True, "monitor_type": "ping"})
        # 2) switch (infra) dopo → prima del fix: devices_detail_by_client[cid] mancante → KeyError(cid) → HTTP 500
        await db.managed_devices.insert_one({"id": str(uuid.uuid4()), "client_id": cid, "ip": "10.66.0.1", "name": "SW-CORE",
                                             "device_type": "switch", "is_vital": True, "monitor_type": "snmp"})
        from routes.overview import _compute_clients_overview
        ov = await _compute_clients_overview()
        c = next((x for x in ov["clients"] if x["id"] == cid), None)
        assert c, "cliente test non presente nella overview"
        assert c["devices"]["vital_total"] == 2, c["devices"]
        print("STEP1 OK: overview con endpoint vitale + switch → nessun KeyError, vital_total=2")

        # VPN rimossa
        for path in ("/api/admin/wireguard/peers", "/api/admin/wireguard/server-status", "/api/connector/wireguard/session"):
            r = requests.get(f"{API}{path}")
            assert r.status_code == 404, (path, r.status_code)
        names = await db.list_collection_names()
        assert not [n for n in names if "wireguard" in n.lower()], names
        print("STEP2 OK: endpoint WireGuard 404, collection VPN eliminate")
        print("\nALL OVERVIEW/VPN TESTS PASSED")
    finally:
        await db.clients.delete_many({"id": cid})
        await db.managed_devices.delete_many({"client_id": cid})
        await db.device_poll_status.delete_many({"client_id": cid})


if __name__ == "__main__":
    asyncio.run(main())
