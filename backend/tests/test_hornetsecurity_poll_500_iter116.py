"""Iteration 116 — Hornetsecurity global poll/test endpoints must never return unhandled 500.

Covers:
- POST /api/admin/hornetsecurity/test
- POST /api/admin/hornetsecurity/poll
- GET  /api/admin/hornetsecurity/tenants
"""
import os
import re
import time
from pathlib import Path

import pytest
import pyotp
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")

CRED_PATH = Path("/app/memory/test_credentials.md")


@pytest.fixture(scope="session")
def admin_token():
    if not CRED_PATH.exists():
        pytest.skip("missing test_credentials.md")
    content = CRED_PATH.read_text(encoding="utf-8")
    email = re.search(r'(?im)^-\s*Email:\s*`([^`]+)`', content).group(1)
    password = re.search(r'(?im)^-\s*Password:\s*`([^`]+)`', content).group(1)
    secret_m = re.search(r'`([A-Z2-7]{32})`', content)
    if not secret_m:
        pytest.skip("no TOTP secret found in test_credentials.md")
    secret = secret_m.group(1)

    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    if r.status_code != 200:
        pytest.fail(f"login failed {r.status_code}: {r.text[:300]}")
    data = r.json()
    token = data.get("token") or data.get("access_token")
    assert token, f"no token in login response: {data}"
    if data.get("requires_2fa") or data.get("requires_2fa_setup") or not data.get("refresh_token"):
        code = pyotp.TOTP(secret).now()
        r2 = s.post(f"{BASE_URL}/api/auth/verify-2fa", json={"code": code},
                    headers={"Authorization": f"Bearer {token}"}, timeout=30)
        if r2.status_code != 200:
            # retry once with fresh code (clock window)
            time.sleep(31)
            code = pyotp.TOTP(secret).now()
            r2 = s.post(f"{BASE_URL}/api/auth/verify-2fa", json={"code": code},
                        headers={"Authorization": f"Bearer {token}"}, timeout=30)
        if r2.status_code != 200:
            pytest.fail(f"verify-2fa failed {r2.status_code}: {r2.text[:300]}")
        token = r2.json().get("token") or token
    return token


@pytest.fixture(scope="session")
def client(admin_token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"})
    return s


class TestHornetsecurityGlobal:
    def test_global_config_present(self, client):
        r = client.get(f"{BASE_URL}/api/admin/hornetsecurity/global-config", timeout=60)
        print(f"\n[global-config] status={r.status_code} body={r.text[:500]}")
        assert r.status_code != 500, "unhandled 500 on global-config"
        assert r.status_code == 200
        assert "configured" in r.json()

    def test_test_endpoint_never_500(self, client):
        r = client.post(f"{BASE_URL}/api/admin/hornetsecurity/test", timeout=120)
        print(f"\n[test] status={r.status_code} body={r.text[:800]}")
        assert r.status_code != 500, f"UNHANDLED 500 on /test: {r.text[:500]}"
        assert r.status_code in (200, 400, 404, 502), f"unexpected status {r.status_code}: {r.text[:300]}"
        data = r.json()
        if r.status_code == 200:
            assert "ok" in data and "http_status" in data
            assert "tenants_detected" in data
            assert "diagnostics" in data
            assert isinstance(data["diagnostics"], dict)
        else:
            assert data.get("detail"), "error response without detail"

    def test_poll_endpoint_never_500(self, client):
        r = client.post(f"{BASE_URL}/api/admin/hornetsecurity/poll", timeout=180)
        print(f"\n[poll] status={r.status_code} body={r.text[:800]}")
        assert r.status_code != 500, f"UNHANDLED 500 on /poll: {r.text[:500]}"
        assert r.status_code in (200, 400, 404, 429, 502), f"unexpected status {r.status_code}: {r.text[:300]}"
        data = r.json()
        if r.status_code == 200:
            assert data.get("ok") is True
            for k in ("workloads_total", "tenants_seen", "workloads_persist_errors"):
                assert k in data, f"missing {k} in poll summary"
            assert isinstance(data["workloads_total"], int)
        else:
            assert data.get("detail"), "error response without detail"

    def test_poll_second_call_rate_limited_not_500(self, client):
        r = client.post(f"{BASE_URL}/api/admin/hornetsecurity/poll", timeout=180)
        print(f"\n[poll#2] status={r.status_code} body={r.text[:400]}")
        assert r.status_code != 500, f"UNHANDLED 500 on second /poll: {r.text[:500]}"
        assert r.status_code in (200, 400, 404, 429, 502)

    def test_tenants_endpoint(self, client):
        r = client.get(f"{BASE_URL}/api/admin/hornetsecurity/tenants", timeout=120)
        print(f"\n[tenants] status={r.status_code} body_excerpt={r.text[:300]}")
        assert r.status_code == 200, f"tenants failed {r.status_code}: {r.text[:300]}"
        data = r.json()
        assert isinstance(data.get("tenants"), list), "missing tenants list"
        assert isinstance(data.get("mappings"), list), "missing mappings list"
        print(f"[tenants] count={len(data['tenants'])} mappings={len(data['mappings'])}")
        if data["tenants"]:
            t = data["tenants"][0]
            assert "tenant" in t and "workloads_total" in t
            assert "_id" not in t

    def test_no_mongo_objectid_leak_in_tenants(self, client):
        r = client.get(f"{BASE_URL}/api/admin/hornetsecurity/tenants", timeout=120)
        assert r.status_code == 200
        assert '"_id"' not in r.text, "MongoDB _id leaked in response"

    def test_unauthenticated_poll_rejected(self):
        r = requests.post(f"{BASE_URL}/api/admin/hornetsecurity/poll", timeout=60)
        print(f"\n[poll-noauth] status={r.status_code}")
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"
