"""Tests for Datto-as-evidence fix in GET /api/devices.

Verifies that the Datto RMM agent 'online' status (fresh heartbeat) promotes a
managed device to status='online' even when ICMP is blocked and no L2 evidence
exists (fix for false-red on Windows/Hyper-V servers).
"""
import os
import uuid
import asyncio
from datetime import datetime, timezone, timedelta

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

ADMIN_EMAIL = "info@86bit.it"
ADMIN_PASS = "Ariel17051986@!@86"


# ---------- Helpers ----------

def _login():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
                      timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok, f"no token in response: {r.json()}"
    return tok


def _now_iso(offset_minutes=0):
    return (datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)).isoformat()


@pytest.fixture(scope="module")
def token():
    return _login()


@pytest.fixture(scope="module")
def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def db():
    loop = asyncio.new_event_loop()
    client = AsyncIOMotorClient(MONGO_URL)
    d = client[DB_NAME]
    yield d, loop
    client.close()
    loop.close()


def _run(loop, coro):
    return loop.run_until_complete(coro)


# ---------- Seed / cleanup helpers ----------

TEMP_TAG = "TEST_datto_ev_"


async def _seed(db, client_id, md_id, ip, mac, uid,
                datto_online=True, datto_fresh_min=1, include_datto=True):
    await db.clients.insert_one({
        "id": client_id,
        "name": f"{TEMP_TAG}{client_id[:8]}",
        "status": "active",
        "created_at": _now_iso(),
    })
    # managed device — field 'ip' (not ip_address). No datto_uid unless testing uid match.
    md = {
        "id": md_id,
        "client_id": client_id,
        "ip": ip,
        "mac": mac,
        "name": f"{TEMP_TAG}srv",
        "hostname": f"{TEMP_TAG}srv",
        "device_type": "server",
        "source": "manual",
        "created_at": _now_iso(),
    }
    if uid:
        md["datto_uid"] = uid
    await db.managed_devices.insert_one(md)
    # device_poll_status with reachable=false → ICMP blocked
    await db.device_poll_status.insert_one({
        "client_id": client_id,
        "device_ip": ip,
        "reachable": False,
        "ping_reachable": False,
        "last_ping_at": _now_iso(),
        "last_poll_at": _now_iso(),
        "method": "icmp",
        "source": "connector-master",
    })
    if include_datto:
        await db.datto_devices.insert_one({
            "client_id": client_id,
            "uid": uid or f"uid-{md_id}",
            "hostname": f"{TEMP_TAG}srv",
            "online": bool(datto_online),
            "datto_last_seen": _now_iso(-abs(datto_fresh_min)),
            "ip": ip,
            "ip_list": [ip],
            "mac": mac,
            "mac_list": [mac],
        })


async def _cleanup(db, client_id):
    await db.clients.delete_many({"id": client_id})
    await db.managed_devices.delete_many({"client_id": client_id})
    await db.device_poll_status.delete_many({"client_id": client_id})
    await db.discovered_endpoints.delete_many({"client_id": client_id})
    await db.datto_devices.delete_many({"client_id": client_id})
    await db.devices.delete_many({"client_id": client_id})


def _get_devices(headers, client_id):
    r = requests.get(f"{BASE_URL}/api/devices",
                     params={"client_id": client_id},
                     headers=headers, timeout=30)
    assert r.status_code == 200, f"GET /api/devices failed: {r.status_code} {r.text}"
    return r.json()


def _find(devices, ip):
    for d in devices:
        if d.get("ip_address") == ip:
            return d
    return None


# ---------- Tests ----------

class TestDattoAsEvidence:
    """Datto online → promotes ICMP-blocked device to online."""

    def test_1_datto_online_promotes_offline_to_online_via_uid(self, db, auth_headers):
        d, loop = db
        cid = str(uuid.uuid4())
        mid = str(uuid.uuid4())
        ip = "10.99.16.101"
        mac = "aa:bb:cc:00:00:01"
        uid = f"datto-uid-{uuid.uuid4().hex[:8]}"
        try:
            _run(loop, _seed(d, cid, mid, ip, mac, uid=uid,
                             datto_online=True, datto_fresh_min=1))
            devs = _get_devices(auth_headers, cid)
            found = _find(devs, ip)
            assert found is not None, f"device {ip} not returned"
            assert found["status"] == "online", (
                f"expected online via Datto UID; got {found['status']}"
            )
        finally:
            _run(loop, _cleanup(d, cid))

    def test_2_datto_online_promotes_via_ip_when_no_uid(self, db, auth_headers):
        """IP-only match: managed_device has NO datto_uid, but datto_devices
        has same IP and online → still promoted."""
        d, loop = db
        cid = str(uuid.uuid4())
        mid = str(uuid.uuid4())
        ip = "10.99.16.102"
        mac = "aa:bb:cc:00:00:02"
        try:
            _run(loop, _seed(d, cid, mid, ip, mac, uid=None,
                             datto_online=True, datto_fresh_min=1))
            devs = _get_devices(auth_headers, cid)
            found = _find(devs, ip)
            assert found is not None
            assert found["status"] == "online", (
                f"expected online via Datto IP match; got {found['status']}"
            )
        finally:
            _run(loop, _cleanup(d, cid))

    def test_3_datto_online_promotes_via_mac(self, db, auth_headers):
        """MAC-only match: seed datto_devices with different IP but same MAC.
        Managed device with no datto_uid, IP-mismatch in datto → should still
        promote via MAC lookup."""
        d, loop = db
        cid = str(uuid.uuid4())
        mid = str(uuid.uuid4())
        ip = "10.99.16.103"
        mac = "aa:bb:cc:00:00:03"
        try:
            # Manual seed to force MAC-only match
            _run(loop, d.clients.insert_one({
                "id": cid, "name": f"{TEMP_TAG}{cid[:8]}",
                "status": "active", "created_at": _now_iso(),
            }))
            _run(loop, d.managed_devices.insert_one({
                "id": mid, "client_id": cid, "ip": ip, "mac": mac,
                "name": f"{TEMP_TAG}srv", "device_type": "server",
                "source": "manual", "created_at": _now_iso(),
            }))
            _run(loop, d.device_poll_status.insert_one({
                "client_id": cid, "device_ip": ip, "reachable": False,
                "ping_reachable": False, "last_ping_at": _now_iso(),
                "method": "icmp",
            }))
            # Datto doc: DIFFERENT IP, but same MAC
            _run(loop, d.datto_devices.insert_one({
                "client_id": cid,
                "uid": f"uid-{mid}",
                "hostname": f"{TEMP_TAG}srv",
                "online": True,
                "datto_last_seen": _now_iso(-1),
                "ip": "172.31.1.1",  # different IP
                "ip_list": ["172.31.1.1"],
                "mac": mac,
                "mac_list": [mac],
            }))
            devs = _get_devices(auth_headers, cid)
            found = _find(devs, ip)
            assert found is not None
            assert found["status"] == "online", (
                f"expected online via Datto MAC match; got {found['status']}"
            )
        finally:
            _run(loop, _cleanup(d, cid))

    def test_4_datto_offline_does_not_promote(self, db, auth_headers):
        """Negative case: Datto reports online=False → device stays offline."""
        d, loop = db
        cid = str(uuid.uuid4())
        mid = str(uuid.uuid4())
        ip = "10.99.16.104"
        mac = "aa:bb:cc:00:00:04"
        try:
            _run(loop, _seed(d, cid, mid, ip, mac,
                             uid=f"uid-{mid}",
                             datto_online=False, datto_fresh_min=1))
            devs = _get_devices(auth_headers, cid)
            found = _find(devs, ip)
            assert found is not None
            assert found["status"] == "offline", (
                f"expected offline when Datto online=False; got {found['status']}"
            )
        finally:
            _run(loop, _cleanup(d, cid))

    def test_5_datto_stale_heartbeat_does_not_promote(self, db, auth_headers):
        """Negative case: Datto online=True but datto_last_seen > 30 min old
        → device stays offline (stale heartbeat)."""
        d, loop = db
        cid = str(uuid.uuid4())
        mid = str(uuid.uuid4())
        ip = "10.99.16.105"
        mac = "aa:bb:cc:00:00:05"
        try:
            _run(loop, _seed(d, cid, mid, ip, mac,
                             uid=f"uid-{mid}",
                             datto_online=True, datto_fresh_min=60))
            devs = _get_devices(auth_headers, cid)
            found = _find(devs, ip)
            assert found is not None
            assert found["status"] == "offline", (
                f"expected offline when Datto heartbeat is stale (>30min); "
                f"got {found['status']}"
            )
        finally:
            _run(loop, _cleanup(d, cid))

    def test_6_regression_no_datto_no_l2_stays_offline(self, db, auth_headers):
        """Regression: no ping, no L2, NO datto doc at all → still offline.
        The change must not turn everything green."""
        d, loop = db
        cid = str(uuid.uuid4())
        mid = str(uuid.uuid4())
        ip = "10.99.16.106"
        mac = "aa:bb:cc:00:00:06"
        try:
            _run(loop, _seed(d, cid, mid, ip, mac, uid=None,
                             include_datto=False))
            devs = _get_devices(auth_headers, cid)
            found = _find(devs, ip)
            assert found is not None
            assert found["status"] == "offline", (
                f"expected offline when no Datto/L2/ping; got {found['status']}"
            )
        finally:
            _run(loop, _cleanup(d, cid))

    def test_7_regression_reachable_via_ping_stays_online(self, db, auth_headers):
        """Regression: device that IS reachable via ping still shows online
        (unchanged behavior)."""
        d, loop = db
        cid = str(uuid.uuid4())
        mid = str(uuid.uuid4())
        ip = "10.99.16.107"
        mac = "aa:bb:cc:00:00:07"
        try:
            _run(loop, d.clients.insert_one({
                "id": cid, "name": f"{TEMP_TAG}{cid[:8]}",
                "status": "active", "created_at": _now_iso(),
            }))
            _run(loop, d.managed_devices.insert_one({
                "id": mid, "client_id": cid, "ip": ip, "mac": mac,
                "name": f"{TEMP_TAG}srv", "device_type": "server",
                "source": "manual", "created_at": _now_iso(),
            }))
            _run(loop, d.device_poll_status.insert_one({
                "client_id": cid, "device_ip": ip,
                "reachable": True, "ping_reachable": True,
                "last_ping_at": _now_iso(), "last_poll_at": _now_iso(),
                "method": "icmp",
            }))
            devs = _get_devices(auth_headers, cid)
            found = _find(devs, ip)
            assert found is not None
            assert found["status"] == "online", (
                f"expected online via ping; got {found['status']}"
            )
        finally:
            _run(loop, _cleanup(d, cid))
