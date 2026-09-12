"""Iter 88 — Test 3 new Nagios-clone features:
   #1 Scheduled Downtime (maintenance windows + suppression)
   #2 Soft/Hard states (max_check_attempts global + per-device override)
   #3 Parent-child dependencies (unreachable_dependency)
"""
import os
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://snmp-guardian.preview.emergentagent.com').rstrip('/')
CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"

ADMIN_EMAIL = "info@86bit.it"
ADMIN_PASS = "Ariel17051986@!@86"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
                      timeout=20)
    assert r.status_code == 200, f"login failed {r.status_code} {r.text}"
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---- Feature #1: Monitoring settings + Maintenance CRUD ----

class TestMonitoringSettings:
    def test_get_monitoring_settings(self, auth):
        r = requests.get(f"{BASE_URL}/api/settings/monitoring", headers=auth, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("max_check_attempts", "default", "min", "max"):
            assert k in d, f"missing key {k} in {d}"
        assert d["min"] == 1
        assert d["max"] == 20
        assert d["default"] == 5

    def test_post_monitoring_settings(self, auth):
        r = requests.post(f"{BASE_URL}/api/settings/monitoring?max_check_attempts=5",
                          headers=auth, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("max_check_attempts") == 5
        # verify GET reflects
        r2 = requests.get(f"{BASE_URL}/api/settings/monitoring", headers=auth, timeout=15)
        assert r2.json()["max_check_attempts"] == 5


class TestMaintenanceCRUD:
    created_id = None

    def test_list_maintenance(self, auth):
        r = requests.get(f"{BASE_URL}/api/maintenance/{CLIENT_ID}", headers=auth, timeout=15)
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_create_and_delete_maintenance(self, auth):
        payload = {
            "device_ip": "10.66.0.99",
            "start_time": "2099-01-01T00:00:00+00:00",
            "end_time": "2099-01-01T02:00:00+00:00",
            "description": "TEST_iter88 window",
        }
        r = requests.post(f"{BASE_URL}/api/maintenance/{CLIENT_ID}",
                          headers=auth, json=payload, timeout=15)
        assert r.status_code in (200, 201), r.text
        wid = r.json().get("id") or r.json().get("window", {}).get("id")
        assert wid, r.text
        # delete
        rd = requests.delete(f"{BASE_URL}/api/maintenance/{CLIENT_ID}/{wid}",
                             headers=auth, timeout=15)
        assert rd.status_code in (200, 204), rd.text


# ---- Info-card: maintenance + softstate + unreachable ----

class TestInfoCardMaintenance:
    def test_maintenance_device_card(self, auth):
        r = requests.get(f"{BASE_URL}/api/devices/by-ip/10.66.0.10/info-card",
                         headers=auth, timeout=20)
        assert r.status_code == 200, r.text
        status = r.json().get("status", {})
        assert status.get("in_maintenance") is True, f"expected in_maintenance=True, got {status}"
        mw = status.get("maintenance_window")
        assert mw, f"maintenance_window empty: {status}"


class TestInfoCardSoftState:
    def test_softstate_card(self, auth):
        r = requests.get(f"{BASE_URL}/api/devices/by-ip/10.66.0.20/info-card",
                         headers=auth, timeout=20)
        assert r.status_code == 200, r.text
        st = r.json().get("status", {})
        assert st.get("state_type") == "soft", f"state_type expected 'soft', got {st}"
        assert st.get("degraded") is True, f"degraded expected True, got {st}"
        assert st.get("failed_attempts") == 2, f"failed_attempts expected 2, got {st}"
        assert st.get("max_check_attempts") == 5, f"max_check_attempts expected 5, got {st}"

    def test_softstate_override_and_revert(self, auth):
        # Override
        r1 = requests.post(f"{BASE_URL}/api/devices/by-ip/10.66.0.20/monitoring-config",
                           headers=auth, json={"max_check_attempts": 8, "client_id": CLIENT_ID},
                           timeout=20)
        assert r1.status_code == 200, r1.text
        assert r1.json().get("max_check_attempts") == 8
        # Verify in info-card
        rc = requests.get(f"{BASE_URL}/api/devices/by-ip/10.66.0.20/info-card",
                          headers=auth, timeout=20)
        assert rc.status_code == 200
        assert rc.json()["status"].get("max_check_attempts") == 8, rc.json()["status"]
        # Revert
        r2 = requests.post(f"{BASE_URL}/api/devices/by-ip/10.66.0.20/monitoring-config",
                           headers=auth, json={"max_check_attempts": None, "client_id": CLIENT_ID},
                           timeout=20)
        assert r2.status_code == 200, r2.text


class TestInfoCardDependency:
    def test_unreachable_dependency(self, auth):
        r = requests.get(f"{BASE_URL}/api/devices/by-ip/10.66.0.50/info-card",
                         headers=auth, timeout=20)
        assert r.status_code == 200, r.text
        st = r.json().get("status", {})
        assert st.get("parent_ip") == "10.66.0.1", st
        assert st.get("parent_status") in ("offline", "down"), st
        assert st.get("unreachable_dependency") is True, st

    def test_set_parent_and_revert(self, auth):
        r1 = requests.post(f"{BASE_URL}/api/devices/by-ip/10.66.0.50/parent",
                           headers=auth, json={"parent_ip": "10.66.0.99", "client_id": CLIENT_ID},
                           timeout=20)
        assert r1.status_code == 200, r1.text
        assert r1.json().get("parent_ip") == "10.66.0.99"
        # verify card
        rc = requests.get(f"{BASE_URL}/api/devices/by-ip/10.66.0.50/info-card",
                          headers=auth, timeout=20)
        assert rc.json()["status"].get("parent_ip") == "10.66.0.99"
        # revert
        r2 = requests.post(f"{BASE_URL}/api/devices/by-ip/10.66.0.50/parent",
                           headers=auth, json={"parent_ip": "10.66.0.1", "client_id": CLIENT_ID},
                           timeout=20)
        assert r2.status_code == 200, r2.text
        assert r2.json().get("parent_ip") == "10.66.0.1"


# ---- Liveness regression: device ICMP-ok normal ----

class TestLivenessRegression:
    def test_normal_device_card(self, auth):
        r = requests.get(f"{BASE_URL}/api/devices/by-ip/192.168.1.3/info-card",
                         headers=auth, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "status" in d
        # Make sure the card still has icmp_reachable / snmp_reachable structure
        st = d["status"]
        assert "icmp_reachable" in st or "reachable" in st
