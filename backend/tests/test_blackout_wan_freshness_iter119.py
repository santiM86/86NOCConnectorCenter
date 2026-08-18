"""
ITER 119 — BLACKOUT DETECTION quasi-live (fix ricorrente, 5+ occorrenze).

Copre:
  * liveness_resolver.build_wan_down_clients()  — filtro freschezza (BUG#1)
    e logica ALL-targets (BUG#2)
  * liveness_resolver.build_clients_without_online_agent() — soglia 90s
  * liveness_resolver.build_blackout_clients()  — intersezione agent-down & WAN-down
  * liveness_resolver.compute_status()          — ('offline','site_blackout') vs
    ('stale','agent_offline')
  * REST: GET /api/devices?client_id=... e GET /api/overview/clients devono
    derivare lo stesso stato (nessuna discrepanza).

Seed su DB reale (MONGO_URL/DB_NAME) con client_id prefissati TEST_QA_*.
Nessun dato reale (86BIT_Office, GualdiGroup) viene toccato.
"""
import asyncio
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyotp
import pytest
import requests
from dotenv import dotenv_values
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient

sys.path.insert(0, "/app/backend")
from liveness_resolver import (  # noqa: E402
    AGENT_HEARTBEAT_STALE_SECONDS,
    WAN_PROBE_FRESHNESS_SECONDS,
    build_blackout_clients,
    build_clients_without_online_agent,
    build_wan_down_clients,
    compute_status,
)

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")

backend_env = dotenv_values("/app/backend/.env")
MONGO_URL = os.environ.get("MONGO_URL") or backend_env.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME") or backend_env.get("DB_NAME")

# --- client di test -----------------------------------------------------
CID_BO = "TEST_QA_BLACKOUT_119"      # agent giu' + WAN giu' fresca  -> blackout
CID_MIXED = "TEST_QA_MIXED_119"      # agent giu' + 1 target fresco ON -> stale
CID_OLDONLY = "TEST_QA_OLDONLY_119"  # agent giu' + solo probe stantie  -> stale
CID_LIVE = "TEST_QA_LIVE_119"        # agent vivo + WAN giu'            -> online
ALL_CIDS = [CID_BO, CID_MIXED, CID_OLDONLY, CID_LIVE]

IP = {
    CID_BO: "10.201.0.5",
    CID_MIXED: "10.202.0.5",
    CID_OLDONLY: "10.203.0.5",
    CID_LIVE: "10.204.0.5",
}


def _iso(dt):
    return dt.isoformat()


def _now():
    return datetime.now(timezone.utc)


def _probe(cid, target, status, reachable, checked_at):
    return {
        "client_id": cid,
        # wan_probe_results ha un indice UNIQUE su target_id: un doc per target
        "target_id": f"TEST_QA_119_{target}",
        "target": target,
        "target_host": target,
        "status": status,
        "ping": {"reachable": reachable, "avg_ms": 12.0 if reachable else None},
        "ports": [],
        "checked_at": _iso(checked_at),
    }


# --- fixtures -----------------------------------------------------------
@pytest.fixture(scope="module")
def db():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


def _cleanup(db):
    q = {"$in": ALL_CIDS}
    db.clients.delete_many({"id": q})
    for coll in ("managed_agents", "managed_devices", "device_poll_status",
                 "discovered_endpoints", "wan_probe_results", "wan_targets",
                 "datto_devices", "devices", "alerts", "site_blackout_state"):
        db[coll].delete_many({"client_id": q})


@pytest.fixture(scope="module", autouse=True)
def seeded(db):
    now = _now()
    old_hb = now - timedelta(seconds=AGENT_HEARTBEAT_STALE_SECONDS + 60)
    old_probe = now - timedelta(minutes=30)
    _cleanup(db)

    db.clients.insert_many([
        {"id": c, "name": f"TEST_QA {c}", "created_at": _iso(now)} for c in ALL_CIDS
    ])
    db.managed_agents.insert_many([
        {"client_id": CID_BO, "agent_id": "TEST_QA_a1", "role": "master",
         "hostname": "QA-BO-AGENT", "last_heartbeat_at": _iso(old_hb),
         "last_seen_at": _iso(old_hb)},
        {"client_id": CID_MIXED, "agent_id": "TEST_QA_a2", "role": "master",
         "hostname": "QA-MIX-AGENT", "last_heartbeat_at": _iso(old_hb),
         "last_seen_at": _iso(old_hb)},
        {"client_id": CID_OLDONLY, "agent_id": "TEST_QA_a3", "role": "master",
         "hostname": "QA-OLD-AGENT", "last_heartbeat_at": _iso(old_hb),
         "last_seen_at": _iso(old_hb)},
        {"client_id": CID_LIVE, "agent_id": "TEST_QA_a4", "role": "master",
         "hostname": "QA-LIVE-AGENT", "last_heartbeat_at": _iso(now),
         "last_seen_at": _iso(now)},
    ])
    # device vitali (la Panoramica conta i vitali) con poll FRESCO reachable=True:
    # simula esattamente il bug "device verdi durante blackout".
    db.managed_devices.insert_many([
        {"client_id": c, "ip": IP[c], "name": f"TEST_QA_PC_{c[-7:]}",
         "device_type": "server", "source": "manual", "is_vital": True,
         "last_seen_at": _iso(now)}
        for c in ALL_CIDS
    ])
    db.device_poll_status.insert_many([
        {"client_id": c, "device_ip": IP[c], "reachable": True, "method": "ping",
         "source": "agent_v4", "last_poll": _iso(now), "last_ping_at": _iso(now),
         "last_reachable_at": _iso(now), "consecutive_failures": 0}
        for c in ALL_CIDS
    ])
    # evidenza ARP fresca (proviene dall'agent -> non deve tenere "online")
    db.discovered_endpoints.insert_many([
        {"client_id": c, "ip": IP[c], "mac": "aa:bb:cc:00:00:01",
         "source_connector_mode": "agent_v4", "last_seen_via": "arp",
         "last_seen_at": _iso(now)}
        for c in ALL_CIDS
    ])
    # wan_probe_results
    db.wan_probe_results.insert_many([
        # BLACKOUT: target fresco offline + vecchio doc "online" (BUG#1)
        _probe(CID_BO, "bo-fw.example.test", "offline", False, now),
        _probe(CID_BO, "bo-old.example.test", "online", True, old_probe),
        # MIXED: un target fresco offline + un target fresco online (BUG#2)
        _probe(CID_MIXED, "mix-fw.example.test", "offline", False, now),
        _probe(CID_MIXED, "mix-vpn.example.test", "online", True, now),
        # OLDONLY: solo risultati stantii (offline vecchio) -> non conta
        _probe(CID_OLDONLY, "old-fw.example.test", "offline", False, old_probe),
        # LIVE: WAN giu' fresca ma agent vivo -> nessun blackout
        _probe(CID_LIVE, "live-fw.example.test", "offline", False, now),
    ])
    yield db
    _cleanup(db)


@pytest.fixture(scope="module")
def token():
    content = Path("/app/memory/test_credentials.md").read_text(encoding="utf-8")
    email = re.search(r"Email:\s*`([^`]+)`", content).group(1)
    password = re.search(r"Password:\s*`([^`]+)`", content).group(1)
    secret = re.search(r"`([A-Z2-7]{26,})`", content).group(1)
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    if r.status_code != 200:
        pytest.fail(f"login failed {r.status_code}: {r.text[:300]}")
    data = r.json()
    tok = data.get("token")
    if data.get("requires_2fa") or data.get("requires_2fa_setup"):
        r2 = s.post(f"{BASE_URL}/api/auth/verify-2fa", json={"code": pyotp.TOTP(secret).now()},
                    headers={"Authorization": f"Bearer {tok}"}, timeout=30)
        if r2.status_code != 200:
            pytest.fail(f"verify-2fa failed {r2.status_code}: {r2.text[:300]}")
        tok = r2.json().get("token")
    assert tok
    return tok


def _run(coro):
    client = AsyncIOMotorClient(MONGO_URL)
    try:
        return asyncio.get_event_loop().run_until_complete(coro(client[DB_NAME]))
    finally:
        client.close()


def _sets():
    async def _inner(mdb):
        offline = await build_clients_without_online_agent(mdb)
        wan_down = await build_wan_down_clients(mdb)
        blackout = await build_blackout_clients(mdb, offline)
        return offline, wan_down, blackout
    return _run(_inner)


def _md(cid):
    return {"client_id": cid, "ip": IP[cid], "source": "manual"}


PD_OK = {"reachable": True, "method": "ping", "consecutive_failures": 0,
         "last_reachable_at": _iso(_now())}


# ================= UNIT: liveness_resolver =================
class TestLivenessResolverUnit:

    def test_constants_speed_tuning(self):
        assert AGENT_HEARTBEAT_STALE_SECONDS == 90, AGENT_HEARTBEAT_STALE_SECONDS
        assert WAN_PROBE_FRESHNESS_SECONDS == 180, WAN_PROBE_FRESHNESS_SECONDS

    def test_agent_stale_set(self):
        offline, _wan, _blk = _sets()
        for c in (CID_BO, CID_MIXED, CID_OLDONLY):
            assert c in offline, f"{c} dovrebbe essere agent-down"
        assert CID_LIVE not in offline

    def test_wan_down_freshness_and_all_targets(self):
        _off, wan_down, _blk = _sets()
        # BUG#1: vecchio doc "online" non deve bloccare la classificazione
        assert CID_BO in wan_down, "BUG#1 freschezza: WAN non classificata giu'"
        # BUG#2: un target fresco raggiungibile => NON WAN giu'
        assert CID_MIXED not in wan_down, "BUG#2 ALL-targets: falso WAN-down"
        # nessun risultato fresco => non decidibile => non WAN giu'
        assert CID_OLDONLY not in wan_down, "probe stantie non devono contare"
        # WAN giu' ma agent vivo: appare in wan_down ma NON in blackout
        assert CID_LIVE in wan_down

    def test_blackout_intersection(self):
        _off, _wan, blackout = _sets()
        assert CID_BO in blackout
        assert CID_MIXED not in blackout
        assert CID_OLDONLY not in blackout
        assert CID_LIVE not in blackout, "agent vivo => nessun blackout"

    def test_compute_status_blackout_is_offline_site_blackout(self):
        offline, _wan, blackout = _sets()
        status, reason = compute_status(PD_OK, _md(CID_BO), {}, {}, offline, blackout)
        assert (status, reason) == ("offline", "site_blackout"), (status, reason)

    def test_compute_status_agent_down_wan_up_is_stale(self):
        offline, _wan, blackout = _sets()
        for cid in (CID_MIXED, CID_OLDONLY):
            status, reason = compute_status(PD_OK, _md(cid), {}, {}, offline, blackout)
            assert (status, reason) == ("stale", "agent_offline"), (cid, status, reason)

    def test_compute_status_evidence_does_not_override_blackout(self):
        offline, _wan, blackout = _sets()
        ip_ev = {IP[CID_BO]: "agent_v4_arp"}
        status, reason = compute_status(PD_OK, _md(CID_BO), ip_ev, {}, offline, blackout)
        assert (status, reason) == ("offline", "site_blackout"), (status, reason)

    def test_compute_status_regression_live_client_online(self):
        offline, _wan, blackout = _sets()
        status, _r = compute_status(PD_OK, _md(CID_LIVE), {}, {}, offline, blackout)
        assert status == "online", status

    def test_wan_recovery_flips_blackout_to_stale(self, db):
        """WAN torna su (fresca) -> il device deve passare a stale, non offline."""
        db.wan_probe_results.update_many(
            {"client_id": CID_BO, "target": "bo-fw.example.test"},
            {"$set": {"status": "online", "ping": {"reachable": True},
                      "checked_at": _iso(_now())}},
        )
        try:
            offline, wan_down, blackout = _sets()
            assert CID_BO not in wan_down
            assert CID_BO not in blackout
            status, reason = compute_status(PD_OK, _md(CID_BO), {}, {}, offline, blackout)
            assert (status, reason) == ("stale", "agent_offline"), (status, reason)
        finally:
            db.wan_probe_results.update_many(
                {"client_id": CID_BO, "target": "bo-fw.example.test"},
                {"$set": {"status": "offline", "ping": {"reachable": False},
                          "checked_at": _iso(_now())}},
            )

    def test_ports_open_counts_as_reachable(self, db):
        """Un target fresco con una porta aperta => WAN su (non blackout)."""
        db.wan_probe_results.insert_one({
            "client_id": CID_BO, "target_id": "TEST_QA_119_bo-ports",
            "target": "bo-ports.example.test",
            "status": "offline", "ping": {"reachable": False},
            "ports": [{"port": 443, "open": True}], "checked_at": _iso(_now()),
        })
        try:
            _off, wan_down, blackout = _sets()
            assert CID_BO not in wan_down, "porta aperta => WAN raggiungibile"
            assert CID_BO not in blackout
        finally:
            db.wan_probe_results.delete_many({"client_id": CID_BO, "target": "bo-ports.example.test"})


# ================= REST: consistenza endpoint =================
def _devices(token, cid):
    r = requests.get(f"{BASE_URL}/api/devices", params={"client_id": cid},
                     headers={"Authorization": f"Bearer {token}"}, timeout=90)
    assert r.status_code == 200, f"GET /api/devices?client_id={cid} -> {r.status_code}: {r.text[:300]}"
    return r.json()


def _overview(token):
    r = requests.get(f"{BASE_URL}/api/overview/clients",
                     headers={"Authorization": f"Bearer {token}"}, timeout=120)
    assert r.status_code == 200, f"GET /api/overview/clients -> {r.status_code}: {r.text[:300]}"
    return r.json()


def _find(devices, cid):
    hit = [d for d in devices if (d.get("ip") or d.get("ip_address")) == IP[cid]]
    assert hit, f"device {IP[cid]} non trovato in {len(devices)} risultati"
    return hit[0]


def _client_bucket(payload, cid):
    items = payload if isinstance(payload, list) else (payload.get("clients") or [])
    hit = [c for c in items if (c.get("client_id") or c.get("id")) == cid]
    assert hit, f"client {cid} non presente in /api/overview/clients"
    return hit[0]


class TestRestConsistency:

    def test_devices_endpoint_blackout_offline(self, token):
        d = _find(_devices(token, CID_BO), CID_BO)
        assert d.get("status") == "offline", f"atteso offline, ottenuto {d.get('status')}: {d}"
        assert d.get("status_reason") == "site_blackout", d.get("status_reason")

    def test_devices_endpoint_agent_down_wan_up_stale(self, token):
        for cid in (CID_MIXED, CID_OLDONLY):
            d = _find(_devices(token, cid), cid)
            assert d.get("status") == "stale", f"{cid}: atteso stale, ottenuto {d.get('status')}"
            assert d.get("status_reason") == "agent_offline", (cid, d.get("status_reason"))

    def test_devices_endpoint_live_client_online(self, token):
        d = _find(_devices(token, CID_LIVE), CID_LIVE)
        assert d.get("status") == "online", f"falso non-online: {d}"

    def test_overview_matches_devices_endpoint(self, token):
        payload = _overview(token)
        bo = _client_bucket(payload, CID_BO).get("devices") or {}
        assert bo.get("offline", 0) >= 1, f"Panoramica non mostra offline per blackout: {bo}"
        assert bo.get("online", 0) == 0, f"Panoramica mostra ancora online: {bo}"
        mix = _client_bucket(payload, CID_MIXED).get("devices") or {}
        assert mix.get("stale", 0) >= 1, f"atteso stale in Panoramica: {mix}"
        assert mix.get("online", 0) == 0, mix
        live = _client_bucket(payload, CID_LIVE).get("devices") or {}
        assert live.get("online", 0) >= 1, f"regressione: client vivo non online: {live}"

    def test_no_objectid_leak(self, token):
        for d in _devices(token, CID_BO):
            assert "_id" not in d


# ================= ALERTING quasi-live =================
class TestSiteBlackoutAlert:
    """L'alert engine (interval 60s) deve emettere un alert 'site_blackout'
    per il cliente in blackout confermato (passivo: nessuna invocazione diretta
    per non generare notifiche extra)."""

    def test_site_blackout_alert_emitted_within_2_cycles(self, db):
        deadline = time.time() + 140
        found = None
        while time.time() < deadline:
            # mantieni la probe WAN "fresca" (finestra 180s) durante l'attesa
            db.wan_probe_results.update_many(
                {"client_id": CID_BO, "target": "bo-fw.example.test"},
                {"$set": {"checked_at": _iso(_now())}},
            )
            found = db.alerts.find_one({"client_id": CID_BO, "source_type": "site_blackout"})
            if found:
                break
            time.sleep(10)
        assert found, "nessun alert 'site_blackout' emesso entro ~2 cicli (140s)"
        assert found.get("severity") == "critical", found.get("severity")
        assert found.get("status") == "active", found.get("status")
