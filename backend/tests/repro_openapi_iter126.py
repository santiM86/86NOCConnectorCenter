"""Iter126 — repro: /openapi.json 500 due to `from __future__ import annotations` + body model."""
import os
import re
from pathlib import Path

import pyotp
import requests
from dotenv import dotenv_values

fe = dotenv_values("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or fe["REACT_APP_BACKEND_URL"]).rstrip("/")
c = Path("/app/memory/test_credentials.md").read_text()
EMAIL = re.search(r'(?im)^\s*-\s*Email:\s*`([^`]+)`', c).group(1)
PWD = re.search(r'(?im)^\s*-\s*Password:\s*`([^`]+)`', c).group(1)
SECRET = re.search(r'`([A-Z2-7]{32})`', c).group(1)

s = requests.Session()
r = s.post(f"{BASE_URL}/api/auth/login", json={"email": EMAIL, "password": PWD}, timeout=30)
tok = r.json()["token"]
r = s.post(f"{BASE_URL}/api/auth/verify-2fa", json={"code": pyotp.TOTP(SECRET).now()},
           headers={"Authorization": f"Bearer {tok}"}, timeout=30)
full = r.json().get("token") or r.json().get("access_token")
H = {"Authorization": f"Bearer {full}"}

print("internal /openapi.json ->", requests.get("http://localhost:8001/openapi.json", timeout=60).status_code)
print("/docs ->", requests.get("http://localhost:8001/docs", timeout=30).status_code)

# rotate-master-key with confirm=false (safe: should 400 before any rotation)
r = s.post(f"{BASE_URL}/api/admin/security/rotate-master-key", json={"confirm": False}, headers=H, timeout=60)
print("rotate-master-key(confirm=false) ->", r.status_code, r.text[:300])

for ep in ["/api/admin/security/encryption-status", "/api/admin/audit/recent"]:
    rr = s.get(f"{BASE_URL}{ep}", headers=H, timeout=60)
    print(ep, "->", rr.status_code, rr.text[:120])
