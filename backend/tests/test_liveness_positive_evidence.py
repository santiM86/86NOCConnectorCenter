"""
Test coerenza vitalità SRVDC tra TV dashboard, Overview clients e Devices.
Bug fix: liveness_resolver.PositiveEvidence applicato in tv_dashboard/overview/alert_hygiene
per applicare le stesse evidenze positive (Datto RMM, Hyper-V) usate da /api/devices.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
import uuid

import pyotp
import pytest
import requests

sys.path.insert(0, "/app/backend")

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN_EMAIL = "info@86bit.it"
ADMIN_PASSWORD = "Ariel17051986@!@86"
TOTP_SECRET = "NMHDJNO53WLTOSREUXWERE6FDH5TAKC3"

CLIENT_ID = f"TEST_liveness_{uuid.uuid4().hex[:8]}"
CLIENT_NAME = f"TEST_LIVENESS_CLIENT_{CLIENT_ID[-8:]}"
DEVICE_IP = "192.168.44.5"
DEVICE_HOSTNAME = "SRVDC"


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _now():
    return datetime.now(timezone.utc)


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200, r.text
    tok = r.json().get("token")
    code = pyotp.TOTP(TOTP_SECRET).now()
    r2 = requests.post(f"{BASE_URL}/api/auth/verify-2fa", json={"code": code}, headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r2.status_code == 200, r2.text
    return r2.json()["token"]


@pytest.fixture(scope="module")
def db():
    from database import db as _db
    return _db


@pytest.fixture(scope="module", autouse=True)
def setup_and_cleanup(db):
    async def _setup():
        now = _now()
        three_days_ago = now - timedelta(days=3)
        await db.clients.insert_one({"id": CLIENT_ID, "name": CLIENT_NAME})
        await db.managed_agents.insert_one({
            "client_id": CLIENT_ID,
            "last_heartbeat_at": now.isoformat(),
            "connected": True,
        })
        await db.managed_devices.insert_one({
            "client_id": CLIENT_ID,
            "ip": DEVICE_IP,
            "hostname": DEVICE_HOSTNAME,
            "name": DEVICE_HOSTNAME,
            "device_type": "server",
            "is_vital": True,
        })
        await db.device_poll_status.insert_one({
            "client_id": CLIENT_ID,
            "device_ip": DEVICE_IP,
            "reachable": False,
            "consecutive_failures": 50,
            "unreachable_since": three_days_ago.isoformat(),
            "last_reachable_at": three_days_ago.isoformat(),
            "updated_at": now.isoformat(),
            "last_poll": now.isoformat(),
        })
    async def _cleanup():
        await db.clients.delete_many({"id": CLIENT_ID})
        await db.managed_agents.delete_many({"client_id": CLIENT_ID})
        await db.managed_devices.delete_many({"client_id": CLIENT_ID})
        await db.device_poll_status.delete_many({"client_id": CLIENT_ID})
        await db.hyperv_snapshots.delete_many({"client_id": CLIENT_ID})
        await db.datto_devices.delete_many({"client_id": CLIENT_ID})
        await db.alerts.delete_many({"client_id": CLIENT_ID})

    asyncio.get_event_loop().run_until_complete(_setup())
    yield
    asyncio.get_event_loop().run_until_complete(_cleanup())


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _compute_tv():
    from routes import tv_dashboard as tv
    # bypass cache
    tv._TV_CACHE.clear() if hasattr(tv, "_TV_CACHE") else None
    return _run(tv._compute_tv_dashboard())


def _compute_overview():
    from routes import overview as ov
    return _run(ov._compute_clients_overview())


def _tv_has_srvdc_offline(tv_data):
    offline = tv_data.get("offline_devices") or []
    for d in offline:
        if d.get("client_id") == CLIENT_ID and (d.get("ip") == DEVICE_IP or (d.get("hostname") or "").lower().startswith("srvdc")):
            return True
    return False


def _overview_client(ov_data):
    for c in (ov_data.get("clients") or []):
        if c.get("id") == CLIENT_ID or c.get("client_id") == CLIENT_ID:
            return c
    return None


def _srvdc_status_in_detail(client_entry):
    """Cerca SRVDC nella detail.vital_list del client."""
    detail = client_entry.get("detail") or {}
    for v in (detail.get("vital_list") or []):
        h = (v.get("hostname") or v.get("name") or "").lower()
        if h.startswith("srvdc") or v.get("ip") == DEVICE_IP:
            return v.get("status")
    return None


# ---------- CASO 1: Hyper-V Running ----------
def test_case1_hyperv_running(db, admin_token):
    _run(db.hyperv_snapshots.delete_many({"client_id": CLIENT_ID}))
    _run(db.datto_devices.delete_many({"client_id": CLIENT_ID}))
    _run(db.hyperv_snapshots.insert_one({
        "client_id": CLIENT_ID,
        "hostname": "HVHOST",
        "collected_at": _now_iso(),
        "vms": [{"name": "SRVDC", "state": "Running"}],
    }))

    tv = _compute_tv()
    assert not _tv_has_srvdc_offline(tv), f"CASO1 TV: SRVDC deve NON essere in offline_devices"

    ov = _compute_overview()
    ce = _overview_client(ov)
    assert ce is not None, "Client non trovato in overview"
    devs = ce.get("devices") or {}
    assert devs.get("vital_offline", 0) == 0, f"CASO1 overview vital_offline={devs.get('vital_offline')}"
    status = _srvdc_status_in_detail(ce)
    assert status == "online", f"CASO1 overview SRVDC status={status}"

    # Coerenza con /api/devices
    r = requests.get(f"{BASE_URL}/api/devices", params={"client_id": CLIENT_ID}, headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)
    assert r.status_code == 200, r.text
    devices = r.json() if isinstance(r.json(), list) else r.json().get("devices", [])
    srv = next((d for d in devices if d.get("ip_address") == DEVICE_IP or d.get("ip") == DEVICE_IP), None)
    assert srv is not None, "SRVDC non presente in /api/devices"
    assert srv.get("status") == "online", f"CASO1 /api/devices SRVDC status={srv.get('status')}"


# ---------- CASO 2: Hyper-V Off ----------
def test_case2_hyperv_off(db):
    _run(db.hyperv_snapshots.update_one(
        {"client_id": CLIENT_ID},
        {"$set": {"vms": [{"name": "SRVDC", "state": "Off"}], "collected_at": _now_iso()}},
    ))
    tv = _compute_tv()
    assert not _tv_has_srvdc_offline(tv), "CASO2 TV: SRVDC 'Off' non deve essere in offline_devices"

    ov = _compute_overview()
    ce = _overview_client(ov)
    devs = ce.get("devices") or {}
    # 'off' non deve essere contato come offline
    assert devs.get("vital_offline", 0) == 0, f"CASO2 vital_offline={devs.get('vital_offline')}"
    status = _srvdc_status_in_detail(ce)
    assert status == "off", f"CASO2 overview SRVDC status={status} (atteso 'off')"


# ---------- CASO 3: Datto online ----------
def test_case3_datto_online(db, admin_token):
    _run(db.hyperv_snapshots.delete_many({"client_id": CLIENT_ID}))
    _run(db.datto_devices.delete_many({"client_id": CLIENT_ID}))
    _run(db.datto_devices.insert_one({
        "client_id": CLIENT_ID,
        "uid": "dt-1",
        "ip": DEVICE_IP,
        "online": True,
        "datto_last_seen": _now_iso(),
    }))

    tv = _compute_tv()
    assert not _tv_has_srvdc_offline(tv), "CASO3 TV: SRVDC deve essere online tramite Datto"

    ov = _compute_overview()
    ce = _overview_client(ov)
    devs = ce.get("devices") or {}
    assert devs.get("vital_offline", 0) == 0, f"CASO3 vital_offline={devs.get('vital_offline')}"
    status = _srvdc_status_in_detail(ce)
    assert status == "online", f"CASO3 overview SRVDC status={status}"

    r = requests.get(f"{BASE_URL}/api/devices", params={"client_id": CLIENT_ID}, headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)
    assert r.status_code == 200
    devices = r.json() if isinstance(r.json(), list) else r.json().get("devices", [])
    srv = next((d for d in devices if d.get("ip_address") == DEVICE_IP or d.get("ip") == DEVICE_IP), None)
    assert srv and srv.get("status") == "online", f"CASO3 /api/devices SRVDC status={srv and srv.get('status')}"


# ---------- CASO 4: nessuna evidenza positiva -> offline ----------
def test_case4_no_evidence_offline(db):
    _run(db.hyperv_snapshots.delete_many({"client_id": CLIENT_ID}))
    _run(db.datto_devices.delete_many({"client_id": CLIENT_ID}))

    tv = _compute_tv()
    assert _tv_has_srvdc_offline(tv), "CASO4 TV: SRVDC deve essere in offline_devices"

    ov = _compute_overview()
    ce = _overview_client(ov)
    devs = ce.get("devices") or {}
    assert devs.get("vital_offline", 0) >= 1, f"CASO4 vital_offline={devs.get('vital_offline')} (atteso >=1)"
