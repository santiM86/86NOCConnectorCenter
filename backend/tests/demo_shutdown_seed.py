import os, asyncio, sys
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
from motor.motor_asyncio import AsyncIOMotorClient

CID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"
IP = "192.168.1.254"
SW = "10.10.41.221"


async def m(mode):
    db = AsyncIOMotorClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
    if mode == "seed":
        now = datetime.now(timezone.utc)
        since = now.replace(hour=8, minute=25, second=0, microsecond=0)
        await db.device_poll_status.update_one({"client_id": CID, "device_ip": IP}, {"$set": {"reachable": False, "unreachable_since": since.isoformat(), "_demo_shutdown": True}})
        await db.discovered_endpoints.insert_one({"client_id": CID, "switch_ip": SW, "port": 5, "mac": "DEMO000000AA", "ip": IP, "_demo_shutdown": True})
        await db.switch_ports.insert_one({"client_id": CID, "local_ip": SW, "idx": 5, "name": "GigabitEthernet1/0/5", "oper": "up", "admin": "up", "speed_mbps": 1000, "updated_at": now.isoformat(), "_demo_shutdown": True})
        print("seeded")
    else:
        await db.device_poll_status.update_one({"client_id": CID, "device_ip": IP}, {"$set": {"reachable": True, "unreachable_since": None}, "$unset": {"_demo_shutdown": ""}})
        await db.discovered_endpoints.delete_many({"_demo_shutdown": True})
        await db.switch_ports.delete_many({"_demo_shutdown": True})
        await db.device_status_state.delete_many({"client_id": CID, "device_ip": IP})
        await db.device_status_events.delete_many({"client_id": CID, "device_ip": IP})
        print("restored")

asyncio.run(m(sys.argv[1]))
