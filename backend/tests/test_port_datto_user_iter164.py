# Datto user on switch port map (iter 164): GET /api/devices/{ip}/switch-ports datto_user enrichment
import os
import asyncio
import pytest
import pyotp
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
CID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"
SW = "10.250.250.1"
MAC = "00:15:5D:01:79:0D"
MAC2 = "00:15:5D:01:72:02"  # secondary mac in mac_list
UNK = "AA:BB:CC:00:11:22"
TAG = "TEST_iter164"
EXPECTED_USER = "SRVDATI86B\\Administrator"


def _db():
    return AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


async def _seed():
    db = _db()
    await _cleanup_async()
    ports = []
    for idx, oper in [(1, 1), (2, 1), (3, 1), (4, 2), (5, 1)]:
        ports.append({"client_id": CID, "local_ip": SW, "idx": idx, "name": f"GigabitEthernet1/0/{idx}",
                      "oper": oper, "admin": 1, "speed_mbps": 1000, "test_tag": TAG,
                      "updated_at": "2026-01-10T10:00:00+00:00"})
    await db.switch_ports.insert_many(ports)
    eps = [
        # port 1: datto-matched PC (by mac)
        {"mac": MAC, "ip": "10.10.1.10", "port": 1, "datto_name": "SRVDATI86B"},
        # port 2: one datto (secondary mac, matched by mac_list) + one unknown device
        {"mac": MAC2, "ip": "", "port": 2},
        {"mac": UNK, "ip": "", "port": 2},
        # port 3: only unknown
        {"mac": "AA:BB:CC:00:11:33", "ip": "", "port": 3},
        # port 4: DOWN port with datto mac -> no port datto_user
        {"mac": MAC, "ip": "10.10.1.10", "port": 4},
        # port 5: matched by IP only (mac not in datto)
        {"mac": "AA:BB:CC:00:11:55", "ip": "10.10.1.139", "port": 5},
    ]
    await db.discovered_endpoints.insert_many([{**e, "client_id": CID, "switch_ip": SW, "source": "agent_fdb",
                                                "vlan": 1, "test_tag": TAG,
                                                "updated_at": "2026-01-10T10:00:00+00:00"} for e in eps])


async def _cleanup_async():
    db = _db()
    await db.switch_ports.delete_many({"local_ip": SW, "client_id": CID})
    await db.discovered_endpoints.delete_many({"switch_ip": SW, "client_id": CID})
    await db.port_memory.delete_many({"local_ip": SW, "client_id": CID})


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


@pytest.fixture(scope="module")
def ports(token):
    asyncio.run(_seed())
    r = requests.get(f"{BASE_URL}/api/devices/{SW}/switch-ports", params={"client_id": CID},
                     headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    yield {p["idx"]: p for p in r.json()["ports"]}
    if not os.environ.get("KEEP_SEED"):
        asyncio.run(_cleanup_async())


def test_port1_datto_mac_match(ports):
    p = ports[1]
    assert p["neighbor"]["match_source"] == "datto_rmm"
    u = p.get("datto_user")
    assert u and u["user"] == EXPECTED_USER
    assert u["online"] is True
    assert isinstance(u["last_seen"], str) and u["last_seen"]
    assert p["attached"][0]["datto_user"] == EXPECTED_USER


def test_port2_single_attached_fallback(ports):
    p = ports[2]
    users = {a["mac"]: a.get("datto_user") for a in p["attached"]}
    assert users[MAC2] == EXPECTED_USER
    assert users[UNK] is None
    assert p.get("datto_user", {}).get("user") == EXPECTED_USER


def test_port3_no_user(ports):
    assert not ports[3].get("datto_user")


def test_port4_down_no_user(ports):
    assert not ports[4].get("datto_user")


def test_port5_ip_match(ports):
    p = ports[5]
    assert p["attached"][0].get("datto_user") == EXPECTED_USER
    assert p.get("datto_user", {}).get("user") == EXPECTED_USER


def test_other_client_no_leak(token):
    r = requests.get(f"{BASE_URL}/api/devices/{SW}/switch-ports", params={"client_id": "TEST_other_client"},
                     headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["ports"] == []


def test_unauth():
    r = requests.get(f"{BASE_URL}/api/devices/{SW}/switch-ports", params={"client_id": CID})
    assert r.status_code in (401, 403)
