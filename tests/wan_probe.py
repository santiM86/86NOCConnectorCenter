import os, requests, pyotp, json
from dotenv import dotenv_values
BASE = dotenv_values("/app/frontend/.env")["REACT_APP_BACKEND_URL"].rstrip("/")
s = requests.Session()
r = s.post(f"{BASE}/api/auth/login", json={"email": "info@86bit.it", "password": "Ariel17051986@!@86"})
print("login", r.status_code, list(r.json().keys()))
d = r.json()
tok = d.get("token")
if d.get("requires_2fa"):
    code = pyotp.TOTP('NMHDJNO53WLTOSREUXWERE6FDH5TAKC3').now()
    r2 = s.post(f"{BASE}/api/auth/verify-2fa", json={"code": code}, headers={"Authorization": f"Bearer {tok}"})
    print("2fa", r2.status_code, r2.text[:200])
    tok = r2.json().get("token", tok)
H = {"Authorization": f"Bearer {tok}"}
ag = s.get(f"{BASE}/api/agents", headers=H)
print("agents", ag.status_code, type(ag.json()), str(ag.json())[:300])
cl = s.get(f"{BASE}/api/clients", headers=H)
clients = cl.json() if isinstance(cl.json(), list) else cl.json().get("clients", [])
print("clients", cl.status_code, len(clients))
found = []
for c in clients:
    cid = c.get("id") or c.get("_id")
    t = s.get(f"{BASE}/api/external-monitor/targets/{cid}", headers=H)
    if t.status_code == 200:
        tg = t.json()
        tl = tg if isinstance(tg, list) else tg.get("targets", [])
        if tl:
            found.append((c.get("name"), cid, len(tl)))
print("clients with wan targets:", found[:10])
fd = s.post(f"{BASE}/api/external-monitor/fault-diagnose", json={"client_id": found[0][1] if found else "x", "target": "1.1.1.1", "mode": "icmp"}, headers=H, timeout=120)
print("fault-diagnose", fd.status_code, fd.text[:300])
