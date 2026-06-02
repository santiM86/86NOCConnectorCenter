"""
Test regressione bug: /api/overview/clients mostrava connector_online=False
quando il client aveva SOLO il nuovo Go Agent v4 (managed_agents heartbeat)
senza il legacy PowerShell connector (connector_status.last_seen).

Riferimento bug: utente segnalava 86BITOffice/Galvan/Zitac con badge CONN.
"OFF" rosso anche quando l'agent v4 era attivo e dati SNMP freschi.

Fix in backend/routes/overview.py (v2026-02-feb): aggiunge lettura di
db.managed_agents e marca connector_online=True se ALMENO un agent v4
ha heartbeat fresco (<5 min).
"""
import os
import sys
import asyncio
from datetime import datetime, timezone, timedelta

# Carica .env per MONGO_URL/DB_NAME
import pathlib
ENV_PATH = pathlib.Path(__file__).resolve().parents[1] / ".env"
if ENV_PATH.exists():
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        # Strip surrounding quotes if present
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k.strip(), v)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
from database import db  # noqa: E402

API_URL = os.environ.get("REACT_APP_BACKEND_URL") or "http://localhost:8001"
if "preview.emergentagent.com" not in API_URL and not API_URL.startswith("http"):
    API_URL = "http://localhost:8001"

TEST_HOSTNAME = "PYTEST_LIVE_AGENT_V4_FIX"


async def _login() -> str:
    async with httpx.AsyncClient(timeout=20) as ac:
        r = await ac.post(f"{API_URL}/api/auth/login",
                          json={"email": "info@86bit.it",
                                "password": "Ariel17051986@!@86"})
        r.raise_for_status()
        return r.json()["token"]


async def _get_client_id() -> str:
    c = await db.clients.find_one({}, {"_id": 0, "id": 1})
    assert c, "Nessun client in DB per il test"
    return c["id"]


async def _fetch_overview(token: str, client_id: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as ac:
        r = await ac.get(f"{API_URL}/api/overview/clients",
                         headers={"Authorization": f"Bearer {token}"})
        r.raise_for_status()
        for entry in r.json().get("clients", []):
            if entry["id"] == client_id:
                return entry
    raise AssertionError(f"Client {client_id} non trovato in overview")


async def test_connector_online_fresh_v4_agent():
    """Quando managed_agents ha heartbeat fresco -> connector_online=True."""
    token = await _login()
    cid = await _get_client_id()

    now = datetime.now(timezone.utc)
    await db.managed_agents.update_one(
        {"client_id": cid, "hostname": TEST_HOSTNAME},
        {"$set": {
            "client_id": cid,
            "hostname": TEST_HOSTNAME,
            "agent_id": "pytest-v4-fresh",
            "last_heartbeat_at": now.isoformat(),
            "last_seen_at": now.isoformat(),
            "connected": True,
        }},
        upsert=True
    )
    try:
        entry = await _fetch_overview(token, cid)
        assert entry["connector_online"] is True, \
            f"Atteso connector_online=True con HB fresco, got {entry['connector_online']}"
        print("✅ FRESH v4 heartbeat -> connector_online=True")
    finally:
        await db.managed_agents.delete_one({"hostname": TEST_HOSTNAME})


async def test_connector_online_stale_v4_agent():
    """Quando managed_agents ha heartbeat vecchio (>5min) -> non promuove True."""
    token = await _login()
    cid = await _get_client_id()

    stale = datetime.now(timezone.utc) - timedelta(minutes=30)
    await db.managed_agents.update_one(
        {"client_id": cid, "hostname": TEST_HOSTNAME + "_STALE"},
        {"$set": {
            "client_id": cid,
            "hostname": TEST_HOSTNAME + "_STALE",
            "agent_id": "pytest-v4-stale",
            "last_heartbeat_at": stale.isoformat(),
            "last_seen_at": stale.isoformat(),
            "connected": False,
        }},
        upsert=True
    )
    # Anche connector_status del cliente è stale in preview, quindi atteso False
    try:
        entry = await _fetch_overview(token, cid)
        # Non deve diventare True solo grazie all'agent stale
        assert entry["connector_online"] is not True or \
            await db.connector_status.find_one(
                {"client_id": cid, "last_seen": {"$gte": (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()}}
            ) is not None, \
            "Stale v4 agent NON deve promuovere connector_online a True"
        print("✅ STALE v4 heartbeat -> connector_online correctly NOT True")
    finally:
        await db.managed_agents.delete_one({"hostname": TEST_HOSTNAME + "_STALE"})


async def main():
    await test_connector_online_fresh_v4_agent()
    await test_connector_online_stale_v4_agent()
    print("\n✅ Tutti i test di regressione passati")


if __name__ == "__main__":
    asyncio.run(main())
