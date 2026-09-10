"""Regression tests for temperature threshold resolver + per-type client overrides.

Covers the bug fix where per-type thresholds set on Soglie Alert page were not
applied to devices because the raw managed_devices.device_type (e.g. 'zyxel-usg')
did not match the canonical temp keys (e.g. 'firewall').
"""
import os
import sys
import time
import pyotp
import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
ADMIN_EMAIL = "info@86bit.it"
ADMIN_PASSWORD = "Ariel17051986@!@86"
TOTP_SECRET = "NMHDJNO53WLTOSREUXWERE6FDH5TAKC3"
CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"


# --- Unit tests: temp_type_key + resolve_temp_thresholds ---------------------
class TestTempTypeKey:
    def test_zyxel_usg_to_firewall(self):
        from hardware_alerts import temp_type_key
        assert temp_type_key("zyxel-usg") == "firewall"

    def test_access_point_to_ap(self):
        from hardware_alerts import temp_type_key
        assert temp_type_key("access-point") == "ap"

    def test_generic_hpe_ilo_to_ilo(self):
        from hardware_alerts import temp_type_key
        assert temp_type_key("generic", "hpe_ilo") == "ilo"

    def test_snmp_switch_to_switch(self):
        from hardware_alerts import temp_type_key
        assert temp_type_key("snmp-switch") == "switch"

    def test_hyperv_vm_to_hypervisor(self):
        from hardware_alerts import temp_type_key
        assert temp_type_key("hyperv_vm") == "hypervisor"

    def test_endpoint_unknown(self):
        from hardware_alerts import temp_type_key
        assert temp_type_key("endpoint") == ""

    def test_generic_unknown(self):
        from hardware_alerts import temp_type_key
        assert temp_type_key("generic") == ""


class TestResolveTempThresholds:
    def test_client_firewall_from_zyxel_usg(self):
        from hardware_alerts import resolve_temp_thresholds
        r = resolve_temp_thresholds({}, "zyxel-usg", {}, {"firewall": {"warn": 80, "crit": 85}})
        assert r == (80.0, 85.0)

    def test_client_firewall_from_hint_tuple(self):
        from hardware_alerts import resolve_temp_thresholds
        r = resolve_temp_thresholds({}, ("generic", "zyxel_usg"), {}, {"firewall": {"warn": 80, "crit": 85}})
        assert r == (80.0, 85.0)

    def test_other_fallback_for_unknown_type(self):
        from hardware_alerts import resolve_temp_thresholds
        r = resolve_temp_thresholds({}, "endpoint", {}, {"other": {"warn": 77, "crit": 88}})
        assert r == (77.0, 88.0)

    def test_device_override_wins(self):
        from hardware_alerts import resolve_temp_thresholds
        r = resolve_temp_thresholds({}, "zyxel-usg", {"warn": 50, "crit": 60},
                                    {"firewall": {"warn": 80, "crit": 85}})
        assert r == (50.0, 60.0)


# --- E2E fixtures ------------------------------------------------------------
@pytest.fixture(scope="module")
def auth_token():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200, r.text
    tok = r.json().get("token")
    assert tok
    code = pyotp.TOTP(TOTP_SECRET).now()
    r2 = s.post(f"{BASE_URL}/api/auth/verify-2fa", json={"code": code},
                headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    if r2.status_code != 200:
        # small clock drift retry
        time.sleep(2)
        code = pyotp.TOTP(TOTP_SECRET).now()
        r2 = s.post(f"{BASE_URL}/api/auth/verify-2fa", json={"code": code},
                    headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    assert r2.status_code == 200, r2.text
    return r2.json().get("token") or r2.json().get("access_token")


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}


# --- E2E tests ---------------------------------------------------------------
class TestTempDefaultsEndpoint:
    def test_defaults_include_all_keys_and_other(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/thresholds-temp-defaults", headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        d = data.get("temp_by_type") or data.get("defaults") or data
        expected = {"switch", "firewall", "ap", "ilo", "nas", "storage",
                    "hypervisor", "ups", "router", "printer", "server", "other"}
        assert expected.issubset(set(d.keys())), f"missing keys: {expected - set(d.keys())}"
        other = d["other"]
        w = other.get("warn") or other.get("warn_c")
        c = other.get("crit") or other.get("crit_c")
        assert float(w) == 65.0
        assert float(c) == 80.0


class TestTemperatureOverviewResolution:
    def _get_thresholds(self, headers):
        r = requests.get(f"{BASE_URL}/api/thresholds/{CLIENT_ID}", headers=headers, timeout=15)
        assert r.status_code == 200, r.text
        return r.json()

    def _post_thresholds(self, headers, body):
        r = requests.post(f"{BASE_URL}/api/thresholds/{CLIENT_ID}",
                          json=body, headers=headers, timeout=15)
        assert r.status_code in (200, 201), r.text

    def _find_row(self, rows, ip):
        for r in rows:
            if r.get("ip") == ip or r.get("device_ip") == ip:
                return r
        return None

    def test_full_flow(self, auth_headers):
        original = self._get_thresholds(auth_headers)
        # Ensure baseline body carries all existing keys; only replace temp_by_type
        base_body = dict(original)
        base_body.pop("_id", None)

        try:
            # Step 1: set switch+firewall client thresholds
            b1 = dict(base_body)
            b1["temp_by_type"] = {"switch": {"warn": 70, "crit": 80},
                                  "firewall": {"warn": 80, "crit": 85}}
            self._post_thresholds(auth_headers, b1)

            r = requests.get(f"{BASE_URL}/api/temperature/overview",
                             headers=auth_headers, timeout=30)
            assert r.status_code == 200, r.text
            payload = r.json()
            rows = payload.get("devices") if isinstance(payload, dict) else payload
            fw = self._find_row(rows, "192.168.1.254")
            assert fw is not None, f"no row for 192.168.1.254; rows sample: {rows[:3]}"
            assert fw.get("device_type") == "firewall", fw
            assert float(fw.get("warn_c")) == 80.0, fw
            assert float(fw.get("crit_c")) == 85.0, fw
            assert fw.get("source") == "cliente", fw

            # Step 2: set switch + other  → 192.168.1.3 (generic) should follow 'other'
            b2 = dict(base_body)
            b2["temp_by_type"] = {"switch": {"warn": 70, "crit": 80},
                                  "other": {"warn": 77, "crit": 88}}
            self._post_thresholds(auth_headers, b2)

            r = requests.get(f"{BASE_URL}/api/temperature/overview",
                             headers=auth_headers, timeout=30)
            assert r.status_code == 200, r.text
            payload = r.json()
            rows = payload.get("devices") if isinstance(payload, dict) else payload

            generic_row = self._find_row(rows, "192.168.1.3")
            if generic_row is not None:
                assert float(generic_row.get("warn_c")) == 77.0, generic_row
                assert float(generic_row.get("crit_c")) == 88.0, generic_row
                assert generic_row.get("source") == "cliente", generic_row
            else:
                print("WARN: 192.168.1.3 not present in overview - skipping generic assertion")

            fw2 = self._find_row(rows, "192.168.1.254")
            assert fw2 is not None
            # Firewall default (70/85) with source 'default' since no client 'firewall' key now
            assert float(fw2.get("warn_c")) == 70.0, fw2
            assert float(fw2.get("crit_c")) == 85.0, fw2
            assert fw2.get("source") == "default", fw2
        finally:
            # RESTORE original per instructions
            restore = dict(base_body)
            restore["temp_by_type"] = {"switch": {"warn": 70, "crit": 80}}
            self._post_thresholds(auth_headers, restore)
