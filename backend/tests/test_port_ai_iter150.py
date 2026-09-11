"""Iter150 — Light regression on port-ai GET endpoints (no POSTs to save LLM cost)."""
import os
import sys
import pyotp
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "frontend", ".env"))

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
CID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"
IP = "10.10.41.220"
SECRET = "NMHDJNO53WLTOSREUXWERE6FDH5TAKC3"


def _token():
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login", json={"email": "info@86bit.it", "password": "Ariel17051986@!@86"})
    assert r.status_code == 200, r.text
    tok = r.json()["token"]
    r2 = s.post(f"{BASE}/api/auth/verify-2fa", json={"code": pyotp.TOTP(SECRET).now()},
                headers={"Authorization": f"Bearer {tok}"})
    assert r2.status_code == 200, r2.text
    return r2.json()["token"]


def test_unauth_audit_403_401():
    r = requests.get(f"{BASE}/api/devices/{IP}/switch-ports/ai-audit", params={"client_id": CID})
    assert r.status_code in (401, 403), r.status_code


def test_unauth_explain_403_401():
    r = requests.get(f"{BASE}/api/devices/{IP}/switch-ports/1/ai-explain", params={"client_id": CID})
    assert r.status_code in (401, 403), r.status_code


def test_get_audit_latest():
    t = _token()
    r = requests.get(f"{BASE}/api/devices/{IP}/switch-ports/ai-audit",
                     params={"client_id": CID}, headers={"Authorization": f"Bearer {t}"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert "latest" in j and "history" in j
    assert j["latest"] is not None, "expected pre-seeded audit"
    assert "result" in j["latest"]
    print("audit latest keys:", list(j["latest"]["result"].keys()))


def test_get_explain_port1():
    t = _token()
    r = requests.get(f"{BASE}/api/devices/{IP}/switch-ports/1/ai-explain",
                     params={"client_id": CID}, headers={"Authorization": f"Bearer {t}"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["latest"] is not None
    v = j["latest"]["result"].get("verdict")
    print("explain port1 verdict:", v)
    assert v, "no verdict"


def test_switch_ports_habit_schedule():
    t = _token()
    r = requests.get(f"{BASE}/api/devices/{IP}/switch-ports",
                     params={"client_id": CID}, headers={"Authorization": f"Bearer {t}"})
    assert r.status_code == 200, r.text
    j = r.json()
    ports = j.get("ports") or j.get("items") or j
    # find idx=8
    by_idx = {int(p["idx"]): p for p in (ports if isinstance(ports, list) else []) if p.get("idx") is not None}
    assert 8 in by_idx, list(by_idx.keys())
    p8 = by_idx[8]
    print("port8 habit:", p8.get("habit"))
