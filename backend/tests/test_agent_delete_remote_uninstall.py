"""Tests for DELETE /api/agents/{agent_id} (iteration 79).

Covers:
- DELETE without uninstall_remote → cleans all DB collections, audit row created
- DELETE with uninstall_remote=true on OFFLINE agent → uninstall_status='agent_offline'
- DELETE on non-existing agent_id → 404
- DELETE without auth → 401/403
- DELETE with viewer role → 403
- agent_cleanup_audit collection populated with proper criteria + status
- GET /api/agents no longer returns deleted agent

Test data is created via direct Mongo seeding (no real WS agent connects in preview).
All TEST_ prefixed docs are cleaned up at teardown.
"""
import os
import time
import uuid
import requests
import pytest
from datetime import datetime, timezone
from pymongo import MongoClient

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = "info@86bit.it"
ADMIN_PASS = "Ariel17051986@!@86"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


# ---------- Fixtures --------------------------------------------------------

@pytest.fixture(scope="module")
def mongo():
    cli = MongoClient(MONGO_URL)
    db = cli[DB_NAME]
    yield db
    # cleanup any stray TEST_ agent docs
    for col in ("managed_agents", "sys_metrics_latest", "sys_metrics_history",
                "device_poll_status", "agent_log_buffer", "agent_command_audit"):
        try:
            db[col].delete_many({"agent_id": {"$regex": "^TEST_"}})
        except Exception:
            pass
    cli.close()


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
def viewer_user(admin_headers):
    """Create a viewer user, return (email, password, token, user_id) — cleaned up after."""
    email = f"test.viewer.{uuid.uuid4().hex[:8]}@example.com"
    password = "ViewerPass123!"
    payload = {"email": email, "password": password,
               "name": "Test Viewer iter79", "role": "viewer"}
    r = requests.post(f"{API}/admin/users", json=payload, headers=admin_headers, timeout=15)
    if r.status_code not in (200, 201):
        pytest.skip(f"cannot create viewer user: {r.status_code} {r.text}")
    user_id = r.json().get("id") or r.json().get("user_id")

    # login as viewer
    lr = requests.post(f"{API}/auth/login",
                       json={"email": email, "password": password}, timeout=15)
    if lr.status_code != 200:
        pytest.skip(f"viewer login failed: {lr.status_code} {lr.text}")
    token = lr.json().get("token") or lr.json().get("access_token")
    yield {"email": email, "token": token, "user_id": user_id}
    # cleanup
    try:
        if user_id:
            requests.delete(f"{API}/admin/users/{user_id}", headers=admin_headers, timeout=10)
    except Exception:
        pass


def _seed_agent(db, agent_id: str, hostname: str = "TEST_host"):
    """Insert a fake agent + traces in multiple collections."""
    now = datetime.now(timezone.utc).isoformat()
    db.managed_agents.insert_one({
        "agent_id": agent_id,
        "hostname": hostname,
        "client_id": "TEST_client_iter79",
        "agent_version": "v4.0.0-test",
        "last_hello_at": now,
        "last_heartbeat_at": now,
        "labels": {"role": "test"},
    })
    db.sys_metrics_latest.insert_one({
        "agent_id": agent_id, "hostname": hostname,
        "cpu_pct": 12.3, "mem_pct": 45.6, "received_at": now,
    })
    db.sys_metrics_history.insert_many([
        {"agent_id": agent_id, "cpu_pct": 10, "received_at": now},
        {"agent_id": agent_id, "cpu_pct": 11, "received_at": now},
    ])
    db.device_poll_status.insert_one({
        "agent_id": agent_id, "device_id": "TEST_dev1", "status": "ok",
    })
    db.agent_log_buffer.insert_one({
        "agent_id": agent_id, "level": "info", "msg": "TEST log",
    })
    db.agent_command_audit.insert_one({
        "agent_id": agent_id, "command": "noop", "at": now,
    })


# ---------- Auth gating ------------------------------------------------------

def test_delete_agent_requires_auth():
    """DELETE without auth → 401/403"""
    fake_id = f"TEST_{uuid.uuid4().hex[:12]}"
    r = requests.delete(f"{API}/agents/{fake_id}", timeout=10)
    assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}: {r.text}"


def test_delete_agent_viewer_forbidden(viewer_user, mongo):
    """DELETE with viewer role → 403"""
    # seed an agent so the endpoint progresses past existence check (it requires admin BEFORE that)
    agent_id = f"TEST_viewer_{uuid.uuid4().hex[:12]}"
    _seed_agent(mongo, agent_id)
    try:
        r = requests.delete(
            f"{API}/agents/{agent_id}",
            headers={"Authorization": f"Bearer {viewer_user['token']}"},
            timeout=10,
        )
        assert r.status_code == 403, f"viewer should get 403, got {r.status_code}: {r.text}"
        # And the doc must still exist
        still = mongo.managed_agents.find_one({"agent_id": agent_id})
        assert still is not None, "viewer DELETE should NOT have purged the agent"
    finally:
        mongo.managed_agents.delete_many({"agent_id": agent_id})
        mongo.sys_metrics_latest.delete_many({"agent_id": agent_id})
        mongo.sys_metrics_history.delete_many({"agent_id": agent_id})
        mongo.device_poll_status.delete_many({"agent_id": agent_id})
        mongo.agent_log_buffer.delete_many({"agent_id": agent_id})
        mongo.agent_command_audit.delete_many({"agent_id": agent_id})


# ---------- 404 path ---------------------------------------------------------

def test_delete_nonexistent_agent_404(admin_headers):
    fake_id = f"TEST_does_not_exist_{uuid.uuid4().hex[:8]}"
    r = requests.delete(f"{API}/agents/{fake_id}", headers=admin_headers, timeout=10)
    assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text}"
    body = r.json()
    assert "agent_id non trovato" in (body.get("detail") or ""), \
        f"detail should mention 'agent_id non trovato', got: {body}"


# ---------- Happy path: delete-only -----------------------------------------

def test_delete_agent_center_only_purges_db(admin_headers, mongo):
    agent_id = f"TEST_center_{uuid.uuid4().hex[:12]}"
    _seed_agent(mongo, agent_id, hostname="TEST_center_host")

    # sanity: doc is there
    assert mongo.managed_agents.find_one({"agent_id": agent_id}) is not None

    r = requests.delete(f"{API}/agents/{agent_id}",
                        headers=admin_headers, timeout=15)
    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    body = r.json()
    assert body.get("deleted") is True
    assert body.get("uninstall_status") == "skipped"
    assert body.get("uninstall_remote") is False
    assert body.get("agent_id") == agent_id
    assert body.get("hostname") == "TEST_center_host"

    purged = body.get("collections_purged") or {}
    # must have purged at least these
    for col in ("managed_agents", "sys_metrics_latest", "sys_metrics_history",
                "device_poll_status", "agent_log_buffer", "agent_command_audit"):
        assert purged.get(col, 0) >= 1, f"{col} should be purged, got {purged}"

    # verify DB really empty for that agent_id
    for col in ("managed_agents", "sys_metrics_latest", "sys_metrics_history",
                "device_poll_status", "agent_log_buffer", "agent_command_audit"):
        leftover = mongo[col].count_documents({"agent_id": agent_id})
        assert leftover == 0, f"{col} still has {leftover} docs for {agent_id}"


# ---------- Happy path: delete-with-uninstall on OFFLINE agent --------------

def test_delete_agent_uninstall_remote_offline(admin_headers, mongo):
    agent_id = f"TEST_uninst_{uuid.uuid4().hex[:12]}"
    _seed_agent(mongo, agent_id, hostname="TEST_offline_host")

    r = requests.delete(f"{API}/agents/{agent_id}",
                        params={"uninstall_remote": "true"},
                        headers=admin_headers, timeout=15)
    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    body = r.json()
    assert body.get("deleted") is True
    assert body.get("uninstall_remote") is True
    assert body.get("uninstall_status") == "agent_offline", \
        f"expected agent_offline, got: {body}"
    # An informative error message should be present
    assert body.get("uninstall_error"), "uninstall_error should explain offline state"

    # And DB still purged regardless of offline state
    purged = body.get("collections_purged") or {}
    assert purged.get("managed_agents", 0) >= 1
    assert mongo.managed_agents.count_documents({"agent_id": agent_id}) == 0


# ---------- Audit collection check ------------------------------------------

def test_agent_cleanup_audit_populated(admin_headers, mongo):
    agent_id = f"TEST_audit_{uuid.uuid4().hex[:12]}"
    _seed_agent(mongo, agent_id, hostname="TEST_audit_host")

    r = requests.delete(f"{API}/agents/{agent_id}",
                        params={"uninstall_remote": "true"},
                        headers=admin_headers, timeout=15)
    assert r.status_code == 200

    # find latest audit row for this agent
    rows = list(mongo.agent_cleanup_audit.find(
        {"deleted_ids": agent_id}).sort("deleted_at", -1).limit(3))
    assert rows, f"audit row missing for {agent_id}"
    row = rows[0]
    assert row.get("criteria") == "delete-with-uninstall", \
        f"criteria should reflect uninstall_remote, got {row.get('criteria')}"
    assert row.get("uninstall_status") == "agent_offline"
    assert row.get("hostname") == "TEST_audit_host"
    assert row.get("client_id") == "TEST_client_iter79"
    cp = row.get("collections_purged") or {}
    assert cp.get("managed_agents", 0) >= 1
    assert row.get("deleted_by")  # email or id of admin


def test_agent_cleanup_audit_criteria_delete_only(admin_headers, mongo):
    agent_id = f"TEST_audit2_{uuid.uuid4().hex[:12]}"
    _seed_agent(mongo, agent_id)

    r = requests.delete(f"{API}/agents/{agent_id}",
                        headers=admin_headers, timeout=15)
    assert r.status_code == 200

    rows = list(mongo.agent_cleanup_audit.find(
        {"deleted_ids": agent_id}).sort("deleted_at", -1).limit(3))
    assert rows
    assert rows[0].get("criteria") == "delete-only"
    assert rows[0].get("uninstall_status") == "skipped"


# ---------- GET /api/agents no longer returns deleted -----------------------

def test_get_agents_excludes_deleted(admin_headers, mongo):
    agent_id = f"TEST_listcheck_{uuid.uuid4().hex[:12]}"
    _seed_agent(mongo, agent_id, hostname="TEST_listcheck_host")

    # confirm listed before delete
    r = requests.get(f"{API}/agents", headers=admin_headers, timeout=15)
    assert r.status_code == 200
    listing = r.json()
    # Endpoint may return list directly or {"agents": [...]}
    items = listing if isinstance(listing, list) else listing.get("agents", [])
    ids_before = {a.get("agent_id") for a in items}
    assert agent_id in ids_before, "seeded agent should appear in /api/agents"

    # delete
    dr = requests.delete(f"{API}/agents/{agent_id}",
                         headers=admin_headers, timeout=15)
    assert dr.status_code == 200

    # let any polling cache invalidate
    time.sleep(0.5)

    r2 = requests.get(f"{API}/agents", headers=admin_headers, timeout=15)
    assert r2.status_code == 200
    listing2 = r2.json()
    items2 = listing2 if isinstance(listing2, list) else listing2.get("agents", [])
    ids_after = {a.get("agent_id") for a in items2}
    assert agent_id not in ids_after, \
        f"deleted agent {agent_id} still appears in /api/agents"


# ---------- 400 on bad agent_id (length) ------------------------------------

def test_delete_agent_short_id_400(admin_headers):
    r = requests.delete(f"{API}/agents/abc", headers=admin_headers, timeout=10)
    # may be 400 (validation) or 404 (not found)
    assert r.status_code in (400, 404), f"expected 400/404, got {r.status_code}: {r.text}"
