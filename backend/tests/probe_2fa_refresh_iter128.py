"""Iter128 security probe: pre-2FA login returns refresh_token — can it be exchanged
for a fully-privileged token, bypassing the 2FA challenge?"""
import requests
from dotenv import dotenv_values

BASE = dotenv_values("/app/frontend/.env")["REACT_APP_BACKEND_URL"].rstrip("/")
s = requests.Session()
r = s.post(f"{BASE}/api/auth/login", json={"email": "info@86bit.it", "password": "Ariel17051986@!@86"}, timeout=30)
d = r.json()
rt = d.get("refresh_token")
print("refresh_token present pre-2FA:", bool(rt))
print("cookies set:", {k: v[:12] + "..." for k, v in s.cookies.get_dict().items()})
for path in ["/api/auth/refresh", "/api/auth/refresh-token"]:
    rr = s.post(f"{BASE}{path}", json={"refresh_token": rt}, timeout=30)
    print(path, "->", rr.status_code, rr.text[:200])
    if rr.status_code == 200:
        nt = rr.json().get("token") or rr.json().get("access_token")
        if nt:
            me = requests.get(f"{BASE}/api/auth/me", headers={"Authorization": f"Bearer {nt}"}, timeout=30)
            print("  /api/auth/me with refreshed token ->", me.status_code, me.text[:120])
