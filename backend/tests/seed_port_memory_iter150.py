"""Seed memoria porte realistica per lo switch 10.10.41.220 (client da3d…) → test AI porte.
Uso: cd /app/backend && python tests/seed_port_memory_iter150.py
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
NOW = datetime.now(timezone.utc)


def hist(up_fn, per=10):
    how_up, how_total = {}, {}
    for d in range(7):
        for h in range(24):
            k = str(d * 24 + h)
            how_total[k] = per
            how_up[k] = per if up_fn(d, h) else 0
    return how_up, how_total


def doc(idx, name, up_fn, days=40, poe=0.0, speed=1000, last_up=True, last_dev=None):
    hu, ht = hist(up_fn)
    ups = sum(hu.values())
    d = {"client_id": CID, "local_ip": SW, "idx": idx, "name": name, "first_seen": (NOW - timedelta(days=days)).isoformat(),
         "samples": 1680, "up_samples": ups, "how_up": hu, "how_total": ht, "usual_speed_mbps": speed,
         "poe_samples": ups if poe else 0, "poe_w_sum": ups * poe if poe else 0,
         "last_up_at": (NOW - timedelta(minutes=5 if last_up else 300)).isoformat(),
         "last_down_at": (NOW - timedelta(minutes=300 if last_up else 5)).isoformat(),
         "last_oper_up": last_up, "last_poe_w": poe if last_up else 0.0, "last_speed_mbps": speed if last_up else 0,
         "updated_at": NOW.isoformat()}
    if last_dev:
        d["last_device"] = {**last_dev, "seen_at": (NOW - timedelta(hours=3)).isoformat()}
    return d


async def main():
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    await db.port_memory.delete_many({"client_id": CID, "local_ip": SW})
    office = lambda d, h: d < 5 and 8 <= h < 18  # noqa: E731
    docs = [
        doc(1, "GigabitEthernet1/0/1", lambda d, h: True, poe=0, last_dev={"mac": "AA:BB:CC:00:00:01", "ip": "10.10.41.10", "name": "SRV-DC01"}),
        doc(2, "GigabitEthernet1/0/2", lambda d, h: True, last_up=False, last_dev={"mac": "AA:BB:CC:00:00:02", "ip": "10.10.41.11", "name": "NAS-BACKUP"}),  # always_on ora giù → anomalo
        doc(3, "GigabitEthernet1/0/3", office, last_up=False, last_dev={"mac": "AA:BB:CC:00:00:03", "ip": "10.10.41.50", "name": "PC-MARIO"}),  # scheduled
        doc(4, "GigabitEthernet1/0/4", office, last_up=False, speed=100, last_dev={"mac": "AA:BB:CC:00:00:04", "ip": "10.10.41.51", "name": "PC-LUCIA"}),
        doc(5, "GigabitEthernet1/0/5", lambda d, h: d < 5 and 22 <= h < 24, last_up=False, last_dev={"mac": "AA:BB:CC:00:00:05", "ip": "", "name": ""}),  # notturno sospetto
        doc(6, "GigabitEthernet1/0/6", lambda d, h: True, poe=6.2, last_dev={"mac": "AA:BB:CC:00:00:06", "ip": "10.10.41.200", "name": "AP-SALA"}),
        doc(7, "GigabitEthernet1/0/7", lambda d, h: (d * 24 + h) % 11 == 0, last_up=False),  # sporadic
        doc(8, "GigabitEthernet1/0/8", lambda d, h: False, last_up=False, days=45),  # unused
        doc(9, "GigabitEthernet1/0/9", lambda d, h: False, last_up=False, days=60),  # unused
        doc(10, "GigabitEthernet1/0/10", office, days=3, last_up=False),  # learning
    ]
    await db.port_memory.insert_many(docs)
    # flap 7gg sulla porta 4 (cavo instabile)
    await db.port_flap_events.delete_many({"client_id": CID, "local_ip": SW, "idx": 4})
    await db.port_flap_events.insert_many([
        {"client_id": CID, "local_ip": SW, "idx": 4, "port_name": "GigabitEthernet1/0/4", "kind": "oper_change",
         "from": 1 if i % 2 else 2, "to": 2 if i % 2 else 1, "ts": (NOW - timedelta(hours=3 * i + 1)).isoformat()} for i in range(14)])
    print("seeded", len(docs), "porte su", SW)


asyncio.run(main())
