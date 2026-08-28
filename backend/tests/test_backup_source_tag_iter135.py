"""Iteration 135 — backup `source` tag ('vm' | '365') on the three surfaces.

Covers:
  - GET /api/overview/clients      -> client['backup']['source'] when total > 0
  - GET /api/tv/dashboard          -> client_summaries[]['backup']['source']
  - GET /api/mobile/dashboard      -> same payload via X-Mobile-Token
  - backup_aggregation.build_backup_by_client sets 'source' only when total > 0
"""
import os

import pyotp
import pytest
import requests
from dotenv import dotenv_values

_env = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or _env.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
if not BASE_URL:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")

ADMIN_EMAIL = "info@86bit.it"
ADMIN_PASSWORD = "Ariel17051986@!@86"
TOTP_SECRET = "NMHDJNO53WLTOSREUXWERE6FDH5TAKC3"
MOBILE_TOKEN_FALLBACK = "jFdx6pqssnLsTIoxb2LM6rRHpFBTrcYSuvDRABISTu8"
VALID_SOURCES = {"vm", "365"}


@pytest.fixture(scope="session")
def token():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=60)
    assert r.status_code == 200, f"login failed {r.status_code}: {r.text[:300]}"
    data = r.json()
    tok = data.get("token")
    assert tok, f"no token in login response: {data}"
    if data.get("requires_2fa"):
        code = pyotp.TOTP(TOTP_SECRET).now()
        r2 = s.post(f"{BASE_URL}/api/auth/verify-2fa", json={"code": code},
                    headers={"Authorization": f"Bearer {tok}"}, timeout=60)
        assert r2.status_code == 200, f"verify-2fa failed {r2.status_code}: {r2.text[:300]}"
        tok = r2.json().get("token")
        assert tok
    return tok


@pytest.fixture(scope="session")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def mobile_token(auth):
    r = requests.post(f"{BASE_URL}/api/mobile/pairing", headers=auth, json={}, timeout=60)
    if r.status_code in (200, 201):
        t = r.json().get("token")
        if t:
            return t
    return MOBILE_TOKEN_FALLBACK


# --- overview -------------------------------------------------------------
class TestOverviewBackupSource:
    def test_overview_clients_backup_source(self, auth):
        r = requests.get(f"{BASE_URL}/api/overview/clients", headers=auth, timeout=120)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        clients = body if isinstance(body, list) else body.get("clients", [])
        assert isinstance(clients, list) and clients, "no clients returned"
        with_backup = 0
        for c in clients:
            bk = c.get("backup")
            assert bk is not None, f"client {c.get('name')} missing backup object"
            if (bk.get("total") or 0) > 0:
                with_backup += 1
                assert "source" in bk, f"{c.get('name')}: backup.total>0 but no 'source'"
                assert bk["source"] in VALID_SOURCES, f"{c.get('name')}: bad source {bk['source']!r}"
            else:
                assert bk.get("source") in (None, *VALID_SOURCES)
        assert with_backup > 0, "no client with backup.total>0 — cannot validate source tag"
        print(f"overview: {len(clients)} clients, {with_backup} with backups")

    def test_no_mongo_object_id(self, auth):
        r = requests.get(f"{BASE_URL}/api/overview/clients", headers=auth, timeout=120)
        assert "_id" not in r.text


# --- tv -------------------------------------------------------------------
class TestTvBackupSource:
    def test_tv_dashboard_backup_source(self, auth):
        r = requests.get(f"{BASE_URL}/api/tv/dashboard", headers=auth, timeout=120)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        summaries = data.get("client_summaries") or data.get("clients") or []
        assert summaries, f"no client summaries; keys={list(data.keys())}"
        found = 0
        for cs in summaries:
            bk = cs.get("backup")
            if bk is None:
                continue
            assert (bk.get("total") or 0) > 0, f"{cs.get('name')}: non-null backup with total 0"
            assert bk.get("source") in VALID_SOURCES, f"{cs.get('name')}: bad/missing source {bk.get('source')!r}"
            found += 1
        assert found > 0, "no non-null backup summary in tv dashboard"
        print(f"tv: {len(summaries)} summaries, {found} with backup+source")


# --- mobile ---------------------------------------------------------------
class TestMobileBackupSource:
    def test_mobile_dashboard_requires_token(self):
        r = requests.get(f"{BASE_URL}/api/mobile/dashboard", timeout=60)
        assert r.status_code in (401, 403), f"expected auth error, got {r.status_code}"

    def test_mobile_dashboard_backup_source(self, mobile_token):
        r = requests.get(f"{BASE_URL}/api/mobile/dashboard",
                         headers={"X-Mobile-Token": mobile_token}, timeout=120)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        summaries = data.get("client_summaries") or data.get("clients") or []
        assert summaries, f"no client summaries; keys={list(data.keys())}"
        found = 0
        for cs in summaries:
            bk = cs.get("backup")
            if bk is None:
                continue
            assert bk.get("source") in VALID_SOURCES, f"{cs.get('name')}: bad source {bk.get('source')!r}"
            found += 1
        assert found > 0, "no non-null backup summary in mobile dashboard"

    def test_mobile_matches_tv(self, auth, mobile_token):
        tv = requests.get(f"{BASE_URL}/api/tv/dashboard", headers=auth, timeout=120).json()
        mob = requests.get(f"{BASE_URL}/api/mobile/dashboard",
                           headers={"X-Mobile-Token": mobile_token}, timeout=120).json()
        tv_map = {c["id"]: (c.get("backup") or {}).get("source")
                  for c in (tv.get("client_summaries") or tv.get("clients") or [])}
        mob_map = {c["id"]: (c.get("backup") or {}).get("source")
                   for c in (mob.get("client_summaries") or mob.get("clients") or [])}
        assert tv_map == mob_map, f"tv {tv_map} != mobile {mob_map}"


# --- cross-surface parity -------------------------------------------------
def test_source_parity_overview_vs_tv(auth):
    ov = requests.get(f"{BASE_URL}/api/overview/clients", headers=auth, timeout=120).json()
    ov_clients = ov if isinstance(ov, list) else ov.get("clients", [])
    ov_map = {c["id"]: (c.get("backup") or {}).get("source")
              for c in ov_clients if (c.get("backup") or {}).get("total", 0) > 0}
    tv = requests.get(f"{BASE_URL}/api/tv/dashboard", headers=auth, timeout=120).json()
    tv_map = {c["id"]: (c.get("backup") or {}).get("source")
              for c in (tv.get("client_summaries") or tv.get("clients") or []) if c.get("backup")}
    assert ov_map, "no backup clients in overview"
    for cid, src in ov_map.items():
        assert tv_map.get(cid) == src, f"client {cid}: overview source={src} but tv={tv_map.get(cid)}"


# --- unit: aggregation logic --------------------------------------------
def test_aggregation_unit_vm_priority():
    """Directly exercise the 'vm' branch which live data cannot currently hit."""
    import asyncio
    import sys
    sys.path.insert(0, "/app/backend")
    from backup_aggregation import build_backup_by_client

    class FakeCursor:
        def __init__(self, docs):
            self.docs = docs

        async def to_list(self, n):
            return self.docs

    class FakeColl:
        def __init__(self, docs):
            self.docs = docs

        def find(self, *a, **k):
            return FakeCursor(self.docs)

    class FakeDB:
        backup_status = FakeColl([{"client_id": "c1", "status": "ok"}])
        clients = FakeColl([
            {"id": "c1", "hornetsecurity_vm_customers": ["acme"]},
        ])
        backup_job_status = FakeColl([])
        vmbackup_jobs = FakeColl([
            {"customer_name": "acme", "host_name": "h1", "onsite_status": "success"},
            {"customer_name": "acme", "host_name": "h2", "alert_reason": "failed"},
        ])

    res = asyncio.get_event_loop().run_until_complete(build_backup_by_client(FakeDB()))
    assert res["c1"]["source"] == "vm", res
    assert res["c1"]["total"] == 2, res
    assert res["c1"]["error"] == 1


def test_aggregation_unit_365_when_no_vm():
    import asyncio
    import sys
    sys.path.insert(0, "/app/backend")
    from backup_aggregation import build_backup_by_client

    class FakeCursor:
        def __init__(self, docs):
            self.docs = docs

        async def to_list(self, n):
            return self.docs

    class FakeColl:
        def __init__(self, docs):
            self.docs = docs

        def find(self, *a, **k):
            return FakeCursor(self.docs)

    class FakeDB:
        backup_status = FakeColl([])
        clients = FakeColl([{"id": "c2", "hornetsecurity_tenants": ["t1"]}])
        backup_job_status = FakeColl([{"tenant": "t1", "sub_group": "x", "status": "success"}])
        vmbackup_jobs = FakeColl([])

    res = asyncio.get_event_loop().run_until_complete(build_backup_by_client(FakeDB()))
    assert res["c2"]["source"] == "365", res
    assert res["c2"]["total"] == 1
