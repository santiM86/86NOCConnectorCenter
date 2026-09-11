"""Seed scenario Evidence Fusion v2: PC-MARIO (10.10.41.50) giù da 25 min, porta 3 di CHASW-B down,
memoria porta 'a orario' (down fuori orario ufficio = abituale), Datto offline con lastSeen coincidente.
Uso: cd /app/backend && python tests/seed_fusion_iter151.py
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

CID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"
SW = "10.10.41.220"
IP = "10.10.41.50"
MAC = "AA:BB:CC:00:00:03"
NOW = datetime.now(timezone.utc)
DOWN_AT = NOW - timedelta(minutes=25)


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    await db.managed_devices.update_one({"client_id": CID, "ip": IP}, {"$set": {
        "client_id": CID, "ip": IP, "name": "PC-MARIO", "device_type": "workstation", "mac": MAC, "is_vital": True,
        "datto_uid": "datto-pc-mario", "updated_at": NOW.isoformat()}}, upsert=True)
    await db.device_poll_status.update_one({"client_id": CID, "device_ip": IP}, {"$set": {
        "client_id": CID, "device_ip": IP, "reachable": False, "unreachable_since": DOWN_AT.isoformat(),
        "last_reachable_at": DOWN_AT.isoformat(), "last_poll_at": (NOW - timedelta(minutes=1)).isoformat(),
        "updated_at": (NOW - timedelta(minutes=1)).isoformat(), "consecutive_failures": 12, "primary_mac": MAC}}, upsert=True)
    await db.discovered_endpoints.update_one({"client_id": CID, "mac": MAC}, {"$set": {
        "client_id": CID, "ip": IP, "mac": MAC, "switch_ip": SW, "port": 3, "hostname": "PC-MARIO",
        "last_seen_at": DOWN_AT.isoformat(), "last_seen_via": "snmp"}}, upsert=True)
    await db.switch_ports.update_one({"client_id": CID, "local_ip": SW, "idx": 3}, {"$set": {
        "client_id": CID, "local_ip": SW, "idx": 3, "name": "GigabitEthernet1/0/3", "oper": 2, "admin": 1,
        "speed_mbps": 0, "poe_watt": 0, "updated_at": (NOW - timedelta(minutes=2)).isoformat()}}, upsert=True)
    await db.datto_devices.update_one({"uid": "datto-pc-mario"}, {"$set": {
        "uid": "datto-pc-mario", "client_id": CID, "name": "PC-MARIO", "hostname": "PC-MARIO", "ip": IP, "ip_list": [IP],
        "mac_list": [MAC], "online": False, "datto_last_seen": (DOWN_AT + timedelta(minutes=1)).isoformat(),
        "fetched_at": (NOW - timedelta(minutes=3)).isoformat()}}, upsert=True)
    # storico spegnimenti: ogni giorno feriale alla stessa ora locale degli ultimi 14 giorni
    await db.device_status_events.delete_many({"client_id": CID, "device_ip": IP})
    await db.device_status_events.insert_many([
        {"client_id": CID, "device_ip": IP, "event": "down", "at": (DOWN_AT - timedelta(days=d)).isoformat()} for d in range(1, 15)])
    print("seeded PC-MARIO down scenario")


asyncio.run(main())
