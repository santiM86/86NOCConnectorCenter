"""Iteration 90 — Triage flow: bulk-vital endpoint + new-device watchdog.

Tests:
- POST /api/devices/bulk-vital: validation + happy path with GET verify.
- Watchdog: POST /api/alert-engine/run-now creates a
  source_type='new_devices_detected' alert for a client with recently
  discovered managed_devices with is_vital null; then RESOLVES it after we
  clear those devices to is_vital=true.
- /api/alert-engine/config contains new_device_detection /
  new_device_window_hours defaults.
"""
import os
import uuid
import time
from datetime import datetime, timezone

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

ADMIN_EMAIL = "info@86bit.it"
ADMIN_PASSWORD = "Ariel17051986@!@86"

TEST_CLIENT_ID = f"test-triage-iter90-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                      timeout=30)
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def mongo():
    c = MongoClient(MONGO_URL)
    db = c[DB_NAME]
    yield db
    # cleanup
    db.managed_devices.delete_many({"client_id": TEST_CLIENT_ID})
    db.clients.delete_many({"id": TEST_CLIENT_ID})
    db.alerts.delete_many({"client_id": TEST_CLIENT_ID})
    c.close()


@pytest.fixture(scope="module", autouse=True)
def seed(mongo):
    now_iso = datetime.now(timezone.utc).isoformat()
    mongo.clients.insert_one({
        "id": TEST_CLIENT_ID, "name": "TEST_Triage_Iter90",
        "created_at": now_iso,
    })
    devices = []
    # 3 undecided infra devices (should be preselected as vital in UI)
    for i, (cat, ip) in enumerate([("firewall", "10.99.0.1"),
                                    ("switch", "10.99.0.2"),
                                    ("server", "10.99.0.3")]):
        devices.append({
            "id": str(uuid.uuid4()), "client_id": TEST_CLIENT_ID,
            "name": f"TEST_{cat}_{i}", "ip": ip, "ip_address": ip,
            "device_category": cat, "category": cat,
            "is_vital": None, "status": "online",
            "created_at": now_iso,
        })
    # 1 undecided non-infra
    devices.append({
        "id": str(uuid.uuid4()), "client_id": TEST_CLIENT_ID,
        "name": "TEST_printer_x", "ip": "10.99.0.10", "ip_address": "10.99.0.10",
        "device_category": "printer", "category": "printer",
        "is_vital": None, "status": "online",
        "created_at": now_iso,
    })
    mongo.managed_devices.insert_many(devices)
    yield


# ---------------- bulk-vital -----------------

class TestBulkVital:
    def test_missing_ips(self, headers):
        r = requests.post(f"{BASE_URL}/api/devices/bulk-vital",
                          headers=headers, json={"is_vital": True, "client_id": TEST_CLIENT_ID})
        assert r.status_code == 400

    def test_missing_is_vital(self, headers):
        r = requests.post(f"{BASE_URL}/api/devices/bulk-vital",
                          headers=headers, json={"ips": ["10.99.0.1"], "client_id": TEST_CLIENT_ID})
        assert r.status_code == 400

    def test_missing_client_id(self, headers):
        r = requests.post(f"{BASE_URL}/api/devices/bulk-vital",
                          headers=headers, json={"ips": ["10.99.0.1"], "is_vital": True})
        assert r.status_code == 400

    def test_set_vital_true_persists(self, headers, mongo):
        ips = ["10.99.0.1", "10.99.0.2"]
        r = requests.post(f"{BASE_URL}/api/devices/bulk-vital",
                          headers=headers,
                          json={"ips": ips, "is_vital": True,
                                "client_id": TEST_CLIENT_ID, "reason": "triage"})
        assert r.status_code == 200, r.text
        # verify DB persistence
        for ip in ips:
            d = mongo.managed_devices.find_one({"client_id": TEST_CLIENT_ID, "ip": ip})
            assert d and d.get("is_vital") is True
            assert d.get("is_vital_set_by") == ADMIN_EMAIL

    def test_set_vital_false_persists(self, headers, mongo):
        r = requests.post(f"{BASE_URL}/api/devices/bulk-vital",
                          headers=headers,
                          json={"ips": ["10.99.0.10"], "is_vital": False,
                                "client_id": TEST_CLIENT_ID, "reason": "triage"})
        assert r.status_code == 200, r.text
        d = mongo.managed_devices.find_one({"client_id": TEST_CLIENT_ID, "ip": "10.99.0.10"})
        assert d.get("is_vital") is False


# ---------------- Alert Engine config -----------------

class TestAlertEngineConfig:
    def test_config_has_new_device_keys(self, headers):
        r = requests.get(f"{BASE_URL}/api/alert-engine/config", headers=headers)
        assert r.status_code == 200, r.text
        cfg = r.json()
        assert "new_device_detection" in cfg
        assert "new_device_window_hours" in cfg
        assert isinstance(cfg["new_device_window_hours"], (int, float))


# ---------------- new-device watchdog -----------------

class TestNewDeviceWatchdog:
    def test_watchdog_creates_alert(self, headers, mongo):
        # Ensure at least ONE undecided device on the test client remains
        # (10.99.0.3 was seeded is_vital=None and not touched)
        d = mongo.managed_devices.find_one({"client_id": TEST_CLIENT_ID, "ip": "10.99.0.3"})
        assert d and d.get("is_vital") in (None,)

        # Trigger engine
        r = requests.post(f"{BASE_URL}/api/alert-engine/run-now", headers=headers, timeout=60)
        assert r.status_code == 200, r.text

        time.sleep(1)
        alert = mongo.alerts.find_one({
            "client_id": TEST_CLIENT_ID,
            "source_type": "new_devices_detected",
            "status": "active",
        })
        assert alert is not None, "Expected 'new_devices_detected' alert to be created"
        assert alert.get("severity") == "medium"

    def test_watchdog_resolves_alert(self, headers, mongo):
        # Classify the remaining undecided device -> should resolve alert
        r = requests.post(f"{BASE_URL}/api/devices/bulk-vital",
                          headers=headers,
                          json={"ips": ["10.99.0.3"], "is_vital": True,
                                "client_id": TEST_CLIENT_ID, "reason": "triage"})
        assert r.status_code == 200

        r = requests.post(f"{BASE_URL}/api/alert-engine/run-now", headers=headers, timeout=60)
        assert r.status_code == 200

        time.sleep(1)
        alert = mongo.alerts.find_one({
            "client_id": TEST_CLIENT_ID,
            "source_type": "new_devices_detected",
        })
        assert alert is not None
        assert alert.get("status") == "resolved", f"Alert should be resolved, got {alert.get('status')}"
