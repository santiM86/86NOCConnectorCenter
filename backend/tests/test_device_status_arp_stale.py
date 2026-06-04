"""Regression test bug "pallino verde su device offline da settimane".

Caso utente: TP-Link 192.168.16.9 mostrato OFFLINE da 06/05 nella card
ma con pallino VERDE nella lista. Causa: l'evidenza L2 (ARP cache stale)
sovrascriveva il ping fresco che diceva reachable=False.
"""
import os
import sys
import asyncio
import pathlib
from datetime import datetime, timezone, timedelta

ENV_PATH = pathlib.Path(__file__).resolve().parents[1] / ".env"
if ENV_PATH.exists():
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
from database import db  # noqa: E402

API_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001")
TEST_IP = "10.99.99.99"
TEST_MAC = "aa:bb:cc:dd:ee:99"


async def _login():
    async with httpx.AsyncClient(timeout=20) as ac:
        r = await ac.post(f"{API_URL}/api/auth/login",
                          json={"email": "info@86bit.it",
                                "password": "Ariel17051986@!@86"})
        return r.json()["token"]


async def _setup(client_id: str, scenario: str):
    """Inietta managed_device + device_poll_status + discovered_endpoint."""
    now = datetime.now(timezone.utc)
    await db.managed_devices.update_one(
        {"client_id": client_id, "ip": TEST_IP},
        {"$set": {"client_id": client_id, "ip": TEST_IP,
                  "mac": TEST_MAC, "name": "PYTEST_DEVICE"}},
        upsert=True,
    )
    if scenario == "offline_with_arp_stale":
        # Ping fresco dice OFFLINE ma ARP cache stale (legittimo, router cache)
        await db.device_poll_status.update_one(
            {"client_id": client_id, "device_ip": TEST_IP},
            {"$set": {"client_id": client_id, "device_ip": TEST_IP,
                      "ping_reachable": False, "reachable": False,
                      "last_poll_at": now.isoformat(), "source": "agent_v4"}},
            upsert=True,
        )
        # discovered_endpoint mostra IP via "scanner_lan" (ARP)
        await db.discovered_endpoints.update_one(
            {"client_id": client_id, "ip": TEST_IP},
            {"$set": {"client_id": client_id, "ip": TEST_IP, "mac": TEST_MAC,
                      "last_seen_at": now.isoformat(),
                      "source_connector_mode": "scanner",
                      "last_seen_via": "arp"}},
            upsert=True,
        )
    elif scenario == "offline_with_fdb_evidence":
        # Ping fresco dice OFFLINE ma FDB switch (mac_table) lo vede →
        # questo è caso legittimo: device blocca ICMP ma è L2-live
        await db.device_poll_status.update_one(
            {"client_id": client_id, "device_ip": TEST_IP},
            {"$set": {"client_id": client_id, "device_ip": TEST_IP,
                      "ping_reachable": False, "reachable": False,
                      "last_poll_at": now.isoformat(), "source": "agent_v4"}},
            upsert=True,
        )
        await db.discovered_endpoints.update_one(
            {"client_id": client_id, "ip": TEST_IP},
            {"$set": {"client_id": client_id, "ip": TEST_IP, "mac": TEST_MAC,
                      "last_seen_at": now.isoformat(),
                      "source_connector_mode": "snmp",
                      "last_seen_via": "snmp",
                      "switch_ip": "10.10.1.1"}},
            upsert=True,
        )


async def _cleanup(client_id: str):
    await db.managed_devices.delete_one({"client_id": client_id, "ip": TEST_IP})
    await db.device_poll_status.delete_one({"client_id": client_id, "device_ip": TEST_IP})
    await db.discovered_endpoints.delete_one({"client_id": client_id, "ip": TEST_IP})


async def _fetch_status(token: str, client_id: str) -> str | None:
    async with httpx.AsyncClient(timeout=20) as ac:
        r = await ac.get(f"{API_URL}/api/clients/{client_id}/devices",
                         headers={"Authorization": f"Bearer {token}"})
        if r.status_code != 200:
            return None
        for d in r.json():
            if d.get("ip_address") == TEST_IP:
                return d.get("status")
    return None


async def main():
    token = await _login()
    c = await db.clients.find_one({}, {"_id": 0, "id": 1})
    cid = c["id"]

    # Scenario 1: ping OFFLINE + ARP cache stale → DEVE essere offline/pending
    try:
        await _setup(cid, "offline_with_arp_stale")
        await asyncio.sleep(0.5)
        status = await _fetch_status(token, cid)
        assert status in ("offline", "pending"), \
            f"BUG: device offline con sola ARP cache stale dovrebbe NON essere online, got '{status}'"
        print(f"✅ Scenario 1 (ARP stale + ping offline) → status='{status}' OK")
    finally:
        await _cleanup(cid)

    # Scenario 2: ping OFFLINE + FDB switch fresh → DEVE essere online (device blocca ICMP)
    try:
        await _setup(cid, "offline_with_fdb_evidence")
        await asyncio.sleep(0.5)
        status = await _fetch_status(token, cid)
        assert status == "online", \
            f"FDB switch (single source of truth L2) deve mantenere online anche se ping fail, got '{status}'"
        print(f"✅ Scenario 2 (FDB switch + ping offline) → status='{status}' OK")
    finally:
        await _cleanup(cid)

    print("\n✅ Tutti i test di regressione passati")


if __name__ == "__main__":
    asyncio.run(main())
