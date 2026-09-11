"""Iter144 API-level test for /api/devices/shutdown-diagnosis/{ip}"""
import os, requests, pyotp, time, sys

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://noc-alert-hub-2.preview.emergentagent.com").rstrip("/")
EMAIL = "info@86bit.it"
PASSWORD = "Ariel17051986@!@86"
TOTP = "NMHDJNO53WLTOSREUXWERE6FDH5TAKC3"
CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"
IP = "192.168.1.254"


def get_token():
    r = requests.post(f"{BASE}/api/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=15)
    assert r.status_code == 200, r.text
    tok = r.json().get("token") or r.json().get("access_token")
    # verify 2fa
    code = pyotp.TOTP(TOTP).now()
    r2 = requests.post(f"{BASE}/api/auth/verify-2fa", json={"code": code}, headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r2.status_code == 200, r2.text
    final = r2.json().get("token") or r2.json().get("access_token") or tok
    return final


def test_unauth():
    r = requests.get(f"{BASE}/api/devices/shutdown-diagnosis/{IP}?client_id={CLIENT_ID}", timeout=15)
    print("UNAUTH status:", r.status_code)
    assert r.status_code in (401, 403), r.text


def test_diag_seeded():
    tok = get_token()
    h = {"Authorization": f"Bearer {tok}"}
    r = requests.get(f"{BASE}/api/devices/shutdown-diagnosis/{IP}?client_id={CLIENT_ID}", headers=h, timeout=30)
    print("SEEDED status:", r.status_code)
    print("SEEDED body:", r.text[:2000])
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["verdict"] in {"crash", "intentional", "disconnected", "reachable_elsewhere", "unknown"}
    assert 0 <= d["confidence"] <= 100
    assert "label" in d and "summary" in d
    ev = d.get("evidence", [])
    assert len(ev) == 3, f"expected 3 evidence, got {len(ev)}"
    kinds = [e.get("kind") for e in ev]
    assert set(kinds) == {"port", "schedule", "datto"}, kinds
    assert "offline_since" in d
    # Expected specifics per problem statement
    assert d["verdict"] == "crash", d
    port_ev = next(e for e in ev if e["kind"] == "port")
    assert port_ev.get("level") == "crit", port_ev
    sched_ev = next(e for e in ev if e["kind"] == "schedule")
    assert "orario" in (sched_ev.get("title", "") + sched_ev.get("summary", "")).lower()
    datto_ev = next(e for e in ev if e["kind"] == "datto")
    assert datto_ev.get("level") == "na", datto_ev
    print("SEEDED verdict OK:", d["verdict"], d["confidence"])


def test_unknown_ip():
    tok = get_token()
    h = {"Authorization": f"Bearer {tok}"}
    r = requests.get(f"{BASE}/api/devices/shutdown-diagnosis/10.99.99.99?client_id={CLIENT_ID}", headers=h, timeout=30)
    print("UNKNOWN status:", r.status_code, r.text[:500])
    assert r.status_code == 200
    v = r.json().get("verdict")
    assert v in {"unknown", "crash", "intentional", "disconnected", "reachable_elsewhere"}


if __name__ == "__main__":
    test_unauth()
    test_diag_seeded()
    test_unknown_ip()
    print("ALL API TESTS PASSED")
