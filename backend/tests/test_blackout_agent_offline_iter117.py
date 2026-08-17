"""
ITER 117 — BUG GRAVE BLACKOUT (Gualdi):
se l'agent del cliente e' OFFLINE (nessun heartbeat da >3min), i device NON
possono risultare 'online' da dati agent (ARP/scanner/FDB/poll stantii) ->
devono diventare 'stale' con status_reason 'agent_offline'.

Testa l'ENDPOINT REST GET /api/devices?client_id=... con setup DB controllato.
"""
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyotp
import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")

backend_env = dotenv_values("/app/backend/.env")
MONGO_URL = backend_env.get("MONGO_URL")
DB_NAME = backend_env.get("DB_NAME")

CID_BLACKOUT = "TEST_CID_BLACKOUT_117"
CID_LIVE = "TEST_CID_LIVE_117"
IP_BLACKOUT = "10.77.0.5"
IP_LIVE = "10.88.0.5"


def _iso(dt):
    return dt.isoformat()


@pytest.fixture(scope="module")
def mongo_db():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


@pytest.fixture(scope="module")
def seeded(mongo_db):
    db = mongo_db
    now = datetime.now(timezone.utc)
    old = now - timedelta(minutes=30)

    _cleanup(db)

    db.clients.insert_many([
        {"id": CID_BLACKOUT, "name": "TEST_Blackout Srl", "created_at": _iso(now)},
        {"id": CID_LIVE, "name": "TEST_Live Srl", "created_at": _iso(now)},
    ])
    db.managed_agents.insert_many([
        {"client_id": CID_BLACKOUT, "agent_id": "TEST_blk", "role": "master",
         "hostname": "TEST-BLK-AGENT", "last_heartbeat_at": _iso(old),
         "last_seen_at": _iso(old)},
        {"client_id": CID_LIVE, "agent_id": "TEST_liv", "role": "master",
         "hostname": "TEST-LIV-AGENT", "last_heartbeat_at": _iso(now),
         "last_seen_at": _iso(now)},
    ])
    db.managed_devices.insert_many([
        {"client_id": CID_BLACKOUT, "ip": IP_BLACKOUT, "name": "TEST_BLKPC",
         "device_type": "server", "source": "manual"},
        {"client_id": CID_LIVE, "ip": IP_LIVE, "name": "TEST_LIVPC",
         "device_type": "server", "source": "manual"},
    ])
    db.device_poll_status.insert_many([
        {"client_id": CID_BLACKOUT, "device_ip": IP_BLACKOUT, "reachable": True,
         "method": "ping", "source": "agent_v4", "last_poll": _iso(now),
         "last_ping_at": _iso(now), "last_reachable_at": _iso(now),
         "consecutive_failures": 0},
        {"client_id": CID_LIVE, "device_ip": IP_LIVE, "reachable": True,
         "method": "ping", "source": "agent_v4", "last_poll": _iso(now),
         "last_ping_at": _iso(now), "last_reachable_at": _iso(now),
         "consecutive_failures": 0},
    ])
    yield db
    _cleanup(db)


def _cleanup(db):
    cids = {"$in": [CID_BLACKOUT, CID_LIVE]}
    db.clients.delete_many({"id": cids})
    db.managed_agents.delete_many({"client_id": cids})
    db.managed_devices.delete_many({"client_id": cids})
    db.device_poll_status.delete_many({"client_id": cids})
    db.discovered_endpoints.delete_many({"client_id": cids})
    db.datto_devices.delete_many({"client_id": cids})


@pytest.fixture(scope="module")
def auth_token():
    creds_path = Path("/app/memory/test_credentials.md")
    content = creds_path.read_text(encoding="utf-8")
    email = re.search(r"Email:\s*`([^`]+)`", content).group(1)
    password = re.search(r"Password:\s*`([^`]+)`", content).group(1)
    secret = re.search(r"`([A-Z2-7]{26,})`", content).group(1)

    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    if r.status_code != 200:
        pytest.fail(f"login failed {r.status_code}: {r.text[:300]}")
    data = r.json()
    token = data.get("token")
    if data.get("requires_2fa") or data.get("requires_2fa_setup"):
        code = pyotp.TOTP(secret).now()
        r2 = s.post(f"{BASE_URL}/api/auth/verify-2fa", json={"code": code},
                    headers={"Authorization": f"Bearer {token}"}, timeout=30)
        if r2.status_code != 200:
            pytest.fail(f"verify-2fa failed {r2.status_code}: {r2.text[:300]}")
        token = r2.json().get("token")
    assert token
    return token


def _get_devices(token, cid):
    r = requests.get(f"{BASE_URL}/api/devices", params={"client_id": cid},
                     headers={"Authorization": f"Bearer {token}"}, timeout=60)
    assert r.status_code == 200, f"GET /api/devices {cid} -> {r.status_code}: {r.text[:300]}"
    return r.json()


class TestBlackoutGating:
    """GET /api/devices — gating agent_offline"""

    def test_blackout_device_is_stale_not_online(self, seeded, auth_token):
        devices = _get_devices(auth_token, CID_BLACKOUT)
        target = [d for d in devices if (d.get("ip") or d.get("ip_address")) == IP_BLACKOUT]
        assert target, f"device {IP_BLACKOUT} non trovato: {devices}"
        d = target[0]
        assert d.get("status") != "online", f"FALSO ONLINE durante blackout: {d}"
        assert d.get("status") == "stale", f"status atteso 'stale', ottenuto {d.get('status')}"
        assert d.get("status_reason") == "agent_offline", f"status_reason: {d.get('status_reason')}"

    def test_live_client_device_stays_online(self, seeded, auth_token):
        devices = _get_devices(auth_token, CID_LIVE)
        target = [d for d in devices if (d.get("ip") or d.get("ip_address")) == IP_LIVE]
        assert target, f"device {IP_LIVE} non trovato: {devices}"
        d = target[0]
        assert d.get("status") == "online", f"status atteso 'online', ottenuto {d.get('status')} ({d})"

    def test_no_mongo_objectid_leak(self, seeded, auth_token):
        devices = _get_devices(auth_token, CID_BLACKOUT)
        for d in devices:
            assert "_id" not in d

    def test_datto_confirmed_device_stays_online_during_blackout(self, seeded, auth_token, mongo_db):
        """Eccezione: conferma indipendente da Datto RMM -> resta online."""
        now = datetime.now(timezone.utc)
        mongo_db.datto_devices.insert_one({
            "client_id": CID_BLACKOUT, "uid": "TEST_datto_uid_117", "online": True,
            "ip": IP_BLACKOUT, "datto_last_seen": _iso(now),
        })
        try:
            devices = _get_devices(auth_token, CID_BLACKOUT)
            d = [x for x in devices if (x.get("ip") or x.get("ip_address")) == IP_BLACKOUT][0]
            assert d.get("status") == "online", f"Datto-confirmed device dovrebbe restare online: {d}"
        finally:
            mongo_db.datto_devices.delete_many({"client_id": CID_BLACKOUT})
