"""Cleanup: delete QA Wizard test clients created by the New Client Wizard e2e test."""
import os
import pyotp
import requests
from dotenv import dotenv_values

BASE = (os.environ.get("REACT_APP_BACKEND_URL")
        or dotenv_values("/app/frontend/.env").get("REACT_APP_BACKEND_URL")).rstrip("/")
EMAIL, PWD = "info@86bit.it", "Ariel17051986@!@86"
SECRET = "NMHDJNO53WLTOSREUXWERE6FDH5TAKC3"

s = requests.Session()
r = s.post(f"{BASE}/api/auth/login", json={"email": EMAIL, "password": PWD}, timeout=30)
r.raise_for_status()
tok = r.json().get("token")
s.headers["Authorization"] = f"Bearer {tok}"
if r.json().get("requires_2fa"):
    r2 = s.post(f"{BASE}/api/auth/verify-2fa", json={"code": pyotp.TOTP(SECRET).now()}, timeout=30)
    r2.raise_for_status()
    s.headers["Authorization"] = f"Bearer {r2.json()['token']}"

lst = s.get(f"{BASE}/api/clients", timeout=60).json()
items = lst if isinstance(lst, list) else (lst.get("clients") or lst.get("items") or [])
for c in items:
    if str(c.get("name", "")).startswith("QA Wizard"):
        d = s.delete(f"{BASE}/api/clients/{c['id']}", timeout=60)
        print("DELETE", c["name"], c["id"], d.status_code)
print("done")
