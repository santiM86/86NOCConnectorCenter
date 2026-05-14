"""Regression: update-check deve discriminare per hostname+mode.

Bug 2026-05-07 (segnalato dall'utente con screenshot Connector Scanner SRVDCGAL
v3.8.13 ONLINE):
  L'utente cliccava "Aggiorna" sullo scanner. Il connector eseguiva tutto il
  processo di auto-update fino in fondo MA non aggiornava nulla.

Root cause:
  In `routes/connector.py::connector_update_check` la query era
    db.connector_status.find_one({"client_id": client_data["id"]})
  che ritornava IL PRIMO connector del cliente, indipendentemente da
  master/scanner. Se il master era gia' alla version target ma lo scanner no,
  il backend rispondeva con la version del master come "current_version" e
  decideva update_available=false. Lo scanner allora chiamava il task scheduler
  ArgusConnectorUpdater, il cui update_check.ps1 chiamava /update-check, vedeva
  update_available=false ed usciva con success — l'utente percepiva "fa tutto
  il processo ma non aggiorna nulla".

Fix v3.8.26:
  - Backend update-check legge query string ?hostname=X&mode=Y. Se forniti,
    cerca QUEL doc specifico.
  - Senza query string (connector legacy v3.7-v3.8.13), prende la MIN version
    tra tutti i connector del cliente (cosi' anche solo uno indietro -> update).
  - Risposta include current_version_seen_by_center per debug.
  - update_check.ps1 passa hostname+mode come query string.
"""
import os
import asyncio
import pytest
import requests
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient


BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://device-poller-ws.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"
CONNECTOR_API_KEY = "noc_35cf39b4d68740b1a981aedef2ee293d"
CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"


@pytest.fixture
def setup_mixed_versions():
    """Crea uno scenario realistico: master alla version ATTIVA (gia' aggiornato)
    + scanner v3.8.13 (indietro). Ripristina il DB nello stato precedente al test."""
    mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("DB_NAME", "test_database")

    test_master = "REGTEST-MASTER-UC"
    test_scanner = "REGTEST-SCANNER-UC"

    async def _setup():
        client = AsyncIOMotorClient(mongo_url)
        try:
            # Read currently active version from DB so we don't hardcode
            active = await client[db_name].connector_updates.find_one(
                {"active": True}, {"_id": 0, "version": 1}
            )
            assert active and active.get("version"), "Nessun connector_update attivo in DB"
            target_version = active["version"]
            now = datetime.now(timezone.utc).isoformat()
            await client[db_name].connector_status.update_one(
                {"client_id": CLIENT_ID, "hostname": test_master, "mode": "master"},
                {"$set": {"connector_version": target_version, "last_seen": now, "last_heartbeat": now}},
                upsert=True,
            )
            await client[db_name].connector_status.update_one(
                {"client_id": CLIENT_ID, "hostname": test_scanner, "mode": "scanner"},
                {"$set": {"connector_version": "3.8.13", "last_seen": now, "last_heartbeat": now}},
                upsert=True,
            )
            return target_version
        finally:
            client.close()

    async def _cleanup():
        client = AsyncIOMotorClient(mongo_url)
        try:
            await client[db_name].connector_status.delete_many(
                {"hostname": {"$in": [test_master, test_scanner]}}
            )
        finally:
            client.close()

    target = asyncio.run(_setup())
    yield {"master": test_master, "scanner": test_scanner, "target_version": target}
    asyncio.run(_cleanup())


def test_update_check_with_hostname_and_mode_returns_specific_version(setup_mixed_versions):
    """Lo scanner indietro DEVE vedere update_available=true anche se il master
    e' gia' alla version target."""
    h = setup_mixed_versions
    target = h["target_version"]
    # Master gia' aggiornato -> update_available=false
    r_master = requests.get(
        f"{API}/connector/update-check",
        params={"hostname": h["master"], "mode": "master"},
        headers={"X-API-Key": CONNECTOR_API_KEY},
        timeout=10,
    )
    assert r_master.status_code == 200
    data_master = r_master.json()
    assert data_master.get("current_version_seen_by_center") == target
    assert data_master.get("update_available") is False, \
        f"Master a v{target} non dovrebbe avere update, invece {data_master}"

    # Scanner indietro -> update_available=true
    r_scanner = requests.get(
        f"{API}/connector/update-check",
        params={"hostname": h["scanner"], "mode": "scanner"},
        headers={"X-API-Key": CONNECTOR_API_KEY},
        timeout=10,
    )
    assert r_scanner.status_code == 200
    data_scanner = r_scanner.json()
    assert data_scanner.get("current_version_seen_by_center") == "3.8.13", \
        f"Backend doveva leggere v3.8.13 dello scanner, invece vede {data_scanner.get('current_version_seen_by_center')}"
    assert data_scanner.get("update_available") is True, \
        f"Scanner a v3.8.13 deve ricevere update_available=true, invece {data_scanner}"


def test_update_check_legacy_no_query_uses_min_version(setup_mixed_versions):
    """Connector legacy (pre-v3.8.26) chiama /update-check SENZA query string.
    Il backend deve prendere la MIN version tra tutti i connector del cliente,
    cosi' un connector indietro forza l'update anche su tutti gli altri."""
    r = requests.get(
        f"{API}/connector/update-check",
        headers={"X-API-Key": CONNECTOR_API_KEY},
        timeout=10,
    )
    assert r.status_code == 200
    data = r.json()
    # Con almeno 1 connector a v3.8.13, MIN deve essere <= 3.8.13
    seen = data.get("current_version_seen_by_center", "")
    assert seen and seen != "3.8.25", \
        f"Legacy DEVE vedere MIN version, non quella del master. visto: {seen}"
    assert data.get("update_available") is True, \
        f"Update deve essere disponibile (almeno 1 connector indietro): {data}"


def test_update_check_unknown_hostname_falls_back_to_min(setup_mixed_versions):
    """Hostname inesistente -> fallback a MIN version (compat retro)."""
    r = requests.get(
        f"{API}/connector/update-check",
        params={"hostname": "DOES-NOT-EXIST-XYZ", "mode": "master"},
        headers={"X-API-Key": CONNECTOR_API_KEY},
        timeout=10,
    )
    assert r.status_code == 200
    data = r.json()
    # Con hostname inesistente nel filtro, fallback a MIN tra TUTTI
    assert data.get("update_available") is True


def test_update_check_response_shape_unchanged():
    """La response shape deve essere stabile per non rompere connector vecchi."""
    r = requests.get(
        f"{API}/connector/update-check",
        headers={"X-API-Key": CONNECTOR_API_KEY},
        timeout=10,
    )
    assert r.status_code == 200
    data = r.json()
    # Campi obbligatori richiesti dal connector v3.6.x+
    REQUIRED = ["update_available", "latest_version", "filename", "download_url",
                "file_size", "sha256", "current_version_seen_by_center"]
    for k in REQUIRED:
        assert k in data, f"Manca campo richiesto '{k}' in update-check response"
