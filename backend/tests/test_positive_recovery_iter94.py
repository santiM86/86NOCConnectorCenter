"""
Iteration 94 — Backend regression for POSITIVE-RECOVERY auto-resolution.

Verifies:
 1. NO active alert of any *_recovery source_type exists (broad rule).
 2. datto_sync_recovery: stale -> fresh transition on TEMP client resolves the
    original datto_sync_stale alert AND persists recovery record as 'resolved'.
 3. datto_server_recovery: server offline (with active alert + offline_state)
    becoming online again, resolves the original datto_server_offline alert
    AND persists any recovery record as 'resolved'.
 4. _emit_recovery_notice helper always writes status='resolved' (unit-level).
    Also covers device_recovery and connector_recovery shape (both go through
    resolved-only insertion path).
 5. Regression: legitimate active alerts (connector_watchdog + new_devices_detected)
    are NOT auto-closed by POST /api/alert-engine/run-now.
 6. Engine stability: /run-now returns ok:true, vital_only view has no recovery noise.
"""
import os
import uuid
import asyncio
import time
from datetime import datetime, timezone, timedelta

import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

ADMIN_EMAIL = "info@86bit.it"
ADMIN_PASSWORD = "Ariel17051986@!@86"

RECOVERY_TYPES = {
    "datto_sync_recovery",
    "device_recovery",
    "datto_server_recovery",
    "connector_recovery",
}


# ---------- fixtures --------------------------------------------------------
@pytest.fixture(scope="module")
def token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=20,
    )
    assert r.status_code == 200, r.text
    j = r.json()
    tok = j.get("access_token") or j.get("token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def loop():
    lp = asyncio.new_event_loop()
    yield lp
    lp.close()


@pytest.fixture(scope="module")
def db(loop):
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


def _fetch_active(headers):
    r = requests.get(
        f"{BASE_URL}/api/alerts",
        params={"status": "active"},
        headers=headers,
        timeout=30,
    )
    assert r.status_code == 200, r.text
    p = r.json()
    return p if isinstance(p, list) else p.get("items", p.get("alerts", []))


# ---------- 1. broad recovery rule -----------------------------------------
def test_no_active_recovery_of_any_type(headers):
    alerts = _fetch_active(headers)
    bad = [a for a in alerts if a.get("source_type") in RECOVERY_TYPES]
    assert bad == [], f"Recovery-typed alerts leaked as active: {bad}"


def test_no_active_source_ending_with_recovery(headers):
    alerts = _fetch_active(headers)
    bad = [a for a in alerts if str(a.get("source_type", "")).endswith("_recovery")]
    assert bad == [], f"Active *_recovery alerts: {bad}"


def test_vital_only_no_recovery_noise(headers):
    r = requests.get(
        f"{BASE_URL}/api/alerts",
        params={"status": "active", "vital_only": "true"},
        headers=headers,
        timeout=30,
    )
    assert r.status_code == 200
    p = r.json()
    alerts = p if isinstance(p, list) else p.get("items", p.get("alerts", []))
    bad = [a for a in alerts if str(a.get("source_type", "")).endswith("_recovery")]
    assert bad == []


# ---------- 2. datto_sync_recovery via run-now -----------------------------
def test_datto_sync_recovery_persists_resolved(loop, db, headers):
    cid = f"TEST_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    stale_alert_id = str(uuid.uuid4())

    async def setup():
        await db.clients.insert_one({"id": cid, "name": f"TEST_{cid[-6:]}",
                                     "created_at": now.isoformat()})
        await db.datto_client_links.insert_one({
            "client_id": cid,
            "last_sync_at": now.isoformat(),  # FRESH
            "created_at": now.isoformat(),
        })
        await db.alerts.insert_one({
            "id": stale_alert_id, "client_id": cid,
            "source_type": "datto_sync_stale", "severity": "high",
            "status": "active", "title": "DATTO RMM: sync fermo (TEST)",
            "message": "test", "device_name": "Datto RMM Sync",
            "created_at": now.isoformat(),
        })

    async def cleanup():
        await db.clients.delete_many({"id": cid})
        await db.datto_client_links.delete_many({"client_id": cid})
        await db.alerts.delete_many({"client_id": cid})

    try:
        loop.run_until_complete(setup())
        r = requests.post(f"{BASE_URL}/api/alert-engine/run-now",
                          headers=headers, timeout=120)
        assert r.status_code in (200, 202), r.text
        assert r.json().get("ok") is True
        time.sleep(2)

        stale = loop.run_until_complete(db.alerts.find_one({"id": stale_alert_id}))
        assert stale and stale.get("status") == "resolved"
        assert stale.get("resolved_at")

        recs = loop.run_until_complete(
            db.alerts.find({"client_id": cid,
                            "source_type": "datto_sync_recovery"}).to_list(50))
        for rec in recs:
            assert rec.get("status") == "resolved", rec
        assert not [r for r in recs if r.get("status") == "active"]
    finally:
        loop.run_until_complete(cleanup())


# ---------- 3. datto_server_recovery via run-now ---------------------------
def test_datto_server_recovery_persists_resolved(loop, db, headers):
    cid = f"TEST_{uuid.uuid4().hex[:12]}"
    uid = f"TEST_uid_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    server_alert_id = str(uuid.uuid4())

    async def setup():
        await db.clients.insert_one({"id": cid, "name": f"TEST_srv_{cid[-6:]}",
                                     "created_at": now.isoformat()})
        # server is ONLINE now
        await db.datto_devices.insert_one({
            "client_id": cid, "uid": uid, "name": "TEST_SRV",
            "ip": "10.253.253.1", "ip_list": [],
            "online": True, "is_server": True,
            "device_type": "Server",
            "datto_last_seen": now.isoformat(),
        })
        # previous offline_state at level=1 with alert_id
        await db.datto_offline_state.insert_one({
            "client_id": cid, "uid": uid, "name": "TEST_SRV",
            "first_offline_at": (now - timedelta(hours=3)).isoformat(),
            "level": 1, "alert_id": server_alert_id,
        })
        await db.alerts.insert_one({
            "id": server_alert_id, "client_id": cid,
            "source_type": "datto_server_offline", "severity": "high",
            "status": "active", "title": "SERVER DATTO OFFLINE: TEST_SRV",
            "message": "test", "device_name": "TEST_SRV",
            "created_at": (now - timedelta(hours=3)).isoformat(),
        })

    async def cleanup():
        await db.clients.delete_many({"id": cid})
        await db.datto_devices.delete_many({"client_id": cid})
        await db.datto_offline_state.delete_many({"client_id": cid})
        await db.alerts.delete_many({"client_id": cid})

    try:
        loop.run_until_complete(setup())
        r = requests.post(f"{BASE_URL}/api/alert-engine/run-now",
                          headers=headers, timeout=120)
        assert r.status_code in (200, 202), r.text
        time.sleep(2)

        orig = loop.run_until_complete(db.alerts.find_one({"id": server_alert_id}))
        assert orig and orig.get("status") == "resolved", \
            f"server_offline alert not resolved: {orig}"
        assert orig.get("resolved_at")

        recs = loop.run_until_complete(
            db.alerts.find({"client_id": cid,
                            "source_type": "datto_server_recovery"}).to_list(50))
        # if auto_recovery enabled, a recovery record must exist AND be resolved
        for rec in recs:
            assert rec.get("status") == "resolved", rec
        assert not [r for r in recs if r.get("status") == "active"]

        # datto_offline_state must be cleaned up
        st = loop.run_until_complete(
            db.datto_offline_state.find_one({"client_id": cid, "uid": uid}))
        assert st is None
    finally:
        loop.run_until_complete(cleanup())


# ---------- 4. _emit_recovery_notice unit + connector_recovery shape --------
def test_emit_recovery_notice_writes_resolved(loop, db):
    """Directly call the helper to prove any recovery source_type is inserted
    as 'resolved' (covers device_recovery / connector_recovery pattern)."""
    import sys
    sys.path.insert(0, "/app/backend")
    from alert_engine import _emit_recovery_notice, _mk_alert

    cid = f"TEST_{uuid.uuid4().hex[:12]}"

    async def run():
        cfg = {"auto_recovery": True, "channels": []}
        for src in ("device_recovery", "datto_server_recovery",
                    "datto_sync_recovery"):
            rec = _mk_alert(cid, "TEST_cn", "TEST_dev", "10.253.253.2",
                            "server", "low", src,
                            f"TEST {src}", "test message")
            await _emit_recovery_notice(db, cfg, rec)
        docs = await db.alerts.find({"client_id": cid}).to_list(20)
        return docs

    async def cleanup():
        await db.alerts.delete_many({"client_id": cid})

    try:
        docs = loop.run_until_complete(run())
        assert len(docs) == 3
        for d in docs:
            assert d.get("status") == "resolved", d
            assert d.get("resolved_at")
    finally:
        loop.run_until_complete(cleanup())


def test_connector_recovery_insertion_pattern_is_resolved():
    """Static-source check: connector_watchdog inserts connector_recovery
    with status='resolved' explicitly (never active)."""
    src = open("/app/backend/connector_watchdog.py", encoding="utf-8").read()
    idx = src.find('"source_type": "connector_recovery"')
    assert idx > 0, "connector_recovery insertion block not found"
    # inspect the surrounding insert_one block
    block = src[idx - 400: idx + 400]
    assert '"status": "resolved"' in block, \
        "connector_recovery block must set status='resolved' explicitly"
    assert '"status": "active"' not in block, \
        "connector_recovery block must NOT set status='active'"


# ---------- 5. Regression: legitimate active alerts NOT closed --------------
def test_run_now_does_not_close_legitimate_active_alerts(headers):
    before = _fetch_active(headers)
    before_ids = {a.get("id"): a for a in before if a.get("source_type") in (
        "connector_watchdog", "new_devices_detected")}

    r = requests.post(f"{BASE_URL}/api/alert-engine/run-now",
                      headers=headers, timeout=120)
    assert r.status_code in (200, 202), r.text
    body = r.json()
    assert body.get("ok") is True
    time.sleep(2)

    after = _fetch_active(headers)
    after_ids = {a.get("id") for a in after}
    for aid, a in before_ids.items():
        assert aid in after_ids, \
            f"Legitimate active alert auto-closed: {a.get('source_type')} / {a.get('title')}"

    # And no *_recovery leaked to active after run-now
    leaked = [a for a in after if str(a.get("source_type", "")).endswith("_recovery")]
    assert leaked == [], f"Recovery leaked as active after run-now: {leaked}"
