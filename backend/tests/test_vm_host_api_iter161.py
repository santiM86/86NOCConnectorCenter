# API test: GET /api/devices/{switch_ip}/switch-ports vm_host field (iter161)
import os, time, asyncio
import pytest, requests, pyotp
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
CID = "TEST_VM161"
SW = "10.161.0.1"
EMAIL, PWD = "info@86bit.it", "Ariel17051986@!@86"
TOTP = "NMHDJNO53WLTOSREUXWERE6FDH5TAKC3"
NOW = datetime.now(timezone.utc).isoformat()
HOST_MAC, VM1, VM2 = "AA:BB:CC:00:16:01", "00:15:5D:60:06:01", "00:15:5D:60:06:00"


def _db():
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return c, c[os.environ["DB_NAME"]]


async def _seed():
    c, db = _db()
    await _clean(db)
    await db.switch_ports.insert_many([
        {"client_id": CID, "local_ip": SW, "idx": 52, "name": "GigabitEthernet1/0/52", "oper": 1, "admin": 1, "speed_mbps": 1000, "updated_at": NOW},
        {"client_id": CID, "local_ip": SW, "idx": 10, "name": "GigabitEthernet1/0/10", "oper": 1, "admin": 1, "speed_mbps": 1000, "updated_at": NOW},
    ])
    await db.managed_devices.insert_many([
        {"id": "TEST_vm161_sw", "client_id": CID, "ip": SW, "name": "TEST_SW161", "device_name": "TEST_SW161", "device_type": "switch"},
        {"id": "TEST_vm161_host", "client_id": CID, "ip": "10.161.0.10", "name": "TEST_HYPERV01", "device_name": "TEST_HYPERV01", "device_type": "server", "virtualization": "physical"},
        {"id": "TEST_vm161_dc", "client_id": CID, "ip": "10.161.0.11", "name": "SRVDC", "device_name": "SRVDC", "device_type": "server", "virtualization": "hyperv"},
        {"id": "TEST_vm161_dati", "client_id": CID, "ip": "10.161.0.12", "name": "SRVDATI", "device_name": "SRVDATI", "device_type": "server", "virtualization": "hyperv"},
    ])
    await db.discovered_endpoints.insert_many([
        {"client_id": CID, "switch_ip": SW, "port": 52, "mac": HOST_MAC, "ip": "10.161.0.10", "is_managed": True, "last_seen_at": NOW},
        {"client_id": CID, "switch_ip": SW, "port": 52, "mac": VM1, "ip": "10.161.0.11", "is_managed": True, "last_seen_at": NOW},
        {"client_id": CID, "switch_ip": SW, "port": 52, "mac": VM2, "ip": "10.161.0.12", "is_managed": True, "last_seen_at": NOW},
        {"client_id": CID, "switch_ip": SW, "port": 10, "mac": "AA:BB:CC:00:10:01", "ip": "10.161.0.50", "hostname": "pc-office", "last_seen_at": NOW},
    ])
    c.close()


async def _clean(db=None):
    own = db is None
    if own:
        c, db = _db()
    for col in ("switch_ports", "managed_devices", "discovered_endpoints", "alerts", "port_memory"):
        await db[col].delete_many({"client_id": CID})
    if own:
        c.close()


@pytest.fixture(scope="module")
def client():
    asyncio.run(_seed())
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": EMAIL, "password": PWD})
    assert r.status_code == 200, r.text
    tok = r.json().get("token")
    s.headers["Authorization"] = f"Bearer {tok}"
    if r.json().get("requires_2fa"):
        for _ in range(3):
            v = s.post(f"{BASE_URL}/api/auth/verify-2fa", json={"code": pyotp.TOTP(TOTP).now()})
            if v.status_code == 200:
                break
            time.sleep(31)
        assert v.status_code == 200, v.text
        s.headers["Authorization"] = f"Bearer {v.json()['token']}"
    yield s
    if not os.environ.get("KEEP_SEED"):
        asyncio.run(_clean())


def _ports(client):
    r = client.get(f"{BASE_URL}/api/devices/{SW}/switch-ports", params={"client_id": CID})
    assert r.status_code == 200, r.text
    return {p["idx"]: p for p in r.json()["ports"]}


def test_vm_host_present_on_hyperv_port(client):
    p = _ports(client)[52]
    vh = p["vm_host"]
    assert vh is not None
    assert vh["kind"] == "Hyper-V"
    assert vh["host_name"] == "TEST_HYPERV01"
    assert vh["host_ip"] == "10.161.0.10"
    assert vh["host_mac"] == HOST_MAC
    macs = {v["mac"] for v in vh["vms"]}
    assert macs == {VM1, VM2}
    names = {v["name"] for v in vh["vms"]}
    assert names == {"SRVDC", "SRVDATI"}
    assert p["attached_count"] == 3


def test_vm_host_null_on_normal_port(client):
    p = _ports(client)[10]
    assert p["vm_host"] is None
    assert p["attached_count"] == 1


def test_no_client_scope_leak(client):
    r = client.get(f"{BASE_URL}/api/devices/{SW}/switch-ports", params={"client_id": "OTHER_TENANT_X"})
    assert r.status_code == 200
    assert r.json()["ports"] == []
