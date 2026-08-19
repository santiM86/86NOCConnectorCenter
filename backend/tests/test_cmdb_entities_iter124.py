"""Iteration 124 — CMDB Unified Inventory / Entity Resolution endpoints."""
import os
import re
from pathlib import Path

import pyotp
import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")
CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"
TOTP_SECRET = "NMHDJNO53WLTOSREUXWERE6FDH5TAKC3"


@pytest.fixture(scope="module")
def creds():
    p = Path("/app/memory/test_credentials.md")
    if not p.exists():
        pytest.skip("missing credentials file")
    c = p.read_text(encoding="utf-8")
    e = re.search(r'(?im)^\s*[-*]?\s*Email:\s*`([^`]+)`', c)
    pw = re.search(r'(?im)^\s*[-*]?\s*Password:\s*`([^`]+)`', c)
    if not e or not pw:
        pytest.skip("creds not parseable")
    return {"email": e.group(1), "password": pw.group(1)}


@pytest.fixture(scope="module")
def token(creds):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json=creds, timeout=60)
    if r.status_code != 200:
        pytest.fail(f"login failed {r.status_code}: {r.text[:300]}")
    d = r.json()
    tk = d.get("token") or d.get("access_token")
    assert tk, f"no token in login response: {d}"
    if d.get("requires_2fa") or d.get("requires_2fa_setup"):
        code = pyotp.TOTP(TOTP_SECRET).now()
        r2 = s.post(f"{BASE_URL}/api/auth/verify-2fa", json={"code": code},
                    headers={"Authorization": f"Bearer {tk}"}, timeout=60)
        if r2.status_code != 200:
            pytest.fail(f"verify-2fa failed {r2.status_code}: {r2.text[:300]}")
        tk = r2.json().get("token") or r2.json().get("access_token")
        assert tk
    return tk


@pytest.fixture(scope="module")
def client(token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return s


# --- auth protection ---
class TestAuthProtection:
    def test_entities_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/cmdb/entities", timeout=60)
        assert r.status_code in (401, 403), r.status_code

    def test_rebuild_requires_auth(self):
        r = requests.post(f"{BASE_URL}/api/cmdb/entities/rebuild", timeout=60)
        assert r.status_code in (401, 403), r.status_code

    def test_detail_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/cmdb/entities/whatever", timeout=60)
        assert r.status_code in (401, 403), r.status_code


# --- rebuild + list ---
class TestRebuildAndList:
    def test_rebuild_all(self, client):
        r = client.post(f"{BASE_URL}/api/cmdb/entities/rebuild", timeout=300)
        assert r.status_code == 200, r.text[:500]
        d = r.json()
        assert "result" in d and isinstance(d["result"], dict)
        assert CLIENT_ID in d["result"], f"sample client missing: {list(d['result'])[:5]}"
        assert isinstance(d["result"][CLIENT_ID], int) and d["result"][CLIENT_ID] > 0
        print("rebuild_all total entities:", sum(d["result"].values()), "clients:", len(d["result"]))

    def test_rebuild_single_client(self, client):
        r = client.post(f"{BASE_URL}/api/cmdb/entities/rebuild?client_id={CLIENT_ID}", timeout=300)
        assert r.status_code == 200, r.text[:500]
        d = r.json()
        assert d["client_id"] == CLIENT_ID
        assert isinstance(d["entities"], int) and d["entities"] > 0

    def test_list_entities_schema(self, client):
        r = client.get(f"{BASE_URL}/api/cmdb/entities?client_id={CLIENT_ID}", timeout=120)
        assert r.status_code == 200, r.text[:500]
        d = r.json()
        assert d["count"] == len(d["entities"]) and d["count"] > 0
        for e in d["entities"]:
            for f in ("entity_id", "client_id", "primary_ip", "name", "device_type",
                      "is_vital", "sources", "identity", "attrs", "manual"):
                assert f in e, f"missing field {f} in {e.get('primary_ip')}"
            assert e["client_id"] == CLIENT_ID
            assert isinstance(e["sources"], list) and isinstance(e["identity"], dict)
            assert set(e["identity"]).issubset({"serial", "mac", "datto_uid", "agent_id",
                                                "hostname", "ip"}), e["identity"]
            assert "_id" not in e

    def test_86bitserver_merge(self, client):
        r = client.get(f"{BASE_URL}/api/cmdb/entities?client_id={CLIENT_ID}", timeout=120)
        ents = r.json()["entities"]
        target = [e for e in ents if e.get("primary_ip") == "10.30.0.201"]
        assert target, "entity 10.30.0.201 not found"
        e = target[0]
        assert e["name"] == "86bitserver", e["name"]
        assert "datto" in e["sources"] and "monitoring" in e["sources"], e["sources"]
        assert e["identity"].get("datto_uid"), e["identity"]

    def test_source_filter(self, client):
        r = client.get(f"{BASE_URL}/api/cmdb/entities?client_id={CLIENT_ID}&source=datto", timeout=120)
        assert r.status_code == 200
        for e in r.json()["entities"]:
            assert "datto" in e["sources"]

    def test_entity_detail_and_404(self, client):
        ents = client.get(f"{BASE_URL}/api/cmdb/entities?client_id={CLIENT_ID}", timeout=120).json()["entities"]
        eid = ents[0]["entity_id"]
        r = client.get(f"{BASE_URL}/api/cmdb/entities/{eid}", timeout=60)
        assert r.status_code == 200, r.text[:300]
        assert r.json()["entity_id"] == eid
        assert "_id" not in r.json()
        r404 = client.get(f"{BASE_URL}/api/cmdb/entities/does-not-exist-xyz", timeout=60)
        assert r404.status_code == 404, r404.status_code

    def test_idempotency(self, client):
        before = client.get(f"{BASE_URL}/api/cmdb/entities?client_id={CLIENT_ID}", timeout=120).json()["count"]
        ids_before = {e["entity_id"] for e in client.get(
            f"{BASE_URL}/api/cmdb/entities?client_id={CLIENT_ID}", timeout=120).json()["entities"]}
        for _ in range(2):
            r = client.post(f"{BASE_URL}/api/cmdb/entities/rebuild?client_id={CLIENT_ID}", timeout=300)
            assert r.status_code == 200
        after = client.get(f"{BASE_URL}/api/cmdb/entities?client_id={CLIENT_ID}", timeout=120).json()
        assert after["count"] == before, f"entity count drifted {before} -> {after['count']}"
        ids_after = {e["entity_id"] for e in after["entities"]}
        assert ids_after == ids_before, "entity_ids changed across rebuilds (unstable identity)"
