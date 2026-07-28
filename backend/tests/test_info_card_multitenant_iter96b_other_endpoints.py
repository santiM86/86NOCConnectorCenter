"""
Iteration 96b — verifica se ALTRI endpoint by-ip sono ancora vulnerabili al leak
cross-tenant (stessa classe di bug del info-card, ma NON fixata).

Endpoint sotto esame:
  - GET /api/devices/by-ip/{ip}/vendor-details  (usato dal pannello Synology in DeviceInfoCard)
  - GET /api/devices/by-ip/{ip}/metrics         (storico metriche)
"""
import os
import re
from pathlib import Path

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

TEST_IP = "192.168.99.97"
CID_X = "TEST_CID_X2"
CID_Y = "TEST_CID_Y2"


@pytest.fixture(scope="session")
def client():
    content = Path("/app/memory/test_credentials.md").read_text(encoding="utf-8")
    email = re.search(r"(?im)^\s*[-*]?\s*Email:\s*`?([^`\s]+)", content).group(1)
    pwd = re.search(r"(?im)^\s*[-*]?\s*Password:\s*`?([^`\s]+)", content).group(1)
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": pwd}, timeout=30)
    assert r.status_code == 200, r.text[:300]
    s.headers.update({"Authorization": f"Bearer {r.json().get('access_token') or r.json().get('token')}"})
    return s


@pytest.fixture(scope="session", autouse=True)
def seed():
    mc = MongoClient(MONGO_URL)
    db = mc[DB_NAME]

    def cleanup():
        for cid in (CID_X, CID_Y):
            db.clients.delete_many({"id": cid})
            db.device_poll_status.delete_many({"client_id": cid})
            db.managed_devices.delete_many({"client_id": cid})
            db.metric_history.delete_many({"client_id": cid})

    cleanup()
    db.clients.insert_many([
        {"id": CID_X, "name": "TEST_Cliente_X2"},
        {"id": CID_Y, "name": "TEST_Cliente_Y2"},
    ])
    db.device_poll_status.insert_many([
        {"client_id": CID_X, "device_ip": TEST_IP, "device_name": "TEST_DEV_X2",
         "cpu_usage": 11, "vendor_metrics": {"tagX": 1}},
        {"client_id": CID_Y, "device_ip": TEST_IP, "device_name": "TEST_DEV_Y2",
         "cpu_usage": 99, "vendor_metrics": {"tagY": 1}},
    ])
    db.managed_devices.insert_many([
        {"id": "TEST_MD_X2", "client_id": CID_X, "ip": TEST_IP, "name": "TEST_DEV_X2"},
        {"id": "TEST_MD_Y2", "client_id": CID_Y, "ip": TEST_IP, "name": "TEST_DEV_Y2"},
    ])
    yield
    cleanup()
    mc.close()


class TestOtherByIpEndpointsScope:
    def test_vendor_details_accepts_and_honors_client_id(self, client):
        rx = client.get(f"{BASE_URL}/api/devices/by-ip/{TEST_IP}/vendor-details",
                        params={"client_id": CID_X}, timeout=30)
        ry = client.get(f"{BASE_URL}/api/devices/by-ip/{TEST_IP}/vendor-details",
                        params={"client_id": CID_Y}, timeout=30)
        assert rx.status_code == 200 and ry.status_code == 200
        assert rx.json().get("name") == "TEST_DEV_X2", f"leak: {rx.json().get('name')}"
        assert ry.json().get("name") == "TEST_DEV_Y2", f"leak: {ry.json().get('name')}"

    def test_metrics_history_honors_client_id(self, client):
        mc = MongoClient(MONGO_URL)
        db = mc[DB_NAME]
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        db.metric_history.insert_many([
            {"client_id": CID_X, "device_ip": TEST_IP, "metric": "cpu", "value": 10.0, "ts": now},
            {"client_id": CID_Y, "device_ip": TEST_IP, "metric": "cpu", "value": 90.0, "ts": now},
        ])
        mc.close()
        r = client.get(f"{BASE_URL}/api/devices/by-ip/{TEST_IP}/metrics",
                       params={"metric": "cpu", "period": "1h", "client_id": CID_X}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        pts = r.json().get("points") or []
        assert pts, "nessun punto ritornato"
        maxs = [p.get("max") for p in pts]
        avgs = [p.get("avg") for p in pts]
        assert 90.0 not in maxs, f"leak cross-tenant nelle metriche (max): {maxs}"
        assert all(a == 10.0 for a in avgs), f"leak cross-tenant nelle metriche (avg mixato): {avgs}"
