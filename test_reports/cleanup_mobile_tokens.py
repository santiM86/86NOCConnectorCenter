"""Cleanup helper: revoke any TEST_QA_* mobile pairing tokens created during testing."""
import os
import pyotp
import requests
from dotenv import dotenv_values

BASE = (os.environ.get("REACT_APP_BACKEND_URL") or dotenv_values("/app/frontend/.env")["REACT_APP_BACKEND_URL"]).rstrip("/")
EMAIL = "info@86bit.it"
PWD = "Ariel17051986@!@86"
SECRET = "NMHDJNO53WLTOSREUXWERE6FDH5TAKC3"

s = requests.Session()
r = s.post(f"{BASE}/api/auth/login", json={"email": EMAIL, "password": PWD})
print("login", r.status_code, list(r.json().keys()) if r.ok else r.text[:200])
tok = r.json().get("token")
if r.json().get("requires_2fa"):
    r2 = s.post(f"{BASE}/api/auth/verify-2fa", json={"code": pyotp.TOTP(SECRET).now()},
                headers={"Authorization": f"Bearer {tok}"})
    print("verify-2fa", r2.status_code)
    tok = r2.json().get("token", tok)

h = {"Authorization": f"Bearer {tok}"}
lst = s.get(f"{BASE}/api/mobile/pairing", headers=h)
print("list", lst.status_code, lst.text[:400])
for d in lst.json().get("devices", []):
    dr = s.delete(f"{BASE}/api/mobile/pairing/{d['id']}", headers=h)
    print("revoke", d.get("device_label"), dr.status_code)

print("final", s.get(f"{BASE}/api/mobile/pairing", headers=h).text[:200])
