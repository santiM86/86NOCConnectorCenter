"""
Iteration 97 — verifica fix multi-tenant sui 3 endpoint by-ip della Scheda Dispositivo:
  - GET /api/devices/by-ip/{ip}/info-card?client_id=      (re-verifica, fixato in iter96)
  - GET /api/devices/by-ip/{ip}/vendor-details?client_id=  (NUOVO fix)
  - GET /api/devices/by-ip/{ip}/metrics?client_id=         (NUOVO fix)

Seed: stesso IP condiviso (192.168.99.99) su 2 client fittizi TEST_CID_X/TEST_CID_Y,
+ IP esclusivo (192.168.99.95) del solo TEST_CID_X per la regressione base.
Collections: clients, device_poll_status, managed_devices, metric_history,
device_metrics_history. Tutto ripulito a fine sessione.
"""
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

SHARED_IP = "192.168.99.99"
SOLO_IP = "192.168.99.95"
CID_X = "TEST_CID_X"
CID_Y = "TEST_CID_Y"
CID_Z = "TEST_CID_Z"  # client senza device


@pytest.fixture(scope="session")
def client():
    content = Path("/app/memory/test_credentials.md").read_text(encoding="utf-8")
    email = re.search(r"(?im)^\s*[-*]?\s*Email:\s*`?([^`\s]+)", content).group(1)
    pwd = re.search(r"(?im)^\s*[-*]?\s*Password:\s*`?([^`\s]+)", content).group(1)
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": pwd}, timeout=30)
    if r.status_code != 200:
        pytest.fail(f"Login failed {r.status_code}: {r.text[:300]}")
    tok = r.json().get("access_token") or r.json().get("token")
    if not tok:
        pytest.fail(f"No token in login response: {r.text[:300]}")
    s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


def _cleanup(db):
    for cid in (CID_X, CID_Y, CID_Z):
        db.clients.delete_many({"id": cid})
        db.device_poll_status.delete_many({"client_id": cid})
        db.managed_devices.delete_many({"client_id": cid})
        db.metric_history.delete_many({"client_id": cid})
        db.device_metrics_history.delete_many({"client_id": cid})


@pytest.fixture(scope="session", autouse=True)
def seed():
    mc = MongoClient(MONGO_URL)
    db = mc[DB_NAME]
    _cleanup(db)

    now = datetime.now(timezone.utc)
    db.clients.insert_many([
        {"id": CID_X, "name": "TEST_Cliente_X"},
        {"id": CID_Y, "name": "TEST_Cliente_Y"},
        {"id": CID_Z, "name": "TEST_Cliente_Z"},
    ])
    db.device_poll_status.insert_many([
        {"client_id": CID_X, "device_ip": SHARED_IP, "device_name": "TEST_DEV_X",
         "name": "TEST_DEV_X", "cpu_usage": 11, "memory_usage": 21, "temperature": 31,
         "status": "online", "profile_key": "synology_dsm",
         "vendor_metrics": {"tag": "X", "temperatureC": 31}, "last_poll": now.isoformat()},
        {"client_id": CID_Y, "device_ip": SHARED_IP, "device_name": "TEST_DEV_Y",
         "name": "TEST_DEV_Y", "cpu_usage": 99, "memory_usage": 98, "temperature": 97,
         "status": "offline", "profile_key": "fortinet_fortigate",
         "vendor_metrics": {"tag": "Y", "fgSysCpuUsage": 99}, "last_poll": now.isoformat()},
        {"client_id": CID_X, "device_ip": SOLO_IP, "device_name": "TEST_DEV_SOLO",
         "name": "TEST_DEV_SOLO", "cpu_usage": 42, "status": "online",
         "vendor_metrics": {"tag": "SOLO"}, "last_poll": now.isoformat()},
    ])
    db.managed_devices.insert_many([
        {"id": "TEST_MD_X", "client_id": CID_X, "ip": SHARED_IP, "name": "TEST_DEV_X",
         "hostname": "host-x", "device_type": "nas", "profile_key": "synology_dsm"},
        {"id": "TEST_MD_Y", "client_id": CID_Y, "ip": SHARED_IP, "name": "TEST_DEV_Y",
         "hostname": "host-y", "device_type": "firewall", "profile_key": "fortinet_fortigate"},
        {"id": "TEST_MD_SOLO", "client_id": CID_X, "ip": SOLO_IP, "name": "TEST_DEV_SOLO",
         "hostname": "host-solo", "device_type": "switch"},
    ])

    # metric_history (nuova): cpu 10 per X, 90 per Y  su SHARED_IP
    mh = []
    for i in range(6):
        ts = now - timedelta(minutes=5 * i)
        mh.append({"client_id": CID_X, "device_ip": SHARED_IP, "metric": "cpu", "value": 10.0, "ts": ts})
        mh.append({"client_id": CID_Y, "device_ip": SHARED_IP, "metric": "cpu", "value": 90.0, "ts": ts})
        mh.append({"client_id": CID_X, "device_ip": SOLO_IP, "metric": "cpu", "value": 42.0, "ts": ts})
    db.metric_history.insert_many(mh)

    # device_metrics_history (legacy, timestamp ISO string): cpu_usage 20 per X, 80 per Y
    lh = []
    for i in range(6):
        ts = (now - timedelta(minutes=5 * i)).isoformat()
        lh.append({"client_id": CID_X, "device_ip": SHARED_IP, "timestamp": ts,
                   "cpu_usage": 20.0, "memory_usage": 25.0, "ping_avg": 5.0})
        lh.append({"client_id": CID_Y, "device_ip": SHARED_IP, "timestamp": ts,
                   "cpu_usage": 80.0, "memory_usage": 85.0, "ping_avg": 50.0})
    db.device_metrics_history.insert_many(lh)

    yield
    _cleanup(db)
    # verifica pulizia
    assert db.device_poll_status.count_documents({"client_id": {"$in": [CID_X, CID_Y]}}) == 0
    assert db.metric_history.count_documents({"client_id": {"$in": [CID_X, CID_Y]}}) == 0
    assert db.device_metrics_history.count_documents({"client_id": {"$in": [CID_X, CID_Y]}}) == 0
    mc.close()


# ---------------------------------------------------------------- info-card
class TestInfoCardScope:
    def test_info_card_returns_only_requested_client(self, client):
        rx = client.get(f"{BASE_URL}/api/devices/by-ip/{SHARED_IP}/info-card",
                        params={"client_id": CID_X}, timeout=30)
        ry = client.get(f"{BASE_URL}/api/devices/by-ip/{SHARED_IP}/info-card",
                        params={"client_id": CID_Y}, timeout=30)
        assert rx.status_code == 200, rx.text[:300]
        assert ry.status_code == 200, ry.text[:300]
        dx, dy = rx.json(), ry.json()
        sx, sy = str(dx), str(dy)
        assert "TEST_DEV_Y" not in sx and "host-y" not in sx, f"leak Y in X: {sx[:500]}"
        assert "TEST_DEV_X" not in sy and "host-x" not in sy, f"leak X in Y: {sy[:500]}"
        assert "_id" not in sx

    def test_info_card_404_for_client_without_ip(self, client):
        r = client.get(f"{BASE_URL}/api/devices/by-ip/{SHARED_IP}/info-card",
                       params={"client_id": CID_Z}, timeout=30)
        assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text[:300]}"

    def test_info_card_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/devices/by-ip/{SHARED_IP}/info-card",
                         params={"client_id": CID_X}, timeout=30)
        assert r.status_code in (401, 403), r.status_code


# ------------------------------------------------------------ vendor-details
class TestVendorDetailsScope:
    def test_vendor_details_scoped_by_client(self, client):
        rx = client.get(f"{BASE_URL}/api/devices/by-ip/{SHARED_IP}/vendor-details",
                        params={"client_id": CID_X}, timeout=30)
        ry = client.get(f"{BASE_URL}/api/devices/by-ip/{SHARED_IP}/vendor-details",
                        params={"client_id": CID_Y}, timeout=30)
        assert rx.status_code == 200, rx.text[:300]
        assert ry.status_code == 200, ry.text[:300]
        dx, dy = rx.json(), ry.json()

        assert dx["name"] == "TEST_DEV_X", f"leak: {dx['name']}"
        assert dx["profile_key"] == "synology_dsm", dx["profile_key"]
        assert dx["cpu_usage"] == 11, dx["cpu_usage"]
        assert dx["vendor_metrics"].get("tag") == "X", dx["vendor_metrics"]
        assert "fgSysCpuUsage" not in dx["vendor_metrics"], dx["vendor_metrics"]
        assert dx.get("status") == "online"

        assert dy["name"] == "TEST_DEV_Y", f"leak: {dy['name']}"
        assert dy["profile_key"] == "fortinet_fortigate", dy["profile_key"]
        assert dy["cpu_usage"] == 99, dy["cpu_usage"]
        assert dy["vendor_metrics"].get("tag") == "Y", dy["vendor_metrics"]
        assert dy.get("status") == "offline"

    def test_vendor_details_no_leak_for_client_without_ip(self, client):
        r = client.get(f"{BASE_URL}/api/devices/by-ip/{SHARED_IP}/vendor-details",
                       params={"client_id": CID_Z}, timeout=30)
        assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text[:400]}"
        body = r.text
        assert "TEST_DEV_X" not in body and "TEST_DEV_Y" not in body, body[:400]

    def test_vendor_details_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/devices/by-ip/{SHARED_IP}/vendor-details",
                         params={"client_id": CID_X}, timeout=30)
        assert r.status_code in (401, 403), r.status_code


# ------------------------------------------------------------ metrics history
class TestMetricsHistoryScope:
    def test_metrics_cpu_only_requested_client(self, client):
        r = client.get(f"{BASE_URL}/api/devices/by-ip/{SHARED_IP}/metrics",
                       params={"metric": "cpu", "period": "24h", "client_id": CID_X}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        pts = r.json().get("points") or []
        assert pts, "nessun punto ritornato per client X"
        # X ha value=10 (metric_history) e cpu_usage=20 (legacy) -> range 10..20
        for p in pts:
            assert 10.0 <= p["min"] <= 20.0, f"min fuori range (leak?): {p}"
            assert 10.0 <= p["max"] <= 20.0, f"max fuori range (leak Y=80/90?): {p}"
            assert 10.0 <= p["avg"] <= 20.0, f"avg mixato: {p}"

    def test_metrics_cpu_client_y_isolated(self, client):
        r = client.get(f"{BASE_URL}/api/devices/by-ip/{SHARED_IP}/metrics",
                       params={"metric": "cpu", "period": "24h", "client_id": CID_Y}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        pts = r.json().get("points") or []
        assert pts, "nessun punto ritornato per client Y"
        for p in pts:
            assert 80.0 <= p["min"] <= 90.0, f"leak X (10/20) in serie Y: {p}"
            assert 80.0 <= p["max"] <= 90.0, f"leak X in serie Y: {p}"

    def test_metrics_memory_scoped(self, client):
        r = client.get(f"{BASE_URL}/api/devices/by-ip/{SHARED_IP}/metrics",
                       params={"metric": "memory", "period": "24h", "client_id": CID_X}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        pts = r.json().get("points") or []
        assert pts, "nessun punto memory per X (legacy source)"
        for p in pts:
            assert p["max"] == 25.0, f"leak memory Y=85: {p}"

    def test_metrics_empty_for_client_without_data(self, client):
        r = client.get(f"{BASE_URL}/api/devices/by-ip/{SHARED_IP}/metrics",
                       params={"metric": "cpu", "period": "24h", "client_id": CID_Z}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert data.get("count") == 0, f"leak: {data}"
        assert data.get("points") == []


# ------------------------------------------------------------ regressione base
class TestSingleClientRegression:
    def test_all_three_endpoints_ok_for_exclusive_device(self, client):
        r1 = client.get(f"{BASE_URL}/api/devices/by-ip/{SOLO_IP}/info-card",
                        params={"client_id": CID_X}, timeout=30)
        assert r1.status_code == 200, r1.text[:300]
        assert "TEST_DEV_SOLO" in str(r1.json())

        r2 = client.get(f"{BASE_URL}/api/devices/by-ip/{SOLO_IP}/vendor-details",
                        params={"client_id": CID_X}, timeout=30)
        assert r2.status_code == 200, r2.text[:300]
        assert r2.json()["name"] == "TEST_DEV_SOLO"
        assert r2.json()["cpu_usage"] == 42

        r3 = client.get(f"{BASE_URL}/api/devices/by-ip/{SOLO_IP}/metrics",
                        params={"metric": "cpu", "period": "24h", "client_id": CID_X}, timeout=30)
        assert r3.status_code == 200, r3.text[:300]
        pts = r3.json().get("points") or []
        assert pts and all(p["avg"] == 42.0 for p in pts), pts

    def test_backward_compat_without_client_id(self, client):
        """Senza client_id gli endpoint devono ancora rispondere 200 (retrocompat)."""
        for url, params in [
            (f"{BASE_URL}/api/devices/by-ip/{SOLO_IP}/vendor-details", {}),
            (f"{BASE_URL}/api/devices/by-ip/{SOLO_IP}/metrics", {"metric": "cpu", "period": "24h"}),
        ]:
            r = client.get(url, params=params, timeout=30)
            assert r.status_code == 200, f"{url} -> {r.status_code} {r.text[:200]}"
