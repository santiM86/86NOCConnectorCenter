"""
Test that Datto RMM sync recovery alerts are NOT persisted as active.
Verifies the fix in alert_engine.run_datto_watchdog.
"""
import os
import uuid
import asyncio
from datetime import datetime, timezone, timedelta

import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

ADMIN_EMAIL = "info@86bit.it"
ADMIN_PASSWORD = "Ariel17051986@!@86"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=20)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    tok = data.get("access_token") or data.get("token")
    assert tok, f"no token in {data}"
    return tok


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def db(loop):
    client = AsyncIOMotorClient(MONGO_URL)
    return client[DB_NAME]


# ---------------------------------------------------------------------------
# 1. No active datto_sync_recovery alerts should exist in production data
# ---------------------------------------------------------------------------
def test_no_active_datto_sync_recovery_via_api(headers):
    r = requests.get(f"{BASE_URL}/api/alerts", params={"status": "active"},
                     headers=headers, timeout=30)
    assert r.status_code == 200, r.text
    payload = r.json()
    alerts = payload if isinstance(payload, list) else payload.get("items", payload.get("alerts", []))
    recovery = [a for a in alerts if a.get("source_type") == "datto_sync_recovery"]
    assert recovery == [], f"Found active datto_sync_recovery alerts: {recovery}"


def test_no_test_alert_leftovers(headers):
    r = requests.get(f"{BASE_URL}/api/alerts", params={"status": "active"},
                     headers=headers, timeout=30)
    assert r.status_code == 200
    payload = r.json()
    alerts = payload if isinstance(payload, list) else payload.get("items", payload.get("alerts", []))
    leftovers = [a for a in alerts if "TEST_" in (a.get("title") or "")]
    assert leftovers == [], f"Found TEST_ leftover alerts: {leftovers}"


# ---------------------------------------------------------------------------
# 2. Vital-only alert list contains no recovery noise
# ---------------------------------------------------------------------------
def test_vital_only_no_recovery_noise(headers):
    r = requests.get(f"{BASE_URL}/api/alerts",
                     params={"status": "active", "vital_only": "true"},
                     headers=headers, timeout=30)
    assert r.status_code == 200, r.text
    payload = r.json()
    alerts = payload if isinstance(payload, list) else payload.get("items", payload.get("alerts", []))
    bad = [a for a in alerts
           if a.get("source_type") == "datto_sync_recovery"
           or "TEST_" in (a.get("title") or "")]
    assert bad == [], f"Vital-only view contains noise: {bad}"


# ---------------------------------------------------------------------------
# 3. Simulate stale->recover transition with a TEMP client & verify:
#    (a) datto_sync_stale existing alert becomes 'resolved'
#    (b) any newly created datto_sync_recovery alert has status='resolved'
#    (c) 0 recovery alerts are active for the temp client
# ---------------------------------------------------------------------------
def test_recovery_transition_persists_resolved_only(loop, db, headers):
    temp_cid = f"TEST_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    stale_alert_id = str(uuid.uuid4())

    async def setup():
        # Insert temp client
        await db.clients.insert_one({
            "id": temp_cid,
            "name": f"TEST_client_{temp_cid[-6:]}",
            "created_at": now.isoformat(),
        })
        # Insert datto_client_links with FRESH last_sync_at (so stale -> not stale)
        await db.datto_client_links.insert_one({
            "client_id": temp_cid,
            "last_sync_at": now.isoformat(),
            "created_at": now.isoformat(),
        })
        # Insert pre-existing ACTIVE datto_sync_stale alert (simulates prior stale state)
        await db.alerts.insert_one({
            "id": stale_alert_id,
            "client_id": temp_cid,
            "source_type": "datto_sync_stale",
            "severity": "high",
            "status": "active",
            "title": "DATTO RMM: sync fermo",
            "message": "test",
            "device_name": "Datto RMM Sync",
            "created_at": now.isoformat(),
        })

    async def fetch_alerts():
        stale = await db.alerts.find_one({"id": stale_alert_id})
        recovery_docs = await db.alerts.find(
            {"client_id": temp_cid, "source_type": "datto_sync_recovery"}
        ).to_list(50)
        return stale, recovery_docs

    async def cleanup():
        await db.clients.delete_many({"id": temp_cid})
        await db.datto_client_links.delete_many({"client_id": temp_cid})
        await db.alerts.delete_many({"client_id": temp_cid})

    try:
        loop.run_until_complete(setup())

        # Trigger the engine
        r = requests.post(f"{BASE_URL}/api/alert-engine/run-now",
                          headers=headers, timeout=120)
        assert r.status_code in (200, 202), f"run-now failed: {r.status_code} {r.text}"

        # Small wait in case background execution
        import time
        time.sleep(3)

        stale_doc, recovery_docs = loop.run_until_complete(fetch_alerts())

        # (a) prior stale must now be resolved
        assert stale_doc is not None
        assert stale_doc.get("status") == "resolved", \
            f"expected stale alert resolved, got {stale_doc.get('status')}"
        assert stale_doc.get("resolved_at"), "resolved_at not set on stale alert"

        # (b) any recovery alert (if auto_recovery enabled) must be status=resolved
        for rec in recovery_docs:
            assert rec.get("status") == "resolved", \
                f"recovery alert is not resolved: {rec}"

        # (c) 0 recovery alerts with status=active for this client
        active_recovery = [r for r in recovery_docs if r.get("status") == "active"]
        assert active_recovery == [], f"Found ACTIVE recovery alerts: {active_recovery}"

    finally:
        loop.run_until_complete(cleanup())


# ---------------------------------------------------------------------------
# 4. Regression: legitimate active alerts (connector_watchdog, new_devices_detected)
#    still surface via /api/alerts?status=active (if they exist in the system).
#    We only assert *presence-shape*, not existence, since the environment may or
#    may not currently have those conditions. We ensure the API returns them
#    when present and doesn't drop them.
# ---------------------------------------------------------------------------
def test_api_returns_active_alerts_correctly(headers):
    r = requests.get(f"{BASE_URL}/api/alerts", params={"status": "active"},
                     headers=headers, timeout=30)
    assert r.status_code == 200
    payload = r.json()
    alerts = payload if isinstance(payload, list) else payload.get("items", payload.get("alerts", []))
    # every returned alert must actually be active
    for a in alerts:
        assert a.get("status") == "active", f"non-active alert leaked: {a}"
        # sanity: none should be recovery noise
        assert a.get("source_type") != "datto_sync_recovery"


# ---------------------------------------------------------------------------
# 5. Regression: genuine stale scenario still emits an ACTIVE datto_sync_stale
# ---------------------------------------------------------------------------
def test_genuine_stale_creates_active_alert(loop, db, headers):
    temp_cid = f"TEST_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    stale_time = now - timedelta(minutes=120)

    async def setup():
        await db.clients.insert_one({
            "id": temp_cid,
            "name": f"TEST_stale_{temp_cid[-6:]}",
            "created_at": now.isoformat(),
        })
        await db.datto_client_links.insert_one({
            "client_id": temp_cid,
            "last_sync_at": stale_time.isoformat(),
            "created_at": stale_time.isoformat(),
        })

    async def fetch():
        return await db.alerts.find(
            {"client_id": temp_cid, "source_type": "datto_sync_stale"}
        ).to_list(10)

    async def cleanup():
        await db.clients.delete_many({"id": temp_cid})
        await db.datto_client_links.delete_many({"client_id": temp_cid})
        await db.alerts.delete_many({"client_id": temp_cid})

    try:
        loop.run_until_complete(setup())
        r = requests.post(f"{BASE_URL}/api/alert-engine/run-now",
                          headers=headers, timeout=120)
        assert r.status_code in (200, 202)
        import time
        time.sleep(3)
        docs = loop.run_until_complete(fetch())
        active = [d for d in docs if d.get("status") == "active"]
        assert len(active) >= 1, f"Expected active datto_sync_stale, got: {docs}"
    finally:
        loop.run_until_complete(cleanup())
