"""HTTP integration tests iter160: alert rules, dependencies, nic-groups, mac-history endpoints."""
import os
import time
import requests
import pyotp

BASE = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
EMAIL = "info@86bit.it"
PASSWORD = "Ariel17051986@!@86"
TOTP_SECRET = "NMHDJNO53WLTOSREUXWERE6FDH5TAKC3"
CID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"

s = requests.Session()


def _login():
    r = s.post(f"{BASE}/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200, r.text
    data = r.json()
    tok = data["token"]
    if data.get("requires_2fa"):
        # wait if close to boundary to avoid rejects
        code = pyotp.TOTP(TOTP_SECRET).now()
        r2 = s.post(f"{BASE}/api/auth/verify-2fa", json={"code": code}, headers={"Authorization": f"Bearer {tok}"})
        assert r2.status_code == 200, r2.text
        tok = r2.json()["token"]
    s.headers.update({"Authorization": f"Bearer {tok}"})


def test_01_metrics_list():
    _login()
    r = s.get(f"{BASE}/api/alert-rules/metrics")
    assert r.status_code == 200, r.text
    keys = {m["key"] for m in r.json()}
    assert {"packet_loss", "latency", "cpu", "ram", "disk", "temperature"} <= keys


_created_rules = []
_created_deps = []


def test_02_rule_crud_and_validation():
    # validation: scope=client missing client_id
    r = s.post(f"{BASE}/api/alert-rules", json={"name": "TEST_x", "metric": "cpu", "threshold": 90, "scope": "client"})
    assert r.status_code == 400, r.text
    # scope=device missing device_ip
    r = s.post(f"{BASE}/api/alert-rules", json={"name": "TEST_x", "metric": "cpu", "threshold": 90, "scope": "device", "client_id": CID})
    assert r.status_code == 400, r.text
    # create ok
    r = s.post(f"{BASE}/api/alert-rules", json={"name": "TEST_iter160_cpu", "metric": "cpu", "operator": ">", "threshold": 95,
                                                 "duration_min": 5, "severity": "high", "scope": "client", "client_id": CID})
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    _created_rules.append(rid)
    # list contains it
    r = s.get(f"{BASE}/api/alert-rules")
    assert r.status_code == 200
    assert any(x["id"] == rid for x in r.json())
    # update
    r = s.put(f"{BASE}/api/alert-rules/{rid}", json={"name": "TEST_iter160_cpu2", "metric": "cpu", "threshold": 88, "scope": "client", "client_id": CID})
    assert r.status_code == 200, r.text
    assert r.json()["threshold"] == 88 and r.json()["name"] == "TEST_iter160_cpu2"


def test_03_run_now():
    r = s.post(f"{BASE}/api/alert-rules/run")
    assert r.status_code == 200, r.text
    assert "emitted" in r.json()


def test_04_dependencies_crud_merge():
    r = s.post(f"{BASE}/api/alert-dependencies", json={"client_id": CID, "parent_ip": "10.250.250.1", "child_ips": ["10.250.250.2", "10.250.250.3"]})
    assert r.status_code == 200, r.text
    dep = r.json()
    _created_deps.append(dep["id"])
    assert sorted(dep["child_ips"]) == ["10.250.250.2", "10.250.250.3"]
    # merge: same parent new child
    r = s.post(f"{BASE}/api/alert-dependencies", json={"client_id": CID, "parent_ip": "10.250.250.1", "child_ips": ["10.250.250.4"]})
    assert r.status_code == 200, r.text
    assert sorted(r.json()["child_ips"]) == ["10.250.250.2", "10.250.250.3", "10.250.250.4"]
    # list
    r = s.get(f"{BASE}/api/alert-dependencies", params={"client_id": CID})
    assert r.status_code == 200
    assert any(d["parent_ip"] == "10.250.250.1" for d in r.json())
    # validation: child == parent only -> 400
    r = s.post(f"{BASE}/api/alert-dependencies", json={"client_id": CID, "parent_ip": "10.250.250.9", "child_ips": ["10.250.250.9"]})
    assert r.status_code == 400, r.text


def test_05_dependency_suggestions_and_nic_groups():
    r = s.get(f"{BASE}/api/alert-dependencies/suggestions", params={"client_id": CID})
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    r = s.get(f"{BASE}/api/clients/{CID}/nic-groups")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_06_nic_host_validation():
    r = s.post(f"{BASE}/api/clients/{CID}/nic-groups/host", json={"mac": "00:00:00:00:00:00", "host_ip": "1.2.3.4"})
    assert r.status_code == 400, r.text


def test_07_mac_history_shape():
    # likely 404 or no device; endpoint always returns 200 shape even if missing
    r = s.get(f"{BASE}/api/devices/by-ip/10.255.255.254/mac-history", params={"client_id": CID})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) >= {"current_mac", "history", "pending"}


def test_99_cleanup():
    for rid in _created_rules:
        s.delete(f"{BASE}/api/alert-rules/{rid}")
    for did in _created_deps:
        s.delete(f"{BASE}/api/alert-dependencies/{did}")
