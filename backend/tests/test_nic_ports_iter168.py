# NIC ports endpoint (GET /api/devices/by-ip/{ip}/nic-ports) regression tests
import os
import uuid
import pytest
import pyotp
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
CID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"
IP = "10.250.99.99"
IP_EP = "10.250.99.98"
TAG = "TEST_nicports_" + uuid.uuid4().hex[:6]


@pytest.fixture(scope="module")
def db():
    c = MongoClient(os.environ["MONGO_URL"])
    return c[os.environ["DB_NAME"]]


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "info@86bit.it", "password": "Ariel17051986@!@86"})
    assert r.status_code == 200, r.text
    d = r.json()
    if d.get("requires_2fa"):
        r = requests.post(f"{BASE_URL}/api/auth/verify-2fa", json={"code": pyotp.TOTP("NMHDJNO53WLTOSREUXWERE6FDH5TAKC3").now()},
                          headers={"Authorization": f"Bearer {d['token']}"})
        assert r.status_code == 200, r.text
        d = r.json()
    return d["token"]


@pytest.fixture(scope="module", autouse=True)
def seed(db):
    ids = [TAG + "_md1", TAG + "_md2"]
    db.managed_devices.insert_many([
        {"id": ids[0], "name": TAG, "client_id": CID, "ip": IP, "mac": "90:09:d0:79:ad:9d",
         "nic_macs": ["90:09:d0:79:ad:9d", "90:09:d0:79:ad:9e"], "nic_active_mac": "90:09:d0:79:ad:9d",
         "nic_seen": {"90:09:d0:79:ad:9d": "2026-01-10T10:00:00+00:00", "90:09:d0:79:ad:9e": "2026-01-09T10:00:00+00:00"}},
        {"id": ids[1], "name": TAG, "client_id": CID, "ip": IP_EP, "mac": None},
    ])
    ep_ids = [TAG + "_ep1", TAG + "_ep2"]
    db.discovered_endpoints.insert_many([
        {"id": ep_ids[0], "client_id": CID, "ip": IP_EP, "mac": "AA:BB:CC:00:00:01", "last_seen_at": "2026-01-10T09:00:00+00:00", "hostname": TAG},
        {"id": ep_ids[1], "client_id": CID, "ip": IP_EP, "mac": "aa-bb-cc-00-00-02", "last_seen_at": "2026-01-10T11:00:00+00:00", "hostname": TAG},
    ])
    yield
    db.managed_devices.delete_many({"id": {"$in": ids}})
    db.discovered_endpoints.delete_many({"id": {"$in": ep_ids}})


def _get(token, ip, cid=CID):
    return requests.get(f"{BASE_URL}/api/devices/by-ip/{ip}/nic-ports", params={"client_id": cid} if cid else {},
                        headers={"Authorization": f"Bearer {token}"})


def test_seeded_two_ports_active_9d(token):
    r = _get(token, IP)
    assert r.status_code == 200, r.text
    d = r.json()
    macs = [p["mac"] for p in d["ports"]]
    assert macs == ["90:09:d0:79:ad:9d", "90:09:d0:79:ad:9e"]
    assert d["active_mac"] == "90:09:d0:79:ad:9d"
    act = {p["mac"]: p["active"] for p in d["ports"]}
    assert act["90:09:d0:79:ad:9d"] is True and act["90:09:d0:79:ad:9e"] is False
    for p in d["ports"]:
        for k in ("mac", "active", "last_seen", "switch_ip", "switch_name", "port", "port_name"):
            assert k in p
    assert d["ports"][0]["last_seen"].startswith("2026-01-10")


def test_discovered_endpoints_macs(token):
    r = _get(token, IP_EP)
    assert r.status_code == 200, r.text
    d = r.json()
    macs = [p["mac"] for p in d["ports"]]
    print(d)
    assert len(macs) == 2
    assert d["active_mac"] == macs[[p["active"] for p in d["ports"]].index(True)]
    # most recent last_seen should be active
    assert d["active_mac"].replace("-", ":").lower() == "aa:bb:cc:00:00:02"


def test_unknown_ip_empty(token):
    r = _get(token, "10.254.254.254")
    assert r.status_code == 200
    assert r.json()["ports"] == []


def test_unknown_ip_no_client(token):
    r = _get(token, "10.254.254.253", cid=None)
    assert r.status_code == 200
    assert r.json()["ports"] == []


def test_requires_auth():
    r = requests.get(f"{BASE_URL}/api/devices/by-ip/{IP}/nic-ports", params={"client_id": CID})
    assert r.status_code in (401, 403)
