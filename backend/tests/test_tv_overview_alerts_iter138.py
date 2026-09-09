"""Iter 138 — Focus review request:
- TV dashboard: cache + no auth + alert_feed dedup + only active alerts
- Overview clients: cache + auth
- /api/alerts?sort_by=severity ordering
- alert_hygiene.resolve_recovered_device_alerts logic
"""
import os
import time
import asyncio
import uuid
from datetime import datetime, timezone, timedelta
import pytest
import pyotp
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"

ADMIN_EMAIL = "info@86bit.it"
ADMIN_PASS = "Ariel17051986@!@86"
TOTP_SECRET = "NMHDJNO53WLTOSREUXWERE6FDH5TAKC3"


@pytest.fixture(scope="module")
def token():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=30)
    assert r.status_code == 200, r.text
    j = r.json()
    tok = j.get("token") or j.get("access_token")
    if j.get("requires_2fa") or j.get("requires_2fa_setup"):
        code = pyotp.TOTP(TOTP_SECRET).now()
        r2 = s.post(f"{BASE_URL}/api/auth/verify-2fa",
                    json={"code": code},
                    headers={"Authorization": f"Bearer {tok}"}, timeout=30)
        assert r2.status_code == 200, r2.text
        tok = r2.json().get("token") or r2.json().get("access_token")
    assert tok
    return tok


@pytest.fixture
def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


# --- TV dashboard ------------------------------------------------------------

def test_tv_dashboard_public_and_fast():
    t0 = time.monotonic()
    r = requests.get(f"{BASE_URL}/api/tv/dashboard", timeout=30)
    dt1 = time.monotonic() - t0
    assert r.status_code == 200, r.text
    j = r.json()
    assert "clients" in j and "alert_feed" in j and "offline_devices" in j
    assert dt1 < 5, f"first call too slow: {dt1:.2f}s"
    # second call, should be cached
    t1 = time.monotonic()
    r2 = requests.get(f"{BASE_URL}/api/tv/dashboard", timeout=30)
    dt2 = time.monotonic() - t1
    assert r2.status_code == 200
    assert dt2 < 1.0, f"cached call too slow: {dt2:.2f}s"


@pytest.mark.asyncio
async def test_tv_alert_feed_only_active_and_dedup():
    r = requests.get(f"{BASE_URL}/api/tv/dashboard", timeout=30)
    assert r.status_code == 200
    feed = r.json().get("alert_feed", [])
    # Cross-check IDs against active alerts directly in DB (bypass /api/alerts
    # limit=1000 pagination; TV feed prioritizes critical which may be older).
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    mc = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = mc[os.environ["DB_NAME"]]
    ids = [a.get("id") for a in feed if a.get("id")]
    if ids:
        docs = await db.alerts.find({"id": {"$in": ids}},
                                    {"_id": 0, "id": 1, "status": 1}).to_list(len(ids))
        by_id = {d["id"]: d for d in docs}
        for aid in ids:
            d = by_id.get(aid)
            assert d is not None, f"alert {aid} in feed not found in DB"
            assert d["status"] == "active", f"alert {aid} in feed has status {d['status']}"
    mc.close()
    # dedup by (client_id, title, device_name)
    seen = set()
    for a in feed:
        key = (a.get("client_id"), (a.get("title") or "").strip().lower(),
               (a.get("device_name") or "").strip().lower())
        assert key not in seen, f"duplicate feed row: {key}"
        seen.add(key)


# --- Overview ---------------------------------------------------------------

def test_overview_clients_requires_auth_and_cached(auth_headers):
    # no auth -> 401/403
    r_noauth = requests.get(f"{BASE_URL}/api/overview/clients", timeout=30)
    assert r_noauth.status_code in (401, 403)
    t0 = time.monotonic()
    r = requests.get(f"{BASE_URL}/api/overview/clients",
                     headers=auth_headers, timeout=60)
    dt1 = time.monotonic() - t0
    assert r.status_code == 200, r.text
    j = r.json()
    assert "clients" in j and "global" in j
    assert isinstance(j["clients"], list)
    # cached
    t1 = time.monotonic()
    r2 = requests.get(f"{BASE_URL}/api/overview/clients",
                      headers=auth_headers, timeout=30)
    dt2 = time.monotonic() - t1
    assert r2.status_code == 200
    assert dt2 < 1.0, f"cached overview too slow: {dt2:.2f}s"


# --- Alerts sort_by=severity -------------------------------------------------

def test_alerts_sort_by_severity(auth_headers):
    r = requests.get(
        f"{BASE_URL}/api/alerts?status=active&sort_by=severity&limit=1000",
        headers=auth_headers, timeout=30)
    assert r.status_code == 200, r.text
    alerts = r.json()
    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    prev = -1
    for a in alerts:
        r_ = rank.get(a.get("severity"), 4)
        assert r_ >= prev, f"out-of-order severity {a.get('severity')} after {prev}"
        prev = r_


# --- alert_hygiene.resolve_recovered_device_alerts ---------------------------

@pytest.mark.asyncio
async def test_resolve_recovered_device_alerts_isolated():
    """Seed a fake client with an online device + a corr_* alert, run hygiene,
    verify alert is resolved. Then a second device offline case verifies the
    alert stays active. Cleanup afterwards.
    """
    from motor.motor_asyncio import AsyncIOMotorClient
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    fake_cid = f"TEST_hyg_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    fresh = (now - timedelta(seconds=30)).isoformat()
    ip_ok = "10.99.0.10"
    ip_ko = "10.99.0.11"

    try:
        # Fake client + fresh managed_agents heartbeat (so cascade-stale isn't triggered)
        await db.clients.insert_one({"id": fake_cid, "name": "TEST_HYG_CLIENT"})
        await db.managed_agents.insert_one({
            "client_id": fake_cid, "agent_id": f"TEST_{fake_cid}",
            "connected": True, "last_heartbeat_at": fresh,
            "last_seen_at": fresh, "agent_version": "test",
        })
        # device online (reachable recent) -> alert should be resolved
        await db.device_poll_status.insert_one({
            "client_id": fake_cid, "device_ip": ip_ok,
            "reachable": True, "ping_reachable": True,
            "last_reachable_at": fresh, "last_poll": fresh, "updated_at": fresh,
            "consecutive_failures": 0,
        })
        await db.managed_devices.insert_one({
            "client_id": fake_cid, "ip": ip_ok, "name": "TEST_OK",
            "is_vital": True, "last_seen_at": fresh,
        })
        alert_ok_id = str(uuid.uuid4())
        await db.alerts.insert_one({
            "id": alert_ok_id, "client_id": fake_cid, "device_ip": ip_ok,
            "device_name": "TEST_OK", "severity": "high",
            "source_type": "corr_device_offline", "title": "Device offline",
            "status": "active", "created_at": now_iso,
        })
        # device offline -> alert should remain active
        stale = (now - timedelta(minutes=30)).isoformat()
        await db.device_poll_status.insert_one({
            "client_id": fake_cid, "device_ip": ip_ko,
            "reachable": False, "ping_reachable": False,
            "last_reachable_at": stale, "last_poll": fresh, "updated_at": fresh,
            "consecutive_failures": 20,
        })
        await db.managed_devices.insert_one({
            "client_id": fake_cid, "ip": ip_ko, "name": "TEST_KO",
            "is_vital": True, "last_seen_at": fresh,
        })
        alert_ko_id = str(uuid.uuid4())
        await db.alerts.insert_one({
            "id": alert_ko_id, "client_id": fake_cid, "device_ip": ip_ko,
            "device_name": "TEST_KO", "severity": "high",
            "source_type": "vital_device_offline", "title": "Vital offline",
            "status": "active", "created_at": now_iso,
        })

        # Run hygiene (import from repo)
        import sys
        sys.path.insert(0, "/app/backend")
        from alert_hygiene import resolve_recovered_device_alerts
        # Force the hygiene function to use the same DB
        n = await resolve_recovered_device_alerts(db)
        assert n >= 1, f"hygiene should have resolved at least 1 alert, got {n}"

        a_ok = await db.alerts.find_one({"id": alert_ok_id}, {"_id": 0})
        a_ko = await db.alerts.find_one({"id": alert_ko_id}, {"_id": 0})
        assert a_ok["status"] == "resolved", f"OK-device alert still active: {a_ok}"
        assert a_ko["status"] == "active", f"KO-device alert should stay active: {a_ko}"
    finally:
        # Cleanup
        await db.alerts.delete_many({"client_id": fake_cid})
        await db.clients.delete_one({"id": fake_cid})
        await db.managed_agents.delete_many({"client_id": fake_cid})
        await db.device_poll_status.delete_many({"client_id": fake_cid})
        await db.managed_devices.delete_many({"client_id": fake_cid})
        await db.vital_offline_state.delete_many({"client_id": fake_cid})
        client.close()
