"""
Iteration 96 — MULTI-TENANT ISOLATION del device info-card.

Bug: GET /api/devices/by-ip/{ip}/info-card faceva match SOLO per IP, quindi
IP privati comuni condivisi tra clienti restituivano il device del cliente
sbagliato (leak cross-tenant).

Test: seed di due client fittizi (TEST_CID_X / TEST_CID_Y) con lo stesso
device_ip 192.168.99.99 in device_poll_status + managed_devices, poi verifica
lo scope di:
  - GET /api/devices/by-ip/{ip}/info-card?client_id=...
  - GET /api/devices?client_id=...
Cleanup completo a fine classe.
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

TEST_IP = "192.168.99.99"
TEST_IP_UNIQUE = "192.168.99.98"
CID_X = "TEST_CID_X"
CID_Y = "TEST_CID_Y"
CID_Z = "TEST_CID_Z"  # client senza quell'IP


@pytest.fixture(scope="session")
def credentials():
    content = Path("/app/memory/test_credentials.md").read_text(encoding="utf-8")
    email = re.search(r"(?im)^\s*[-*]?\s*Email:\s*`?([^`\s]+)", content)
    pwd = re.search(r"(?im)^\s*[-*]?\s*Password:\s*`?([^`\s]+)", content)
    if not email or not pwd:
        pytest.skip("credenziali non trovate in test_credentials.md")
    return {"email": email.group(1), "password": pwd.group(1)}


@pytest.fixture(scope="session")
def client(credentials):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json=credentials, timeout=30)
    if r.status_code != 200:
        pytest.fail(f"Login failed {r.status_code}: {r.text[:300]}")
    token = r.json().get("access_token") or r.json().get("token")
    if not token:
        pytest.fail(f"Nessun token in risposta login: {r.text[:300]}")
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


@pytest.fixture(scope="session", autouse=True)
def seed():
    mc = MongoClient(MONGO_URL)
    db = mc[DB_NAME]

    def cleanup():
        for cid in (CID_X, CID_Y, CID_Z):
            db.clients.delete_many({"id": cid})
            db.device_poll_status.delete_many({"client_id": cid})
            db.managed_devices.delete_many({"client_id": cid})
            db.devices.delete_many({"client_id": cid})

    cleanup()
    db.clients.insert_many([
        {"id": CID_X, "name": "TEST_Cliente_X", "status": "active"},
        {"id": CID_Y, "name": "TEST_Cliente_Y", "status": "active"},
        {"id": CID_Z, "name": "TEST_Cliente_Z", "status": "active"},
    ])
    db.device_poll_status.insert_many([
        {"client_id": CID_X, "device_ip": TEST_IP, "device_name": "TEST_SWITCH_X",
         "reachable": True, "sys_descr": "Cisco IOS Software, C2960 Software (C2960-LANBASEK9-M), Version 15.0(2)SE11",
         "cpu_usage": 12, "memory_usage": 33},
        {"client_id": CID_Y, "device_ip": TEST_IP, "device_name": "TEST_FIREWALL_Y",
         "reachable": False, "sys_descr": "FortiGate-100E v7.2.5,build1517,230918 (GA)"},
        {"client_id": CID_X, "device_ip": TEST_IP_UNIQUE, "device_name": "TEST_UNIQUE_X",
         "reachable": True},
    ])
    db.managed_devices.insert_many([
        {"id": "TEST_MD_X", "client_id": CID_X, "ip": TEST_IP, "name": "TEST_SWITCH_X",
         "name_user_locked": True, "device_type": "switch"},
        {"id": "TEST_MD_Y", "client_id": CID_Y, "ip": TEST_IP, "name": "TEST_FIREWALL_Y",
         "name_user_locked": True, "device_type": "firewall"},
    ])
    yield
    cleanup()
    mc.close()


class TestInfoCardMultiTenant:
    """GET /api/devices/by-ip/{ip}/info-card?client_id="""

    def test_info_card_scoped_client_x(self, client):
        r = client.get(f"{BASE_URL}/api/devices/by-ip/{TEST_IP}/info-card",
                       params={"client_id": CID_X}, timeout=30)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        assert d["client"]["id"] == CID_X
        assert d["client"]["name"] == "TEST_Cliente_X"
        assert d["identity"]["hostname"] == "TEST_SWITCH_X"
        assert d["identity"]["device_type"] == "switch"
        assert d["identity"]["vendor"] == "Cisco"
        assert d["status"]["reachable"] is True
        assert "TEST_FIREWALL_Y" not in r.text

    def test_info_card_scoped_client_y(self, client):
        r = client.get(f"{BASE_URL}/api/devices/by-ip/{TEST_IP}/info-card",
                       params={"client_id": CID_Y}, timeout=30)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        assert d["client"]["id"] == CID_Y
        assert d["client"]["name"] == "TEST_Cliente_Y"
        assert d["identity"]["hostname"] == "TEST_FIREWALL_Y"
        assert d["identity"]["device_type"] == "firewall"
        assert d["identity"]["vendor"] == "Fortinet"
        assert d["status"]["reachable"] is False
        assert "TEST_SWITCH_X" not in r.text

    def test_info_card_no_collision(self, client):
        r = client.get(f"{BASE_URL}/api/devices/by-ip/{TEST_IP_UNIQUE}/info-card",
                       params={"client_id": CID_X}, timeout=30)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        assert d["client"]["id"] == CID_X
        assert d["identity"]["hostname"] == "TEST_UNIQUE_X"
        assert d["device_ip"] == TEST_IP_UNIQUE

    def test_info_card_404_wrong_client(self, client):
        r = client.get(f"{BASE_URL}/api/devices/by-ip/{TEST_IP}/info-card",
                       params={"client_id": CID_Z}, timeout=30)
        assert r.status_code == 404, f"attesa 404, ricevuto {r.status_code}: {r.text[:400]}"

    def test_info_card_404_ip_unique_wrong_client(self, client):
        r = client.get(f"{BASE_URL}/api/devices/by-ip/{TEST_IP_UNIQUE}/info-card",
                       params={"client_id": CID_Y}, timeout=30)
        assert r.status_code == 404, f"attesa 404, ricevuto {r.status_code}: {r.text[:400]}"

    def test_info_card_backward_compat_no_client_id(self, client):
        """Retrocompatibilita': senza client_id ritorna 200 (scope non garantito)."""
        r = client.get(f"{BASE_URL}/api/devices/by-ip/{TEST_IP}/info-card", timeout=30)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        assert d["device_ip"] == TEST_IP
        assert d["identity"]["hostname"] in ("TEST_SWITCH_X", "TEST_FIREWALL_Y")

    def test_info_card_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/devices/by-ip/{TEST_IP}/info-card",
                         params={"client_id": CID_X}, timeout=30)
        assert r.status_code in (401, 403), r.status_code

    def test_info_card_no_mongo_objectid(self, client):
        r = client.get(f"{BASE_URL}/api/devices/by-ip/{TEST_IP}/info-card",
                       params={"client_id": CID_X}, timeout=30)
        assert r.status_code == 200
        assert '"_id"' not in r.text


class TestDevicesListScoped:
    """GET /api/devices?client_id="""

    def test_devices_list_scoped_x(self, client):
        r = client.get(f"{BASE_URL}/api/devices", params={"client_id": CID_X}, timeout=60)
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        items = data if isinstance(data, list) else data.get("devices", [])
        assert items, "lista vuota per CID_X"
        for it in items:
            assert it.get("client_id") in (CID_X, None), it
        ips = {it.get("ip_address") or it.get("ip") for it in items}
        assert TEST_IP in ips
        names = {it.get("name") for it in items}
        assert "TEST_FIREWALL_Y" not in names

    def test_devices_list_scoped_y(self, client):
        r = client.get(f"{BASE_URL}/api/devices", params={"client_id": CID_Y}, timeout=60)
        assert r.status_code == 200, r.text[:400]
        data = r.json()
        items = data if isinstance(data, list) else data.get("devices", [])
        names = {it.get("name") for it in items}
        assert "TEST_SWITCH_X" not in names
        assert "TEST_UNIQUE_X" not in names
        for it in items:
            assert it.get("client_id") in (CID_Y, None), it
