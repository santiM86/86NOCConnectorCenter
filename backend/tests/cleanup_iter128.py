"""Cleanup TEST_ maintenance windows created by iter128 UI test + check /api/auth/me 403 origin."""
import requests, pyotp
from dotenv import dotenv_values

BASE = dotenv_values("/app/frontend/.env")["REACT_APP_BACKEND_URL"].rstrip("/")
S = "NMHDJNO53WLTOSREUXWERE6FDH5TAKC3"

r = requests.post(f"{BASE}/api/auth/login", json={"email": "info@86bit.it", "password": "Ariel17051986@!@86"}, timeout=30)
d = r.json()
pre = d.get("token")
print("login keys:", list(d.keys()), "requires_2fa:", d.get("requires_2fa"))
me_pre = requests.get(f"{BASE}/api/auth/me", headers={"Authorization": f"Bearer {pre}"}, timeout=30)
print("GET /api/auth/me with PRE-2FA token ->", me_pre.status_code, me_pre.text[:150])

tok = requests.post(f"{BASE}/api/auth/verify-2fa", json={"code": pyotp.TOTP(S).now()},
                    headers={"Authorization": f"Bearer {pre}"}, timeout=30).json()["token"]
h = {"Authorization": f"Bearer {tok}"}
print("GET /api/auth/me with FULL token ->", requests.get(f"{BASE}/api/auth/me", headers=h, timeout=30).status_code)

clients = requests.get(f"{BASE}/api/clients", headers=h, timeout=30).json()
for c in clients:
    ws = requests.get(f"{BASE}/api/maintenance/{c['id']}", headers=h, timeout=30).json()
    for w in ws:
        if w["title"].startswith("TEST_") or w["title"].startswith("Silenziato ora"):
            dd = requests.delete(f"{BASE}/api/maintenance/{c['id']}/{w['id']}", headers=h, timeout=30)
            print("deleted", w["title"], dd.status_code)
