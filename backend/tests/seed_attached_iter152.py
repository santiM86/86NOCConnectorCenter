"""Seed: porta 1 di CHASW-B con host Hyper-V SRV-DC01 + 3 VM (MAC 00:15:5D) → test 'attached'."""
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

CID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"
SW = "10.10.41.220"


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    now = datetime.now(timezone.utc).isoformat()
    await db.switch_ports.update_one({"client_id": CID, "local_ip": SW, "idx": 1}, {"$set": {
        "client_id": CID, "local_ip": SW, "idx": 1, "name": "GigabitEthernet1/0/1", "oper": 1, "admin": 1, "speed_mbps": 1000, "updated_at": now}}, upsert=True)
    docs = [("AA:BB:CC:00:00:01", "10.10.41.10", "SRV-DC01", True), ("00:15:5D:01:70:04", "10.10.41.20", "VM-DC", False),
            ("00:15:5D:01:70:05", "10.10.41.21", "VM-SQL", False), ("00:15:5D:01:70:06", "", "", False)]
    for mac, ip, name, mg in docs:
        await db.discovered_endpoints.update_one({"client_id": CID, "mac": mac}, {"$set": {
            "client_id": CID, "mac": mac, "ip": ip, "hostname": name, "switch_ip": SW, "port": 1,
            "last_seen_at": now, "last_seen_via": "snmp", "is_managed": mg}}, upsert=True)
    await db.managed_devices.update_one({"client_id": CID, "ip": "10.10.41.10"}, {"$set": {
        "client_id": CID, "ip": "10.10.41.10", "name": "SRV-DC01", "device_name": "SRV-DC01", "device_type": "server", "mac": "AA:BB:CC:00:00:01"}}, upsert=True)
    print("seeded port 1 attached")


asyncio.run(main())
