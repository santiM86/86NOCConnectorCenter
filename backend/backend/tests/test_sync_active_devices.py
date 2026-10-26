"""Tests for POST /api/connector/sync-active-devices (HMAC/connector auth).
Covers: auth, validation, sync logic (connector-source removal, manual/silenced preservation),
dry_run, empty list safety, alert resolution on removal.
"""
import os
import uuid
import asyncio
import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

from pathlib import Path

# Load env vars from backend/.env and frontend/.env
for p in ['/app/backend/.env', '/app/frontend/.env']:
    try:
        for ln in Path(p).read_text().splitlines():
            if '=' in ln and not ln.strip().startswith('#'):
                k, v = ln.split('=', 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass

BASE_URL = os.environ['REACT_APP_BACKEND_URL'].rstrip('/')
SYNC_URL = f"{BASE_URL}/api/connector/sync-active-devices"

MONGO_URL = os.environ['MONGO_URL']
DB_NAME = os.environ['DB_NAME']

# Test IPs (TEST_ prefix via high subnet for easy identification)
TEST_IPS_CONNECTOR = ["10.88.1.1", "10.88.2.2", "10.88.3.3"]
TEST_IP_MANUAL = "10.88.9.9"
TEST_IP_SILENCED = "10.88.5.5"


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def mongo():
    return AsyncIOMotorClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def client_info(event_loop, mongo):
    async def _get():
        c = await mongo.clients.find_one({}, {"_id": 0, "id": 1, "name": 1, "api_key": 1})
        if not c or not c.get("api_key"):
            pytest.skip("No client with api_key found in DB")
        return c
    return event_loop.run_until_complete(_get())


@pytest.fixture(scope="module")
def headers(client_info):
    return {"X-API-Key": client_info["api_key"], "Content-Type": "application/json"}


@pytest.fixture(scope="module", autouse=True)
def setup_and_cleanup(event_loop, mongo, client_info):
    """Seed test devices + alerts; cleanup at end."""
    cid = client_info["id"]
    all_ips = TEST_IPS_CONNECTOR + [TEST_IP_MANUAL, TEST_IP_SILENCED]

    async def _setup():
        # Clean any leftovers first
        await mongo.managed_devices.delete_many({"client_id": cid, "ip": {"$in": all_ips}})
        await mongo.device_poll_status.delete_many({"client_id": cid, "device_ip": {"$in": all_ips}})
        await mongo.alerts.delete_many({"client_id": cid, "device_ip": {"$in": all_ips}})
        # Seed 3 connector devices
        for ip in TEST_IPS_CONNECTOR:
            await mongo.managed_devices.insert_one({
                "id": str(uuid.uuid4()), "client_id": cid, "ip": ip,
                "name": f"TEST_{ip}", "source": "connector",
                "alerts_silenced": False, "monitor_type": "snmp",
            })
        # Seed 1 manual
        await mongo.managed_devices.insert_one({
            "id": str(uuid.uuid4()), "client_id": cid, "ip": TEST_IP_MANUAL,
            "name": "TEST_manual", "source": "manual",
            "alerts_silenced": False, "monitor_type": "snmp",
        })
        # Seed 1 silenced (source=connector, but silenced)
        await mongo.managed_devices.insert_one({
            "id": str(uuid.uuid4()), "client_id": cid, "ip": TEST_IP_SILENCED,
            "name": "TEST_silenced", "source": "connector",
            "alerts_silenced": True, "monitor_type": "snmp",
        })
        # Seed active alert on 10.88.2.2 (should become resolved after sync)
        await mongo.alerts.insert_one({
            "id": str(uuid.uuid4()), "client_id": cid, "device_ip": "10.88.2.2",
            "title": "TEST alert for sync", "severity": "high", "status": "active",
            "source_type": "test",
        })
    event_loop.run_until_complete(_setup())

    yield

    async def _clean():
        await mongo.managed_devices.delete_many({"client_id": cid, "ip": {"$in": all_ips}})
        await mongo.device_poll_status.delete_many({"client_id": cid, "device_ip": {"$in": all_ips}})
        await mongo.alerts.delete_many({"client_id": cid, "device_ip": {"$in": all_ips}, "title": "TEST alert for sync"})
    event_loop.run_until_complete(_clean())


# ========== AUTH ==========

def test_missing_api_key_returns_401():
    r = requests.post(SYNC_URL, json={"active_ips": ["1.1.1.1"]}, timeout=15)
    assert r.status_code == 401, r.text
    body = r.json()
    assert "Missing API key" in (body.get("detail") or "")


def test_invalid_api_key_returns_401():
    r = requests.post(SYNC_URL, json={"active_ips": ["1.1.1.1"]},
                      headers={"X-API-Key": "bogus_key_xxx", "Content-Type": "application/json"}, timeout=15)
    assert r.status_code == 401
    assert "Invalid API key" in r.json().get("detail", "")


# ========== VALIDATION ==========

def test_missing_active_ips_field(headers):
    # body without active_ips → should return ok:false, error message
    r = requests.post(SYNC_URL, json={}, headers=headers, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is False
    assert body.get("error") in ("active_ips must be list", "empty_active_ips_rejected_for_safety")


def test_active_ips_not_list(headers):
    r = requests.post(SYNC_URL, json={"active_ips": "1.1.1.1"}, headers=headers, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is False
    assert body.get("error") == "active_ips must be list"


def test_empty_list_rejected_for_safety(headers):
    r = requests.post(SYNC_URL, json={"active_ips": [], "dry_run": False}, headers=headers, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is False
    assert body.get("error") == "empty_active_ips_rejected_for_safety"


def test_empty_list_rejected_even_with_dry_run(headers):
    r = requests.post(SYNC_URL, json={"active_ips": [], "dry_run": True}, headers=headers, timeout=15)
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is False
    assert body.get("error") == "empty_active_ips_rejected_for_safety"


# ========== DRY RUN ==========

def test_dry_run_identifies_candidates_without_deleting(headers, mongo, event_loop, client_info):
    cid = client_info["id"]
    # Only 10.88.1.1 active → expect 10.88.2.2 and 10.88.3.3 as candidates.
    # Manual (10.88.9.9) and silenced (10.88.5.5) must NOT appear.
    r = requests.post(SYNC_URL, json={"active_ips": ["10.88.1.1"], "dry_run": True},
                      headers=headers, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    assert body.get("dry_run") is True
    would_ips = {d["ip"] for d in body.get("would_remove", [])}
    # Test IPs: 2.2 and 3.3 should be there. The rest may also be there (stale real data).
    assert "10.88.2.2" in would_ips
    assert "10.88.3.3" in would_ips
    assert "10.88.9.9" not in would_ips, "manual device should be preserved"
    assert "10.88.5.5" not in would_ips, "silenced device should be preserved"

    # Verify nothing was deleted
    async def _check():
        cnt = await mongo.managed_devices.count_documents(
            {"client_id": cid, "ip": {"$in": TEST_IPS_CONNECTOR}}
        )
        return cnt
    count = event_loop.run_until_complete(_check())
    assert count == 3, f"dry_run must not delete; found {count} connector test devices"


# ========== ACTUAL SYNC ==========

def test_sync_removes_only_missing_connector_devices(headers, mongo, event_loop, client_info):
    cid = client_info["id"]
    r = requests.post(SYNC_URL, json={"active_ips": ["10.88.1.1"], "dry_run": False},
                      headers=headers, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    assert isinstance(body.get("removed_count"), int)
    assert body["removed_count"] >= 2

    async def _check():
        # 1.1.1.1 should still exist (active)
        active = await mongo.managed_devices.find_one({"client_id": cid, "ip": "10.88.1.1"})
        # 2.2.2.2 and 3.3.3.3 should be gone
        d2 = await mongo.managed_devices.find_one({"client_id": cid, "ip": "10.88.2.2"})
        d3 = await mongo.managed_devices.find_one({"client_id": cid, "ip": "10.88.3.3"})
        # Manual must persist
        manual = await mongo.managed_devices.find_one({"client_id": cid, "ip": TEST_IP_MANUAL})
        # Silenced must persist
        silenced = await mongo.managed_devices.find_one({"client_id": cid, "ip": TEST_IP_SILENCED})
        return active, d2, d3, manual, silenced
    active, d2, d3, manual, silenced = event_loop.run_until_complete(_check())
    assert active is not None, "active IP must NOT be removed"
    assert d2 is None, "connector device not in active list must be removed"
    assert d3 is None, "connector device not in active list must be removed"
    assert manual is not None, "manual device must be preserved"
    assert silenced is not None, "silenced device must be preserved"


def test_alerts_auto_resolved_on_device_removal(headers, mongo, event_loop, client_info):
    """After the previous test removed 10.88.2.2, its active alert must be resolved with auto-sync note."""
    cid = client_info["id"]

    async def _check():
        alert = await mongo.alerts.find_one(
            {"client_id": cid, "device_ip": "10.88.2.2", "title": "TEST alert for sync"}
        )
        return alert
    alert = event_loop.run_until_complete(_check())
    assert alert is not None, "alert record missing"
    assert alert.get("status") == "resolved", f"alert status: {alert.get('status')}"
    note = alert.get("resolution_note") or ""
    assert "auto-sync" in note.lower() or "auto sync" in note.lower(), f"unexpected note: {note}"


# ========== CONNECTOR.PS1 INTEGRATION BLOCK PRESENT ==========

def test_connector_ps1_has_sync_block():
    ps1 = Path("/app/noc-connector/prg/src/connector.ps1").read_text(encoding="utf-8", errors="ignore")
    assert "Sincronizzazione inversa Center" in ps1
    assert "connector/sync-active-devices" in ps1
    assert "active_ips" in ps1
    # Must come after device-report
    idx_dr = ps1.find("connector/device-report")
    idx_sync = ps1.find("connector/sync-active-devices")
    assert idx_dr > 0 and idx_sync > idx_dr, "sync block must come AFTER device-report"


def test_version_json_is_3_5_25():
    import json
    v = json.loads(Path("/app/noc-connector/prg/version.json").read_text())
    assert v["version"] == "3.5.25"
