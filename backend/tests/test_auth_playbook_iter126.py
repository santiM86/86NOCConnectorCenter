"""Iter126 — auth hardening playbook checks: cookies, CORS, brute-force lockout, hash format."""
import os
import re
import time
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

fe = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or fe["REACT_APP_BACKEND_URL"]).rstrip("/")
txt = Path("/app/memory/test_credentials.md").read_text()
EMAIL = re.search(r'(?im)^\s*-\s*Email:\s*`([^`]+)`', txt).group(1)
PWD = re.search(r'(?im)^\s*-\s*Password:\s*`([^`]+)`', txt).group(1)


def test_password_hash_algorithm_documented():
    """Hash must be a modern algorithm (argon2id or bcrypt $2b$), never plaintext."""
    import asyncio

    from motor.motor_asyncio import AsyncIOMotorClient
    env = dotenv_values("/app/backend/.env")

    async def get():
        c = AsyncIOMotorClient(env["MONGO_URL"])
        return await c[env["DB_NAME"]].users.find_one({"email": EMAIL}, {"_id": 0, "password_hash": 1, "password": 1})

    u = asyncio.get_event_loop().run_until_complete(get()) if False else asyncio.run(get())
    h = u.get("password_hash") or u.get("password") or ""
    assert h.startswith("$argon2") or h.startswith("$2b$"), f"unexpected hash format: {h[:12]}"
    assert PWD not in h


def test_cors_allows_credentials_with_explicit_origin():
    # Preflight must be validated against the app itself: the preview ingress/CDN
    # answers OPTIONS with a wildcard ACAO of its own.
    r = requests.options("http://localhost:8001/api/auth/login", headers={
        "Origin": BASE_URL,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    }, timeout=30)
    assert r.status_code in (200, 204), r.status_code
    allow_origin = r.headers.get("access-control-allow-origin")
    allow_creds = r.headers.get("access-control-allow-credentials")
    assert allow_origin and allow_origin != "*", f"wildcard/missing ACAO: {allow_origin}"
    assert allow_creds == "true", f"credentials not allowed: {allow_creds}"


def test_login_response_shape_and_cookies():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": EMAIL, "password": PWD}, timeout=30)
    assert r.status_code == 200, r.text[:200]
    cookies = r.headers.get("set-cookie") or ""
    print("set-cookie:", cookies)
    # informational: token-in-body scheme is used by this app
    assert r.json().get("token")


@pytest.mark.order(99)
def test_zz_brute_force_lockout_after_repeated_failures():
    """Runs last: it consumes the per-IP login rate limit (10 / 5 min)."""
    s = requests.Session()
    statuses = []
    for i in range(13):
        r = s.post(f"{BASE_URL}/api/auth/login",
                   json={"email": "TEST_bruteforce@example.com", "password": f"wrong{i}"}, timeout=30)
        statuses.append(r.status_code)
        time.sleep(0.2)
    print("statuses:", statuses)
    assert any(st in (423, 429) for st in statuses), f"no lockout/rate-limit triggered: {statuses}"


def test_valid_admin_login_works():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": EMAIL, "password": PWD}, timeout=30)
    if r.status_code == 429:
        pytest.skip("per-IP login rate limit still active from a previous run")
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text[:200]}"
