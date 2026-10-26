"""Seed shared-MAC devices for iter160 UI test on client da3d6e40-b3e5-4d46-9787-dde328a3aa36.
Usage: python seed_or_cleanup.py seed | python seed_or_cleanup.py clean
"""
import asyncio
import os
import sys

sys.path.insert(0, "/app/backend")
from database import db  # noqa

CID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"
MAC = "00:15:5d:ff:ee:01"
IPS = ["10.231.0.11", "10.231.0.12", "10.231.0.13"]
NAMES = ["TEST_SRV-VM1", "TEST_HOSTSRV", "TEST_SRV-VM2"]


async def seed():
    docs_md = []
    for ip, name in zip(IPS, NAMES):
        docs_md.append({
            "id": f"iter160-{ip}", "client_id": CID, "ip": ip, "ip_address": ip, "mac": MAC, "name": name,
            "virtualization": ("physical" if "HOST" in name else "hyperv"), "status": "online",
        })
    # mac_history on the host
    docs_md[1]["mac"] = MAC
    docs_md[1]["mac_previous"] = "00:15:5d:ff:ee:00"
    docs_md[1]["mac_history"] = [
        {"mac": "00:15:5d:ff:ee:00", "at": "2025-11-01T10:00:00+00:00"},
        {"mac": MAC, "at": "2026-01-05T12:34:56+00:00"},
    ]
    await db.managed_devices.insert_many(docs_md)
    # devices collection entries (so /api/devices returns them)
    for ip, name in zip(IPS, NAMES):
        await db.devices.insert_one({
            "id": f"iter160-dev-{ip}", "client_id": CID, "ip_address": ip, "name": name,
            "device_type": "server", "mac_address": MAC, "status": "online",
        })
    print("seeded 3 managed_devices + 3 devices with shared MAC", MAC)


async def clean():
    r1 = await db.managed_devices.delete_many({"id": {"$regex": "^iter160-"}})
    r2 = await db.devices.delete_many({"id": {"$regex": "^iter160-"}})
    r3 = await db.nic_hosts.delete_many({"client_id": CID, "mac": MAC})
    r4 = await db.alert_metric_rules.delete_many({"name": {"$regex": "^TEST_iter160"}})
    r5 = await db.alert_dependencies.delete_many({"client_id": CID, "parent_ip": {"$regex": "^10\\.250\\.250\\."}})
    print(f"cleaned md={r1.deleted_count} dev={r2.deleted_count} nic_hosts={r3.deleted_count} rules={r4.deleted_count} deps={r5.deleted_count}")


action = sys.argv[1] if len(sys.argv) > 1 else "seed"
asyncio.run(seed() if action == "seed" else clean())
