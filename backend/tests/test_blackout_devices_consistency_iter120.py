"""
ITER 120 — RE-VERIFICA indipendente del fix override liveness in
GET /api/devices (bug P0 ricorrente: device verdi durante blackout e
discrepanza ClientOverviewPage vs ClientsPage).

Casi COMPLEMENTARI ai file iter117/iter119 (che coprono unit + REST base):
  * GET /api/devices SENZA client_id (lista globale) deve applicare lo stesso
    override della chiamata filtrata per client_id (nessuna discrepanza).
  * Device di tipo "connector-scanner" (senza poll, last_seen fresco) in
    blackout -> non deve restare online.
  * Device SENZA alcun poll (pending) in un cliente in blackout: verifica di
    coerenza con /api/overview/clients (che con compute_status lo marca
    offline/stale).
  * Boundary freschezza WAN: probe offline vecchia (>180s) senza probe fresca
    -> NON blackout -> stale/agent_offline.
  * Regressione: cliente con agent vivo + WAN giu' -> device restano online.
  * Coerenza aggregata: conteggi per-status da /api/devices == conteggi da
    /api/overview/clients per lo stesso cliente.

Seed su DB reale con client_id prefissati TEST_QA120_* e target_id distinti
(indice unique su wan_probe_results.target_id). Nessun dato reale toccato.
"""
import os
import re
from collections import Counter
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
MONGO_URL = os.environ.get("MONGO_URL") or backend_env.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME") or backend_env.get("DB_NAME")

CID_BO = "TEST_QA120_BO"        # agent giu' + WAN giu' fresca -> blackout
CID_OLD = "TEST_QA120_OLDWAN"   # agent giu' + probe solo stantie -> stale
CID_OK = "TEST_QA120_OK"        # agent vivo + WAN giu' -> online (regressione)
ALL_CIDS = [CID_BO, CID_OLD, CID_OK]

# device del cliente in blackout
IP_BO_POLL = "10.211.0.10"      # poll fresco reachable=True
IP_BO_SCAN = "10.211.0.11"      # source connector-scanner, last_seen fresco, nessun poll
IP_BO_PEND = "10.211.0.12"      # nessun poll, source manual -> pending
IP_OLD_POLL = "10.212.0.10"
IP_OK_POLL = "10.213.0.10"


def _iso(dt):
    return dt.isoformat()


def _now():
    return datetime.now(timezone.utc)


def _probe(cid, target, status, reachable, checked_at):
    return {
        "client_id": cid,
        "target_id": f"TEST_QA120_{target}",
        "target": target,
        "target_host": target,
        "status": status,
        "ping": {"reachable": reachable, "avg_ms": 10.0 if reachable else None},
        "ports": [],
        "checked_at": _iso(checked_at),
    }


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
    stale_hb = now - timedelta(seconds=200)
    old_probe = now - timedelta(seconds=600)
    _cleanup(db)

    db.clients.insert_many([
        {"id": c, "name": f"TEST_QA120 {c}", "created_at": _iso(now)} for c in ALL_CIDS
    ])
    db.managed_agents.insert_many([
        {"client_id": CID_BO, "agent_id": "TEST_QA120_a1", "role": "master",
         "hostname": "QA120-BO", "last_heartbeat_at": _iso(stale_hb),
         "last_seen_at": _iso(stale_hb)},
        {"client_id": CID_OLD, "agent_id": "TEST_QA120_a2", "role": "master",
         "hostname": "QA120-OLD", "last_heartbeat_at": _iso(stale_hb),
         "last_seen_at": _iso(stale_hb)},
        {"client_id": CID_OK, "agent_id": "TEST_QA120_a3", "role": "master",
         "hostname": "QA120-OK", "last_heartbeat_at": _iso(now),
         "last_seen_at": _iso(now)},
    ])
    db.managed_devices.insert_many([
        {"client_id": CID_BO, "ip": IP_BO_POLL, "name": "TEST_QA120_POLL",
         "device_type": "server", "source": "manual", "is_vital": True,
         "last_seen_at": _iso(now)},
        {"client_id": CID_BO, "ip": IP_BO_SCAN, "name": "TEST_QA120_SCAN",
         "device_type": "workstation", "source": "connector-scanner",
         "last_seen_at": _iso(now)},
        {"client_id": CID_BO, "ip": IP_BO_PEND, "name": "TEST_QA120_PEND",
         "device_type": "workstation", "source": "manual"},
        {"client_id": CID_OLD, "ip": IP_OLD_POLL, "name": "TEST_QA120_OLDPOLL",
         "device_type": "server", "source": "manual", "is_vital": True,
         "last_seen_at": _iso(now)},
        {"client_id": CID_OK, "ip": IP_OK_POLL, "name": "TEST_QA120_OKPOLL",
         "device_type": "server", "source": "manual", "is_vital": True,
         "last_seen_at": _iso(now)},
    ])
    db.device_poll_status.insert_many([
        {"client_id": cid, "device_ip": ip, "reachable": True, "method": "ping",
         "source": "agent_v4", "last_poll": _iso(now), "last_ping_at": _iso(now),
         "last_reachable_at": _iso(now), "consecutive_failures": 0}
        for cid, ip in ((CID_BO, IP_BO_POLL), (CID_OLD, IP_OLD_POLL), (CID_OK, IP_OK_POLL))
    ])
    # evidenza ARP fresca (dall'agent, quindi stantia in blackout)
    db.discovered_endpoints.insert_many([
        {"client_id": CID_BO, "ip": ip, "mac": f"aa:bb:cc:12:00:0{i}",
         "source_connector_mode": "agent_v4", "last_seen_via": "arp",
         "last_seen_at": _iso(now)}
        for i, ip in enumerate((IP_BO_POLL, IP_BO_SCAN, IP_BO_PEND), start=1)
    ])
    db.wan_probe_results.insert_many([
        _probe(CID_BO, "qa120-bo-fw.example.test", "offline", False, now),
        _probe(CID_OLD, "qa120-old-fw.example.test", "offline", False, old_probe),
        _probe(CID_OK, "qa120-ok-fw.example.test", "offline", False, now),
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


def _devices(token, cid=None):
    params = {"client_id": cid} if cid else {}
    r = requests.get(f"{BASE_URL}/api/devices", params=params,
                     headers={"Authorization": f"Bearer {token}"}, timeout=180)
    assert r.status_code == 200, f"GET /api/devices {params} -> {r.status_code}: {r.text[:300]}"
    return r.json()


def _overview(token):
    r = requests.get(f"{BASE_URL}/api/overview/clients",
                     headers={"Authorization": f"Bearer {token}"}, timeout=180)
    assert r.status_code == 200, f"GET /api/overview/clients -> {r.status_code}: {r.text[:300]}"
    payload = r.json()
    return payload if isinstance(payload, list) else (payload.get("clients") or [])


def _ip(d):
    return d.get("ip_address") or d.get("ip")


def _by_ip(devices, ip):
    hit = [d for d in devices if _ip(d) == ip]
    assert hit, f"device {ip} non trovato ({len(devices)} risultati)"
    return hit[0]


def _bucket(items, cid):
    hit = [c for c in items if (c.get("client_id") or c.get("id")) == cid]
    assert hit, f"client {cid} assente da /api/overview/clients"
    return hit[0]


# ============ GET /api/devices — override liveness ============
class TestDevicesOverride:

    def test_blackout_polled_device_offline_site_blackout(self, token):
        d = _by_ip(_devices(token, CID_BO), IP_BO_POLL)
        assert d.get("status") == "offline", f"atteso offline: {d.get('status')}"
        assert d.get("status_reason") == "site_blackout", d.get("status_reason")

    def test_blackout_scanner_source_device_not_online(self, token):
        """P0: nessun falso verde. (NB: oggi ritorna 'pending' — vedi
        test_never_polled_devices_consistent_with_overview per la divergenza)."""
        d = _by_ip(_devices(token, CID_BO), IP_BO_SCAN)
        assert d.get("status") != "online", f"FALSO ONLINE (scanner-source) in blackout: {d}"

    def test_blackout_never_polled_device_not_online(self, token):
        d = _by_ip(_devices(token, CID_BO), IP_BO_PEND)
        assert d.get("status") != "online", f"FALSO ONLINE (mai polleato) in blackout: {d}"

    def test_old_wan_probe_does_not_confirm_blackout(self, token):
        d = _by_ip(_devices(token, CID_OLD), IP_OLD_POLL)
        assert d.get("status") == "stale", f"atteso stale: {d.get('status')}"
        assert d.get("status_reason") == "agent_offline", d.get("status_reason")

    def test_regression_live_agent_device_online(self, token):
        d = _by_ip(_devices(token, CID_OK), IP_OK_POLL)
        assert d.get("status") == "online", f"regressione: {d}"
        assert not d.get("status_reason"), d.get("status_reason")


# ============ Coerenza tra chiamate/endpoint ============
class TestConsistency:

    def test_global_list_matches_per_client_list(self, token):
        glob = [d for d in _devices(token) if d.get("client_id") in ALL_CIDS]
        assert glob, "device di test assenti dalla lista globale /api/devices"
        for cid in ALL_CIDS:
            per_client = {_ip(d): (d.get("status"), d.get("status_reason"))
                          for d in _devices(token, cid)}
            for d in [x for x in glob if x.get("client_id") == cid]:
                ip = _ip(d)
                assert ip in per_client, f"{ip} presente solo nella lista globale"
                assert (d.get("status"), d.get("status_reason")) == per_client[ip], (
                    f"DISCREPANZA globale vs client_id per {ip}: "
                    f"{(d.get('status'), d.get('status_reason'))} != {per_client[ip]}"
                )

    def test_overview_counts_match_devices_endpoint(self, token):
        items = _overview(token)
        for cid in ALL_CIDS:
            devs = _devices(token, cid)
            counts = Counter(d.get("status") for d in devs)
            # /api/devices e' una lista PIATTA: overview la suddivide in due bucket
            # (`devices` = server/infra, `endpoints` = PC/workstation/mobile/IoT).
            # Il confronto corretto e' contro la SOMMA dei due bucket.
            b = _bucket(items, cid)
            dev_b = b.get("devices") or {}
            ep_b = b.get("endpoints") or {}
            def _sum(key):
                return (dev_b.get(key, 0) or 0) + (ep_b.get(key, 0) or 0)
            assert counts.get("online", 0) == _sum("online"), (
                f"{cid}: online devices={counts.get('online', 0)} overview(dev+ep)={_sum('online')}")
            assert counts.get("offline", 0) == _sum("offline"), (
                f"{cid}: offline devices={counts.get('offline', 0)} overview(dev+ep)={_sum('offline')}")
            assert counts.get("stale", 0) == _sum("stale"), (
                f"{cid}: stale devices={counts.get('stale', 0)} overview(dev+ep)={_sum('stale')}")

    def test_never_polled_devices_consistent_with_overview(self, token):
        """DIVERGENZA RESIDUA (iter120): i device del cliente in blackout SENZA
        record device_poll_status restano 'pending' in GET /api/devices mentre
        /api/overview/clients li conta OFFLINE (bucket `endpoints`, offline=2).
        L'override in devices.py scatta solo se status == 'online'."""
        devs = _devices(token, CID_BO)
        never_polled = [d for d in devs if _ip(d) in (IP_BO_SCAN, IP_BO_PEND)]
        ov_ep = _bucket(_overview(token), CID_BO).get("endpoints") or {}
        statuses = [d.get("status") for d in never_polled]
        assert ov_ep.get("offline", 0) == statuses.count("offline"), (
            f"DISCREPANZA pagine: /api/devices={statuses} vs overview endpoints={ov_ep}")

    def test_blackout_client_has_zero_online_everywhere(self, token):
        devs = _devices(token, CID_BO)
        assert all(d.get("status") != "online" for d in devs), \
            [(_ip(d), d.get("status")) for d in devs]
        ov = _bucket(_overview(token), CID_BO).get("devices") or {}
        assert ov.get("online", 0) == 0, ov
