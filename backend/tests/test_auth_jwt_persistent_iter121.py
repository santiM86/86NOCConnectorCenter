"""ITER 121 — P0 auth regression + persistent JWT secret + refresh token."""
import os
import sys
import time

import pyotp
import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")).rstrip("/")
ADMIN_EMAIL = "info@86bit.it"
ADMIN_PASSWORD = "Ariel17051986@!@86"
TOTP_SECRET = "NMHDJNO53WLTOSREUXWERE6FDH5TAKC3"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def tokens(session):
    r = session.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"login failed {r.status_code}: {r.text[:300]}"
    data = r.json()
    assert data.get("requires_2fa") is True, f"expected requires_2fa true, got {data}"
    assert isinstance(data.get("token"), str) and data["token"]
    assert data.get("refresh_token") in (None, "")
    code = pyotp.TOTP(TOTP_SECRET).now()
    r2 = session.post(f"{BASE_URL}/api/auth/verify-2fa", json={"code": code},
                      headers={"Authorization": f"Bearer {data['token']}"}, timeout=30)
    if r2.status_code != 200:
        # TOTP window edge: retry once
        time.sleep(31)
        code = pyotp.TOTP(TOTP_SECRET).now()
        r2 = session.post(f"{BASE_URL}/api/auth/verify-2fa", json={"code": code},
                          headers={"Authorization": f"Bearer {data['token']}"}, timeout=30)
    assert r2.status_code == 200, f"verify-2fa failed {r2.status_code}: {r2.text[:300]}"
    d2 = r2.json()
    assert d2.get("token"), "no full token after 2FA"
    assert d2.get("refresh_token"), "no refresh_token after 2FA"
    assert d2.get("verified") is True
    return d2


# --- AUTH REGRESSION (P0) ---
class TestAuthRegression:
    def test_me_endpoint(self, session, tokens):
        r = session.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {tokens['token']}"}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        assert r.json().get("email") == ADMIN_EMAIL

    def test_protected_clients(self, session, tokens):
        r = session.get(f"{BASE_URL}/api/clients", headers={"Authorization": f"Bearer {tokens['token']}"}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        assert isinstance(r.json(), list)

    def test_no_token_rejected(self, session):
        r = session.get(f"{BASE_URL}/api/auth/me", timeout=30)
        assert r.status_code in (401, 403), r.status_code

    def test_bad_token_rejected(self, session):
        r = session.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": "Bearer garbage.token.x"}, timeout=30)
        assert r.status_code == 401, r.status_code

    def test_wrong_password_rejected(self, session):
        r = session.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong-pass-xyz"}, timeout=30)
        assert r.status_code in (401, 403, 429), r.status_code


# --- REFRESH TOKEN ---
class TestRefreshToken:
    def test_refresh_returns_valid_access_token(self, session, tokens):
        r = session.post(f"{BASE_URL}/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]}, timeout=30)
        assert r.status_code == 200, f"{r.status_code}: {r.text[:300]}"
        new_token = r.json().get("token") or r.json().get("access_token")
        assert new_token, r.json()
        me = session.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {new_token}"}, timeout=30)
        assert me.status_code == 200, me.text[:300]
        assert me.json().get("email") == ADMIN_EMAIL

    def test_refresh_invalid_token(self, session):
        r = session.post(f"{BASE_URL}/api/auth/refresh", json={"refresh_token": "invalid-refresh-xyz"}, timeout=30)
        assert r.status_code in (401, 403), r.status_code


# --- PERSISTENT JWT SECRET (deps._load_or_create_persistent_jwt_secret) ---
class TestPersistentJwtSecret:
    def test_idempotent_and_persisted(self):
        sys.path.insert(0, "/app/backend")
        from pymongo import MongoClient
        from dotenv import dotenv_values as dv
        benv = dv("/app/backend/.env")
        mongo_url = os.environ.get("MONGO_URL") or benv.get("MONGO_URL")
        db_name = os.environ.get("DB_NAME") or benv.get("DB_NAME")
        os.environ.setdefault("MONGO_URL", mongo_url)
        os.environ.setdefault("DB_NAME", db_name)
        import deps
        s1 = deps._load_or_create_persistent_jwt_secret()
        s2 = deps._load_or_create_persistent_jwt_secret()
        assert s1 == s2, "persistent JWT secret is not stable across calls"
        assert len(s1) == 64, f"expected 64 hex chars, got {len(s1)}"
        int(s1, 16)  # hex validation
        client = MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
        doc = client[db_name].system_config.find_one({"_id": "jwt_secret"})
        client.close()
        assert doc is not None, "db.system_config _id=jwt_secret missing"
        assert doc.get("value") == s1
        assert doc.get("created_at")

    def test_env_secret_preferred_in_preview(self):
        benv = dotenv_values("/app/backend/.env")
        env_secret = benv.get("JWT_SECRET")
        if not env_secret:
            pytest.skip("no JWT_SECRET in backend/.env")
        sys.path.insert(0, "/app/backend")
        import deps
        assert deps.JWT_SECRET == env_secret, "env JWT_SECRET must take priority"
        assert deps.JWT_ALGORITHM == "HS256"
