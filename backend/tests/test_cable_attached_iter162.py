# API test iter162: switch-ports returns port_devices (from port_memory) + attached[].first_seen_at (Cable View "Collegati sotto")
import os, time, asyncio
import pytest, requests, pyotp
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
CID = "TEST_CAB162"
SW = "10.162.0.1"
EMAIL, PWD = "info@86bit.it", "Ariel17051986@!@86"
TOTP = "NMHDJNO53WLTOSREUXWERE6FDH5TAKC3"
NOWDT = datetime.now(timezone.utc)
NOW = NOWDT.isoformat()
HOST_MAC, VM1, VM2 = "AA:BB:CC:00:16:01", "00:15:5D:60:06:01", "00:15:5D:60:06:00"
PC1, PC2 = "AA:BB:CC:00:20:01", "AA:BB:CC:00:20:02"
HOST_FS = "2025-11-03T09:15:00+00:00"   # port_memory first_seen host
VM1_FS = "2025-12-01T10:00:00+00:00"    # port_memory first_seen VM1
VM2_EP_FS = "2025-12-20T08:30:00+00:00"  # only endpoint first_seen_at for VM2 (fallback)
PC1_FS = "2025-10-10T07:00:00+00:00"


def _db():
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return c, c[os.environ["DB_NAME"]]


def _pm(idx, devs):
    return {"client_id": CID, "local_ip": SW, "idx": idx, "name": f"GigabitEthernet1/0/{idx}",
            "first_seen": (NOWDT - timedelta(days=40)).isoformat(), "samples": 100, "up_samples": 100,
            "last_oper_up": True, "last_up_at": NOW, "updated_at": NOW, "port_devices": devs}


async def _seed():
    c, db = _db()
    await _clean(db)
    await db.switch_ports.insert_many([
        {"client_id": CID, "local_ip": SW, "idx": i, "name": f"GigabitEthernet1/0/{i}", "oper": 1, "admin": 1, "speed_mbps": 1000, "updated_at": NOW}
        for i in (52, 20)])
    await db.managed_devices.insert_many([
        {"id": "TEST_cab162_sw", "client_id": CID, "ip": SW, "name": "TEST_SW162", "device_name": "TEST_SW162", "device_type": "switch"},
        {"id": "TEST_cab162_host", "client_id": CID, "ip": "10.162.0.10", "name": "TEST_HYPERV02", "device_name": "TEST_HYPERV02", "device_type": "server", "virtualization": "physical"},
        {"id": "TEST_cab162_dc", "client_id": CID, "ip": "10.162.0.11", "name": "SRVDC", "device_name": "SRVDC", "device_type": "server", "virtualization": "hyperv"},
        {"id": "TEST_cab162_dati", "client_id": CID, "ip": "10.162.0.12", "name": "SRVDATI", "device_name": "SRVDATI", "device_type": "server", "virtualization": "hyperv"},
    ])
    await db.discovered_endpoints.insert_many([
        {"client_id": CID, "switch_ip": SW, "port": 52, "mac": HOST_MAC, "ip": "10.162.0.10", "is_managed": True, "last_seen_at": NOW, "first_seen_at": "2025-11-05T00:00:00+00:00"},
        {"client_id": CID, "switch_ip": SW, "port": 52, "mac": VM1, "ip": "10.162.0.11", "is_managed": True, "last_seen_at": NOW},
        {"client_id": CID, "switch_ip": SW, "port": 52, "mac": VM2, "ip": "10.162.0.12", "is_managed": True, "last_seen_at": NOW, "first_seen_at": VM2_EP_FS},
        {"client_id": CID, "switch_ip": SW, "port": 20, "mac": PC1, "ip": "10.162.0.50", "hostname": "pc-uno", "last_seen_at": NOW},
        {"client_id": CID, "switch_ip": SW, "port": 20, "mac": PC2, "ip": "10.162.0.51", "hostname": "pc-due", "last_seen_at": NOW},
    ])
    await db.port_memory.insert_many([
        _pm(52, [{"mac": HOST_MAC, "first_seen": HOST_FS, "last_seen": NOW}, {"mac": VM1, "first_seen": VM1_FS, "last_seen": NOW}]),
        _pm(20, [{"mac": PC1, "first_seen": PC1_FS, "last_seen": NOW}]),
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
    s.headers["Authorization"] = f"Bearer {r.json().get('token')}"
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


@pytest.fixture(scope="module")
def ports(client):
    r = client.get(f"{BASE_URL}/api/devices/{SW}/switch-ports", params={"client_id": CID})
    assert r.status_code == 200, r.text
    return {p["idx"]: p for p in r.json()["ports"]}


def test_port_devices_on_vm_port(ports):
    p = ports[52]
    pd = {d["mac"]: d for d in p["port_devices"]}
    assert pd[HOST_MAC]["first_seen"] == HOST_FS
    assert pd[VM1]["first_seen"] == VM1_FS
    assert set(pd[HOST_MAC]) == {"mac", "first_seen", "last_seen"}


def test_attached_first_seen_at(ports):
    att = {a["mac"]: a for a in ports[52]["attached"]}
    assert att[VM2]["first_seen_at"] == VM2_EP_FS
    assert att[VM1]["first_seen_at"] is None
    assert "first_seen_at" in att[HOST_MAC]


def test_vm_host_still_present(ports):
    vh = ports[52]["vm_host"]
    assert vh and vh["host_name"] == "TEST_HYPERV02" and vh["host_mac"] == HOST_MAC
    assert {v["mac"] for v in vh["vms"]} == {VM1, VM2}


def test_multi_device_port(ports):
    p = ports[20]
    assert p["vm_host"] is None
    assert {a["mac"] for a in p["attached"]} == {PC1, PC2}
    assert [d["mac"] for d in p["port_devices"]] == [PC1]


def test_port_without_memory_has_no_port_devices(client):
    r = client.get(f"{BASE_URL}/api/devices/{SW}/switch-ports", params={"client_id": "OTHER_TENANT_X"})
    assert r.status_code == 200 and r.json()["ports"] == []
