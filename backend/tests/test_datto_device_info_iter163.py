# Datto RMM device-info ('Sistema e utente') endpoint tests - iteration 163
import os
import pyotp
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
CID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"
EMAIL = "info@86bit.it"
PWD = "Ariel17051986@!@86"
TOTP = "NMHDJNO53WLTOSREUXWERE6FDH5TAKC3"
FORBIDDEN = {"serial", "serial_number", "bios", "memory", "disks", "antivirus", "raw_enc", "uid",
             "audit", "hardware", "cpu", "mac", "mac_list", "ip_list"}
EXPECTED = ["operating_system", "os_version", "os_architecture", "last_logged_user", "domain",
            "last_reboot", "reboot_required", "online", "last_seen", "device_type", "site_name",
            "description", "fetched_at"]


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    r = sess.post(f"{BASE_URL}/api/auth/login", json={"email": EMAIL, "password": PWD})
    assert r.status_code == 200, r.text
    d = r.json()
    tok = d.get("token")
    if d.get("requires_2fa"):
        r2 = sess.post(f"{BASE_URL}/api/auth/verify-2fa", json={"code": pyotp.TOTP(TOTP).now()},
                       headers={"Authorization": f"Bearer {tok}"})
        assert r2.status_code == 200, r2.text
        tok = r2.json()["token"]
    sess.headers["Authorization"] = f"Bearer {tok}"
    return sess


def _check(d):
    assert d["found"] is True
    for k in EXPECTED:
        assert k in d, k
    leaked = FORBIDDEN & set(d.keys())
    assert not leaked, leaked
    s = str(d).lower()
    assert "serial" not in s and "antivirus" not in s and "bios" not in s


def test_by_client_ip(s):
    r = s.get(f"{BASE_URL}/api/datto/device-info", params={"client_id": CID, "ip": "10.10.1.10"})
    assert r.status_code == 200
    d = r.json()
    print(d)
    _check(d)
    assert d["name"] == "SRVDATI86B"
    assert d["operating_system"]


def test_by_ip_list_secondary(s):
    r = s.get(f"{BASE_URL}/api/datto/device-info", params={"client_id": CID, "ip": "10.10.1.139"})
    assert r.status_code == 200 and r.json()["found"] is True
    assert r.json()["name"] == "SRVDATI86B"


def test_by_mac_only(s):
    r = s.get(f"{BASE_URL}/api/datto/device-info", params={"mac": "00:15:5D:01:79:0D"})
    assert r.status_code == 200
    _check(r.json())
    assert r.json()["name"] == "SRVDATI86B"


def test_by_mac_lowercase_dash(s):
    r = s.get(f"{BASE_URL}/api/datto/device-info", params={"mac": "00-15-5d-01-79-0d"})
    assert r.status_code == 200 and r.json()["found"] is True


def test_mac_secondary_list(s):
    r = s.get(f"{BASE_URL}/api/datto/device-info", params={"mac": "00:15:5D:01:72:02"})
    assert r.json().get("name") == "SRVDATI86B"


def test_no_params_400(s):
    r = s.get(f"{BASE_URL}/api/datto/device-info")
    assert r.status_code == 400


def test_ip_without_client_400(s):
    r = s.get(f"{BASE_URL}/api/datto/device-info", params={"ip": "10.10.1.10"})
    assert r.status_code == 400


def test_unknown_found_false(s):
    r = s.get(f"{BASE_URL}/api/datto/device-info", params={"client_id": CID, "ip": "10.254.254.254"})
    assert r.status_code == 200 and r.json() == {"found": False}
    r = s.get(f"{BASE_URL}/api/datto/device-info", params={"mac": "AA:BB:CC:00:11:22"})
    assert r.json() == {"found": False}


def test_wrong_client_found_false(s):
    r = s.get(f"{BASE_URL}/api/datto/device-info", params={"client_id": "nonexistent-client", "ip": "10.10.1.10"})
    assert r.status_code == 200 and r.json()["found"] is False


def test_unauth():
    r = requests.get(f"{BASE_URL}/api/datto/device-info", params={"client_id": CID, "ip": "10.10.1.10"})
    assert r.status_code in (401, 403)


def test_switch_ports_datto_neighbor(s):
    # requires seeded discovered_endpoints on 10.10.41.222 port 3
    r = s.get(f"{BASE_URL}/api/devices/10.10.41.222/switch-ports", params={"client_id": CID})
    assert r.status_code == 200
    p = next((x for x in r.json()["ports"] if x.get("idx") == 3), None)
    assert p and p.get("neighbor"), p
    print(p["neighbor"])
    assert p["neighbor"]["match_source"] == "datto_rmm"
