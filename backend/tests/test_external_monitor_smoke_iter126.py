"""Iter126 — external_monitor endpoints smoke with a full 2FA-verified admin token."""
import os
import re
from pathlib import Path

import pyotp
import pytest
import requests
from dotenv import dotenv_values

fe = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or fe["REACT_APP_BACKEND_URL"]).rstrip("/")


@pytest.fixture(scope="module")
def headers():
    c = Path("/app/memory/test_credentials.md")
    if not c.exists():
        pytest.skip("no credentials file")
    txt = c.read_text()
    email = re.search(r'(?im)^\s*-\s*Email:\s*`([^`]+)`', txt).group(1)
    pwd = re.search(r'(?im)^\s*-\s*Password:\s*`([^`]+)`', txt).group(1)
    secret = re.search(r'`([A-Z2-7]{32})`', txt).group(1)
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": pwd}, timeout=30)
    assert r.status_code == 200, r.text[:300]
    tok = r.json()["token"]
    if r.json().get("requires_2fa"):
        r2 = s.post(f"{BASE_URL}/api/auth/verify-2fa", json={"code": pyotp.TOTP(secret).now()},
                    headers={"Authorization": f"Bearer {tok}"}, timeout=30)
        assert r2.status_code == 200, r2.text[:300]
        tok = r2.json().get("token") or r2.json().get("access_token")
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def target_id(headers):
    r = requests.get(f"{BASE_URL}/api/external-monitor/targets", headers=headers, timeout=60)
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    data = r.json()
    items = data if isinstance(data, list) else data.get("targets", [])
    if not items:
        pytest.skip("no external-monitor targets in preview DB")
    return items[0].get("id") or items[0].get("target_id")


# --- external_monitor read endpoints (module that had the syntax error) ---
@pytest.mark.parametrize("path", [
    "/api/external-monitor/targets",
    "/api/external-monitor/alerts",
])
def test_list_endpoints(headers, path):
    r = requests.get(f"{BASE_URL}{path}", headers=headers, timeout=60)
    assert r.status_code in (200, 404), f"{path} -> {r.status_code} {r.text[:200]}"


@pytest.mark.parametrize("suffix", [
    "insights", "dns-health", "public-ip-history", "speedtest/history",
    "multi-isp", "saas", "alert-rules", "traceroute-baseline",
])
def test_target_scoped_endpoints(headers, target_id, suffix):
    r = requests.get(f"{BASE_URL}/api/external-monitor/targets/{target_id}/{suffix}",
                     headers=headers, timeout=90)
    assert r.status_code != 500, f"{suffix} -> 500 {r.text[:300]}"
    assert r.status_code in (200, 404, 422, 503), f"{suffix} -> {r.status_code} {r.text[:200]}"
