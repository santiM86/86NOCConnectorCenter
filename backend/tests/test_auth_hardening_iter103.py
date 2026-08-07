"""Iteration 103 — Auth security hardening regression tests.

Covers:
- Admin login without 2FA -> requires_2fa_setup, no refresh_token
- enroll token cannot access normal endpoints (403 "2FA setup required")
- setup-2fa with empty body (enroll token) -> secret + qr_code
- confirm-2fa with valid TOTP -> full token + refresh_token
- full token accesses /api/reports/list
- subsequent login -> requires_2fa, no refresh; verify-2fa -> full token + refresh
- forged customer JWT signed with legacy 'change-me-customer' key -> 401
"""
import os
import time

import jwt as pyjwt
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

ADMIN_EMAIL = "info@86bit.it"
ADMIN_PASSWORD = "Ariel17051986@!@86"

backend_env = dotenv_values("/app/backend/.env")


@pytest.fixture(scope="module")
def mongo_db():
    client = MongoClient(backend_env["MONGO_URL"])
    yield client[backend_env["DB_NAME"]]
    client.close()


@pytest.fixture(scope="module")
def reset_admin_2fa(mongo_db):
    """Ensure admin starts in 'enroll required' state, and restore it after."""
    def _reset():
        mongo_db.users.update_one(
            {"email": ADMIN_EMAIL},
            {"$set": {"two_factor_enabled": False},
             "$unset": {"totp_secret": "", "totp_secret_pending": ""}},
        )
    _reset()
    yield _reset
    _reset()


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _login(client):
    return client.post(f"{BASE_URL}/api/auth/login",
                       json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})


# ==================== 2FA enrollment flow ====================

class TestAdmin2FAEnrollment:
    state = {}

    def test_a_login_requires_2fa_setup(self, client, reset_admin_2fa):
        r = _login(client)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("requires_2fa_setup") is True, data
        assert data.get("refresh_token") is None, "refresh_token must NOT be issued pre-2FA"
        assert isinstance(data.get("token"), str) and data["token"]
        assert data["user"]["role"] == "admin"
        assert data["user"]["two_factor_enabled"] is False
        TestAdmin2FAEnrollment.state["enroll_token"] = data["token"]

    def test_b_enroll_token_blocked_on_normal_endpoint(self, client):
        token = TestAdmin2FAEnrollment.state["enroll_token"]
        r = client.get(f"{BASE_URL}/api/reports/list",
                       headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text[:300]}"
        assert "2FA setup required" in r.json().get("detail", "")

    def test_c_setup_2fa_without_password(self, client):
        token = TestAdmin2FAEnrollment.state["enroll_token"]
        r = client.post(f"{BASE_URL}/api/auth/setup-2fa", json={},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data.get("secret"), str) and len(data["secret"]) >= 16
        assert isinstance(data.get("qr_code"), str) and len(data["qr_code"]) > 100
        assert ADMIN_EMAIL.replace("@", "%40") in data["uri"] or ADMIN_EMAIL in data["uri"]
        TestAdmin2FAEnrollment.state["secret"] = data["secret"]

    def test_d_confirm_2fa_returns_full_session(self, client, mongo_db):
        token = TestAdmin2FAEnrollment.state["enroll_token"]
        secret = TestAdmin2FAEnrollment.state["secret"]
        code = pyotp.TOTP(secret).now()
        r = client.post(f"{BASE_URL}/api/auth/confirm-2fa", json={"code": code},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("enabled") is True
        assert isinstance(data.get("token"), str) and data["token"]
        assert isinstance(data.get("refresh_token"), str) and data["refresh_token"]
        assert data["user"]["two_factor_enabled"] is True
        # persistence check
        u = mongo_db.users.find_one({"email": ADMIN_EMAIL})
        assert u["two_factor_enabled"] is True
        assert u.get("totp_secret") == secret
        assert "totp_secret_pending" not in u
        TestAdmin2FAEnrollment.state["full_token"] = data["token"]

    def test_e_full_token_accesses_protected_endpoint(self, client):
        token = TestAdmin2FAEnrollment.state["full_token"]
        r = client.get(f"{BASE_URL}/api/reports/list",
                       headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        r2 = client.get(f"{BASE_URL}/api/auth/me",
                        headers={"Authorization": f"Bearer {token}"})
        assert r2.status_code == 200
        assert r2.json()["email"] == ADMIN_EMAIL
        assert r2.json()["two_factor_enabled"] is True

    def test_f_login_with_2fa_then_verify(self, client):
        r = _login(client)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("requires_2fa") is True, data
        assert data.get("refresh_token") is None, "refresh_token must NOT be issued pre-2FA verify"
        pending = data["token"]
        # pending token blocked on normal endpoint
        rb = client.get(f"{BASE_URL}/api/reports/list",
                        headers={"Authorization": f"Bearer {pending}"})
        assert rb.status_code == 403
        assert "2FA verification required" in rb.json().get("detail", "")

        secret = TestAdmin2FAEnrollment.state["secret"]
        totp = pyotp.TOTP(secret)
        # avoid using the same code just consumed by confirm-2fa window edge
        code = totp.now()
        rv = client.post(f"{BASE_URL}/api/auth/verify-2fa", json={"code": code},
                         headers={"Authorization": f"Bearer {pending}"})
        if rv.status_code != 200:
            time.sleep(31)
            rv = client.post(f"{BASE_URL}/api/auth/verify-2fa", json={"code": totp.now()},
                             headers={"Authorization": f"Bearer {pending}"})
        assert rv.status_code == 200, rv.text
        vdata = rv.json()
        assert vdata.get("verified") is True
        assert isinstance(vdata.get("refresh_token"), str) and vdata["refresh_token"]
        rme = client.get(f"{BASE_URL}/api/auth/me",
                         headers={"Authorization": f"Bearer {vdata['token']}"})
        assert rme.status_code == 200

    def test_g_verify_2fa_wrong_code_rejected(self, client):
        r = _login(client)
        assert r.status_code == 200, r.text
        pending = r.json()["token"]
        rv = client.post(f"{BASE_URL}/api/auth/verify-2fa", json={"code": "000000"},
                         headers={"Authorization": f"Bearer {pending}"})
        assert rv.status_code == 401


# ==================== Customer portal forged token ====================

class TestCustomerPortalLegacyKey:
    def test_forged_legacy_key_token_rejected(self, client):
        payload = {
            "role": "customer",
            "client_id": "da3d6e40-b3e5-4d46-9787-dde328a3aa36",
            "sub": "da3d6e40-b3e5-4d46-9787-dde328a3aa36",
            "exp": int(time.time()) + 3600,
        }
        forged = pyjwt.encode(payload, "change-me-customer", algorithm="HS256")
        r = client.get(f"{BASE_URL}/api/customer/dashboard",
                       headers={"Authorization": f"Bearer {forged}"})
        assert r.status_code == 401, f"forged legacy token accepted! {r.status_code}: {r.text[:300]}"

    def test_no_token_rejected(self, client):
        r = client.get(f"{BASE_URL}/api/customer/dashboard")
        assert r.status_code in (401, 403)
