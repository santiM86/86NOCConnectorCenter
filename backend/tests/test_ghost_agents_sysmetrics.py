"""Tests for ghost agent cleanup + sys_metrics endpoints (iteration 78).

Covers:
- GET /api/agents/stale (admin auth)
- POST /api/agents/cleanup (manual + all_stale)
- agent_cleanup_audit collection
- GET /api/agents/{id}/sys-metrics/latest, /history
- GET /api/sys-metrics/overview
- Removed legacy /connectors UI (route serves SPA, so we just probe API)
- Legacy /api/connector/status still reachable
"""
import os
import time
import uuid
import requests
import pytest
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = "info@86bit.it"
ADMIN_PASS = "Ariel17051986@!@86"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
                      timeout=15)
    assert r.status_code == 200, f"login failed {r.status_code}: {r.text}"
    return r.json().get("token") or r.json().get("access_token")


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def mongo():
    cli = MongoClient(MONGO_URL)
    db = cli[DB_NAME]
    yield db
    cli.close()


# ----- Auth gating ----------------------------------------------------------

def test_agents_stale_requires_auth():
    r = requests.get(f"{API}/agents/stale", timeout=10)
    assert r.status_code in (401, 403)


def test_agents_cleanup_requires_auth():
    r = requests.post(f"{API}/agents/cleanup",
                      json={"cleanup_all_stale": True}, timeout=10)
    assert r.status_code in (401, 403)


def test_sysmetrics_overview_requires_auth():
    r = requests.get(f"{API}/sys-metrics/overview", timeout=10)
    assert r.status_code in (401, 403)


# ----- /api/agents/stale ----------------------------------------------------

def test_agents_stale_returns_list(admin_headers):
    r = requests.get(f"{API}/agents/stale?stale_days=7",
                     headers=admin_headers, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "stale_count" in data and "agents" in data
    assert data["stale_days"] == 7
    assert isinstance(data["agents"], list)


def test_agents_stale_clamps_invalid_days(admin_headers):
    r = requests.get(f"{API}/agents/stale?stale_days=99999",
                     headers=admin_headers, timeout=15)
    assert r.status_code == 200
    assert r.json()["stale_days"] == 365


# ----- /api/agents/cleanup --------------------------------------------------

def test_cleanup_requires_payload(admin_headers):
    r = requests.post(f"{API}/agents/cleanup", json={},
                      headers=admin_headers, timeout=10)
    assert r.status_code == 400


def test_cleanup_specific_id_and_audit(admin_headers, mongo):
    """Insert a ghost record, delete it, verify audit row written."""
    ghost_id = f"TEST_ghost_{uuid.uuid4().hex[:10]}"
    mongo.managed_agents.insert_one({
        "agent_id": ghost_id,
        "hostname": "TEST_ghost_host",
        "client_id": "TEST_CID",
        "first_seen_at": (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
    })
    try:
        r = requests.post(f"{API}/agents/cleanup",
                          json={"agent_ids": [ghost_id]},
                          headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["deleted_count"] == 1
        assert ghost_id in data["deleted_ids"]
        # verify gone in DB
        assert mongo.managed_agents.find_one({"agent_id": ghost_id}) is None
        # verify audit entry
        audit = mongo.agent_cleanup_audit.find_one(
            {"deleted_ids": ghost_id}, sort=[("_id", -1)])
        assert audit is not None
        assert audit["count"] >= 1
        assert audit["criteria"] == "manual"
    finally:
        mongo.managed_agents.delete_one({"agent_id": ghost_id})


def test_cleanup_all_stale_with_seed(admin_headers, mongo):
    """Seed two stale ghost agents, run cleanup_all_stale, expect both gone."""
    ids = [f"TEST_stale_{uuid.uuid4().hex[:8]}" for _ in range(2)]
    old_iso = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    for aid in ids:
        mongo.managed_agents.insert_one({
            "agent_id": aid,
            "hostname": f"TEST_host_{aid}",
            "client_id": "TEST_CID2",
            "last_heartbeat_at": old_iso,
            "first_seen_at": old_iso,
        })
    try:
        r = requests.post(f"{API}/agents/cleanup",
                          json={"cleanup_all_stale": True,
                                "stale_days": 30,
                                "client_id": "TEST_CID2"},
                          headers=admin_headers, timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        for aid in ids:
            assert aid in data["deleted_ids"], f"missing {aid} in {data}"
        # verify gone
        for aid in ids:
            assert mongo.managed_agents.find_one({"agent_id": aid}) is None
    finally:
        mongo.managed_agents.delete_many({"agent_id": {"$in": ids}})


# ----- sys-metrics endpoints ------------------------------------------------

def test_sysmetrics_latest_404_when_missing(admin_headers):
    fake = f"TEST_nonexistent_{uuid.uuid4().hex[:6]}"
    r = requests.get(f"{API}/agents/{fake}/sys-metrics/latest",
                     headers=admin_headers, timeout=10)
    assert r.status_code == 404


def test_sysmetrics_history_empty_returns_shape(admin_headers):
    fake = f"TEST_nonexistent_{uuid.uuid4().hex[:6]}"
    r = requests.get(f"{API}/agents/{fake}/sys-metrics/history?hours=24",
                     headers=admin_headers, timeout=10)
    assert r.status_code == 200
    data = r.json()
    assert data["sample_count"] == 0
    assert data["samples"] == []
    assert data["hours"] == 24


def test_sysmetrics_overview_shape(admin_headers):
    r = requests.get(f"{API}/sys-metrics/overview",
                     headers=admin_headers, timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert "count" in data
    assert "agents" in data and isinstance(data["agents"], list)


def test_sysmetrics_overview_with_seed(admin_headers, mongo):
    """Insert a doc in sys_metrics_latest, ensure overview enriches it."""
    aid = f"TEST_sm_{uuid.uuid4().hex[:8]}"
    sampled = datetime.now(timezone.utc).isoformat()
    mongo.sys_metrics_latest.insert_one({
        "agent_id": aid,
        "client_id": "TEST_CID_SM",
        "hostname": "TEST_sm_host",
        "sampled_at": sampled,
        "received_at": sampled,
        "cpu_percent": 17.5,
        "mem_used_pct": 42.0,
        "disks": [
            {"mount": "C:", "used_pct": 88.3},
            {"mount": "D:", "used_pct": 50.1},
        ],
    })
    try:
        r = requests.get(f"{API}/sys-metrics/overview?client_id=TEST_CID_SM",
                         headers=admin_headers, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["count"] >= 1
        agents = [a for a in data["agents"] if a["agent_id"] == aid]
        assert agents, f"seeded agent {aid} not returned"
        a = agents[0]
        # enrichment fields
        assert "age_seconds" in a and a["age_seconds"] is not None
        assert "stale" in a
        assert "live" in a
        assert "disk_max_pct" in a
        assert a["disk_max_pct"] == 88.3
        assert a["stale"] is False  # just inserted
    finally:
        mongo.sys_metrics_latest.delete_one({"agent_id": aid})


# ----- legacy connector endpoint --------------------------------------------

def test_legacy_connector_status_reachable():
    # Endpoint may need a client_id; we just verify it isn't 404 (route gone)
    r = requests.get(f"{API}/connector/status?client_id=TEST_CID",
                     timeout=10)
    # 200/400/401/422 all confirm route still mounted; only 404 means removed
    assert r.status_code != 404, f"Legacy /api/connector/status was removed (404)"


# ----- /connectors UI route removed -----------------------------------------

def test_connectors_ui_route_serves_spa_or_404():
    """The /connectors page was removed. The React SPA likely serves index.html
    for unknown routes (no hard 404), but we make sure backend doesn't expose
    something we shouldn't. We just check the frontend route loads SPA shell
    or returns a redirect/404."""
    r = requests.get(f"{BASE_URL}/connectors", timeout=10, allow_redirects=False)
    # Acceptable: SPA fallback 200 (will render NotFound inside), redirect, or 404
    assert r.status_code in (200, 301, 302, 404)
