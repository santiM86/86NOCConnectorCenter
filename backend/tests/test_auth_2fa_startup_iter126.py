"""Iteration 126 — verify backend startup after external_monitor syntax fix + admin login/2FA flow."""
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

CRED_FILE = Path("/app/memory/test_credentials.md")


@pytest.fixture(scope="module")
def creds():
    if not CRED_FILE.exists():
        pytest.skip("missing test_credentials.md")
    content = CRED_FILE.read_text(encoding="utf-8")
    email = re.search(r'(?im)^\s*(?:[-*]\s*)?(?:\*\*)?Email(?:\*\*)?\s*:\s*`?([^`\s]+)', content)
    pwd = re.search(r'(?im)^\s*(?:[-*]\s*)?(?:\*\*)?Password(?:\*\*)?\s*:\s*`?([^`\s]+)', content)
    secret = re.search(r'`([A-Z2-7]{32})`', content)
    if not email or not pwd:
        pytest.skip("no creds parsed")
    return {
        "email": email.group(1),
        "password": pwd.group(1),
        "totp_secret": secret.group(1) if secret else None,
    }


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# --- Startup / health ---
class TestStartup:
    def test_api_root_reachable(self, client):
        r = client.get(f"{BASE_URL}/api/", timeout=30)
        assert r.status_code in (200, 404), f"backend not responding: {r.status_code} {r.text[:200]}"

    def test_openapi_includes_external_monitor(self, client):
        # openapi.json is not exposed through the ingress (/ goes to frontend),
        # so query the backend directly on its internal port.
        r = None
        for url in (f"{BASE_URL}/api/openapi.json", "http://localhost:8001/openapi.json"):
            try:
                r = client.get(url, timeout=60)
            except Exception:
                continue
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
                break
        assert r is not None and r.status_code == 200, "openapi unreachable"
        paths = r.json().get("paths", {})
        ext = [p for p in paths if p.startswith("/api/external-monitor")]
        assert ext, "external-monitor routes not registered (import failure?)"


# --- Auth: login + 2FA ---
class TestAuthFlow:
    def test_login_returns_token_and_requires_2fa(self, client, creds):
        r = client.post(f"{BASE_URL}/api/auth/login",
                        json={"email": creds["email"], "password": creds["password"]}, timeout=30)
        assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:300]}"
        data = r.json()
        assert data.get("token"), "no token in login response"
        assert data.get("requires_2fa") is True or data.get("requires_2fa_setup") is True, \
            f"expected 2FA challenge, got {data}"
        pytest.enroll_token = data["token"]
        pytest.login_data = data

    def test_login_wrong_password_rejected(self, client, creds):
        r = client.post(f"{BASE_URL}/api/auth/login",
                        json={"email": creds["email"], "password": "definitely-wrong-pw"}, timeout=30)
        assert r.status_code in (401, 403, 423, 429), f"unexpected status {r.status_code}: {r.text[:200]}"

    def test_verify_2fa_returns_full_token(self, client, creds):
        assert creds["totp_secret"], "no TOTP secret in credentials file"
        token = getattr(pytest, "enroll_token", None)
        assert token, "login token missing (login test failed)"
        code = pyotp.TOTP(creds["totp_secret"]).now()
        r = client.post(f"{BASE_URL}/api/auth/verify-2fa", json={"code": code},
                        headers={"Authorization": f"Bearer {token}"}, timeout=30)
        assert r.status_code == 200, f"verify-2fa failed: {r.status_code} {r.text[:300]}"
        data = r.json()
        full = data.get("token") or data.get("access_token")
        assert full, f"no full token returned: {data}"
        assert data.get("user", {}).get("email") == creds["email"] or data.get("user") is None
        pytest.full_token = full
        pytest.refresh_token = data.get("refresh_token")

    def test_verify_2fa_wrong_code_rejected(self, client, creds):
        # fresh login token
        r = client.post(f"{BASE_URL}/api/auth/login",
                        json={"email": creds["email"], "password": creds["password"]}, timeout=30)
        assert r.status_code == 200
        t = r.json()["token"]
        r2 = client.post(f"{BASE_URL}/api/auth/verify-2fa", json={"code": "000000"},
                         headers={"Authorization": f"Bearer {t}"}, timeout=30)
        assert r2.status_code in (400, 401, 403), f"wrong TOTP accepted?! {r2.status_code} {r2.text[:200]}"

    def test_refresh_token_present(self):
        assert getattr(pytest, "refresh_token", None), "verify-2fa did not return refresh_token"


# --- Protected endpoints with full token ---
class TestProtectedEndpoints:
    @pytest.fixture(scope="class")
    def auth_headers(self):
        token = getattr(pytest, "full_token", None)
        if not token:
            pytest.fail("no full token available from 2FA flow")
        return {"Authorization": f"Bearer {token}"}

    def test_clients(self, client, auth_headers):
        r = client.get(f"{BASE_URL}/api/clients", headers=auth_headers, timeout=60)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        assert isinstance(r.json(), (list, dict))

    def test_auth_me(self, client, auth_headers):
        r = client.get(f"{BASE_URL}/api/auth/me", headers=auth_headers, timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"

    def test_tv_dashboard(self, client, auth_headers):
        r = client.get(f"{BASE_URL}/api/tv/dashboard", headers=auth_headers, timeout=90)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"

    def test_no_mongo_object_id_leak(self, client, auth_headers):
        r = client.get(f"{BASE_URL}/api/clients", headers=auth_headers, timeout=60)
        assert r.status_code == 200
        assert '"_id"' not in r.text, "_id leaked in /api/clients response"

    def test_protected_without_token_rejected(self, client):
        s = requests.Session()
        r = s.get(f"{BASE_URL}/api/clients", timeout=30)
        assert r.status_code in (401, 403), f"unauthenticated access allowed: {r.status_code}"

    def test_external_monitor_targets(self, client, auth_headers):
        r = client.get(f"{BASE_URL}/api/external-monitor/targets", headers=auth_headers, timeout=60)
        assert r.status_code in (200, 404, 422), f"{r.status_code} {r.text[:300]}"
