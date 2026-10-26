# Multi-device port (iter 165): GET /api/devices/{ip}/switch-ports - prev_device suppression + multi-device payload
import os
import time
import asyncio
from datetime import datetime, timezone, timedelta
import pytest
import pyotp
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
CID = "TEST_MULTI165"
SW = "10.165.0.1"
EMAIL, PWD = "info@86bit.it", "Ariel17051986@!@86"
TOTP = "NMHDJNO53WLTOSREUXWERE6FDH5TAKC3"
NOW = datetime.now(timezone.utc)
ISO = NOW.isoformat()
OLD = (NOW - timedelta(days=20)).isoformat()
CHG = (NOW - timedelta(hours=3)).isoformat()
DATI, DC, CL = "00:15:5D:60:06:00", "00:15:5D:60:06:01", "00:15:5D:60:06:02"
HOST, HV1, HV2 = "AA:BB:CC:65:20:01", "00:15:5D:65:20:02", "00:15:5D:65:20:03"
D30A, D30B = "AA:BB:CC:65:30:01", "AA:BB:CC:65:30:02"
AP, A40B, A40C = "AA:BB:CC:65:40:01", "AA:BB:CC:65:40:02", "AA:BB:CC:65:40:03"


def _db():
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return c, c[os.environ["DB_NAME"]]


def _port(idx):
    return {"client_id": CID, "local_ip": SW, "idx": idx, "name": f"GigabitEthernet1/0/{idx}", "oper": 1, "admin": 1,
            "speed_mbps": 1000, "updated_at": ISO}


def _ep(port, mac, ip="", **kw):
    return {"client_id": CID, "switch_ip": SW, "port": port, "mac": mac, "ip": ip, "source": "agent_fdb", "vlan": 1,
            "last_seen_at": ISO, "first_seen_at": OLD, **kw}


def _mem(idx, prev, last, port_devices=None):
    return {"client_id": CID, "local_ip": SW, "idx": idx, "name": f"GigabitEthernet1/0/{idx}", "first_seen": OLD,
            "samples": 500, "up_samples": 480, "updated_at": ISO, "prev_device": prev, "device_changed_at": CHG,
            "last_device": last, "port_devices": port_devices or []}


async def _clean(db=None):
    own = db is None
    if own:
        c, db = _db()
    for col in ("switch_ports", "managed_devices", "discovered_endpoints", "alerts", "port_memory", "lldp_neighbors"):
        await db[col].delete_many({"client_id": CID})
    if own:
        c.close()


async def _seed():
    c, db = _db()
    await _clean(db)
    await db.switch_ports.insert_many([_port(i) for i in (52, 10, 20, 30, 40)])
    await db.managed_devices.insert_many([
        {"id": "TEST_m165_sw", "client_id": CID, "ip": SW, "name": "TEST_SW165", "device_name": "TEST_SW165", "device_type": "switch"},
        {"id": "TEST_m165_host", "client_id": CID, "ip": "10.165.0.20", "name": "TEST_HV165", "device_name": "TEST_HV165",
         "device_type": "server", "virtualization": "physical"},
    ])
    await db.discovered_endpoints.insert_many([
        # port 52: 3 Hyper-V VMs, no host, SRVDC via datto
        _ep(52, DATI, "192.168.1.6", hostname="SRVDATI"),
        _ep(52, DC, "192.168.1.5", datto_name="SRVDC"),
        _ep(52, CL, "192.168.1.54", hostname="CLIENT01"),
        # port 10: single device
        _ep(10, "AA:BB:CC:65:10:01", "10.165.0.50", hostname="pc-office"),
        # port 20: physical host + 2 VMs
        _ep(20, HOST, "10.165.0.20", is_managed=True),
        _ep(20, HV1, "10.165.0.21", hostname="VM-A"),
        _ep(20, HV2, "10.165.0.22", hostname="VM-B"),
        # port 30: dumb switch with 2 PCs (no VM)
        _ep(30, D30A, "10.165.0.31", hostname="PC-A"),
        _ep(30, D30B, "10.165.0.32", hostname="PC-B"),
        # port 40: LLDP AP with clients behind it
        _ep(40, AP, "10.165.0.40", hostname="AP-1"),
        _ep(40, A40B, "10.165.0.41", hostname="phone"),
        _ep(40, A40C, "10.165.0.42", hostname="laptop"),
    ])
    await db.lldp_neighbors.insert_one({"client_id": CID, "local_ip": SW, "local_port_desc": "GigabitEthernet1/0/40",
                                         "local_port_id": "GigabitEthernet1/0/40", "remote_sys_name": "TEST_AP165",
                                         "remote_chassis_id": AP, "remote_port_id": "eth0", "remote_ip": "10.165.0.40",
                                         "updated_at": ISO})
    await db.port_memory.insert_many([
        # prev still attached -> suppressed
        _mem(52, {"mac": DATI, "ip": "192.168.1.6", "name": "SRVDATI"}, {"mac": CL, "ip": "192.168.1.54", "name": "CLIENT01", "seen_at": ISO},
             [{"mac": DATI, "first_seen": OLD, "last_seen": ISO}, {"mac": DC, "first_seen": OLD, "last_seen": ISO},
              {"mac": CL, "first_seen": CHG, "last_seen": ISO}]),
        # prev gone -> real change kept
        _mem(30, {"mac": "AA:BB:CC:65:30:99", "ip": "10.165.0.39", "name": "OLDPC"}, {"mac": D30A, "ip": "10.165.0.31", "name": "PC-A", "seen_at": ISO}),
        # single port: prev gone -> kept
        _mem(10, {"mac": "AA:BB:CC:65:10:99", "ip": "10.165.0.59", "name": "OLDPC10"}, {"mac": "AA:BB:CC:65:10:01", "ip": "10.165.0.50", "name": "pc-office", "seen_at": ISO}),
    ])
    c.close()


@pytest.fixture(scope="module")
def ports():
    asyncio.run(_seed())
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": EMAIL, "password": PWD})
    assert r.status_code == 200, r.text
    d = r.json()
    s.headers["Authorization"] = f"Bearer {d['token']}"
    if d.get("requires_2fa"):
        for _ in range(3):
            v = s.post(f"{BASE_URL}/api/auth/verify-2fa", json={"code": pyotp.TOTP(TOTP).now()})
            if v.status_code == 200:
                break
            time.sleep(31)
        assert v.status_code == 200, v.text
        s.headers["Authorization"] = f"Bearer {v.json()['token']}"
    r = s.get(f"{BASE_URL}/api/devices/{SW}/switch-ports", params={"client_id": CID})
    assert r.status_code == 200, r.text
    yield {p["idx"]: p for p in r.json()["ports"]}
    if not os.environ.get("KEEP_SEED"):
        asyncio.run(_clean())


def test_p52_multi_payload(ports):
    p = ports[52]
    assert p["attached_count"] == 3
    assert {a["mac"] for a in p["attached"]} == {DATI, DC, CL}
    assert p["vm_host"] and p["vm_host"]["kind"] == "Hyper-V"
    assert p["vm_host"]["host_mac"] == ""
    assert any(a["source"] == "datto_rmm" and a["name"] == "SRVDC" for a in p["attached"])
    assert len(p.get("port_devices") or []) == 3


def test_p52_prev_device_suppressed(ports):
    hb = ports[52]["habit"]
    assert hb is not None
    assert "prev_device" not in hb, hb
    assert "device_changed_at" not in hb, hb


def test_p30_prev_device_kept_when_gone(ports):
    hb = ports[30]["habit"]
    assert hb["prev_device"]["mac"] == "AA:BB:CC:65:30:99"
    assert hb.get("device_changed_at")
    assert ports[30]["vm_host"] is None
    assert ports[30]["attached_count"] == 2


def test_p10_single_prev_kept(ports):
    p = ports[10]
    assert p["attached_count"] == 1
    assert p["habit"]["prev_device"]["mac"] == "AA:BB:CC:65:10:99"


def test_p20_host_detected(ports):
    vh = ports[20]["vm_host"]
    assert vh["host_mac"] == HOST
    assert {v["mac"] for v in vh["vms"]} == {HV1, HV2}


def test_p40_lldp_neighbor(ports):
    p = ports[40]
    assert p["neighbor"]["match_source"] == "lldp"
    assert p["attached_count"] == 3
    assert p["vm_host"] is None
