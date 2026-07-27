"""
Device Profile Library Tests - iteration_55
Tests for the new Device Profile Library feature:
- GET /api/device-profiles (list all profiles)
- GET /api/device-profiles/{key} (single profile)
- POST /api/device-profiles/fingerprint (match device identity)
- PUT /api/device-profiles/{key}/override (admin override)
- DELETE /api/device-profiles/{key}/override (reset override)
- POST /api/device-profiles/apply (apply profile to device)
- GET /api/device-profiles/list/vendors (dropdown helper)
"""
import pytest
import requests
import os
from datetime import datetime

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# Test credentials
ADMIN_EMAIL = "admin@86bit.it"
ADMIN_PASSWORD = "password"
VIEWER_EMAIL = "tv@86bit.it"
VIEWER_PASSWORD = "Tv86bit!2026"
TEST_CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"

# Expected profile keys (10 seed profiles)
EXPECTED_PROFILE_KEYS = [
    "hp_procurve", "synology_dsm", "qnap_qts", "fortinet_fortigate",
    "unifi", "zyxel_usg", "apc_ups", "cisco_catalyst", "dell_idrac", "generic_snmp"
]


@pytest.fixture(scope="module")
def admin_token():
    """Get admin auth token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD
    })
    assert response.status_code == 200, f"Admin login failed: {response.text}"
    return response.json().get("token")


@pytest.fixture(scope="module")
def viewer_token():
    """Get viewer auth token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": VIEWER_EMAIL,
        "password": VIEWER_PASSWORD
    })
    assert response.status_code == 200, f"Viewer login failed: {response.text}"
    return response.json().get("token")


@pytest.fixture
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


@pytest.fixture
def viewer_headers(viewer_token):
    return {"Authorization": f"Bearer {viewer_token}", "Content-Type": "application/json"}


class TestDeviceProfilesList:
    """Tests for GET /api/device-profiles"""

    def test_list_profiles_requires_auth(self):
        """Endpoint requires authentication"""
        response = requests.get(f"{BASE_URL}/api/device-profiles")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"

    def test_list_profiles_returns_10_profiles(self, admin_headers):
        """Returns exactly 10 seed profiles"""
        response = requests.get(f"{BASE_URL}/api/device-profiles", headers=admin_headers)
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        assert "seed_version" in data, "Missing seed_version"
        assert "count" in data, "Missing count"
        assert "profiles" in data, "Missing profiles array"
        assert data["count"] == 10, f"Expected 10 profiles, got {data['count']}"
        assert len(data["profiles"]) == 10, f"Expected 10 profiles in array"

    def test_list_profiles_has_all_expected_keys(self, admin_headers):
        """All 10 expected profile keys are present"""
        response = requests.get(f"{BASE_URL}/api/device-profiles", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        
        profile_keys = [p["key"] for p in data["profiles"]]
        for expected_key in EXPECTED_PROFILE_KEYS:
            assert expected_key in profile_keys, f"Missing profile key: {expected_key}"

    def test_profile_structure(self, admin_headers):
        """Each profile has required fields"""
        response = requests.get(f"{BASE_URL}/api/device-profiles", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        
        required_fields = ["key", "vendor", "family", "label", "snmp", "web_console", 
                          "oids", "thresholds", "capabilities", "fingerprint"]
        
        for profile in data["profiles"]:
            for field in required_fields:
                assert field in profile, f"Profile {profile.get('key')} missing field: {field}"
            
            # Check SNMP structure
            snmp = profile.get("snmp", {})
            assert "port" in snmp, f"Profile {profile['key']} missing snmp.port"
            assert "version" in snmp, f"Profile {profile['key']} missing snmp.version"
            
            # Check web_console structure
            wc = profile.get("web_console", {})
            assert "port" in wc, f"Profile {profile['key']} missing web_console.port"
            assert "scheme" in wc, f"Profile {profile['key']} missing web_console.scheme"


class TestDeviceProfileSingle:
    """Tests for GET /api/device-profiles/{key}"""

    def test_get_synology_profile(self, admin_headers):
        """Get synology_dsm profile"""
        response = requests.get(f"{BASE_URL}/api/device-profiles/synology_dsm", headers=admin_headers)
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        assert data["key"] == "synology_dsm"
        assert data["vendor"] == "Synology"
        assert data["family"] == "nas"
        assert "oids" in data
        assert "thresholds" in data

    def test_get_hp_procurve_profile(self, admin_headers):
        """Get hp_procurve profile"""
        response = requests.get(f"{BASE_URL}/api/device-profiles/hp_procurve", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        
        assert data["key"] == "hp_procurve"
        assert data["vendor"] == "HP / Aruba"
        assert data["family"] == "switch"

    def test_get_nonexistent_profile_returns_404(self, admin_headers):
        """Non-existent profile key returns 404"""
        response = requests.get(f"{BASE_URL}/api/device-profiles/nonexistent_profile_xyz", headers=admin_headers)
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"


class TestFingerprintMatching:
    """Tests for POST /api/device-profiles/fingerprint"""

    def test_fingerprint_synology_by_oid(self, admin_headers):
        """Match Synology by sysObjectID prefix"""
        response = requests.post(
            f"{BASE_URL}/api/device-profiles/fingerprint",
            headers=admin_headers,
            json={"sysobjectid": "1.3.6.1.4.1.6574.1", "sysdescr": "Linux DiskStation Synology"}
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        assert data["matched"] is True, "Should match Synology"
        assert data["confidence"] == "high", f"Expected high confidence, got {data['confidence']}"
        assert data["profile"]["key"] == "synology_dsm"

    def test_fingerprint_hp_by_sysdescr(self, admin_headers):
        """Match HP ProCurve by sysDescr pattern (medium confidence)"""
        response = requests.post(
            f"{BASE_URL}/api/device-profiles/fingerprint",
            headers=admin_headers,
            json={"sysdescr": "HP ProCurve J9773A Switch"}
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        assert data["matched"] is True, "Should match HP ProCurve"
        assert data["confidence"] == "medium", f"Expected medium confidence, got {data['confidence']}"
        assert data["profile"]["key"] == "hp_procurve"

    def test_fingerprint_fortinet_by_oid(self, admin_headers):
        """Match Fortinet FortiGate by sysObjectID"""
        response = requests.post(
            f"{BASE_URL}/api/device-profiles/fingerprint",
            headers=admin_headers,
            json={"sysobjectid": "1.3.6.1.4.1.12356.101"}
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        assert data["matched"] is True, "Should match Fortinet"
        assert data["confidence"] == "high", f"Expected high confidence, got {data['confidence']}"
        assert data["profile"]["key"] == "fortinet_fortigate"

    def test_fingerprint_no_match(self, admin_headers):
        """Unknown device returns matched=false"""
        response = requests.post(
            f"{BASE_URL}/api/device-profiles/fingerprint",
            headers=admin_headers,
            json={"sysdescr": "Unknown Mystery Device 9000"}
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        assert data["matched"] is False, "Should not match any profile"

    def test_fingerprint_cisco_by_oid(self, admin_headers):
        """Match Cisco by sysObjectID prefix"""
        response = requests.post(
            f"{BASE_URL}/api/device-profiles/fingerprint",
            headers=admin_headers,
            json={"sysobjectid": "1.3.6.1.4.1.9.1.2066"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["matched"] is True
        assert data["profile"]["key"] == "cisco_catalyst"

    def test_fingerprint_qnap_by_oid(self, admin_headers):
        """Match QNAP by sysObjectID prefix"""
        response = requests.post(
            f"{BASE_URL}/api/device-profiles/fingerprint",
            headers=admin_headers,
            json={"sysobjectid": "1.3.6.1.4.1.24681.1"}
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["matched"] is True
        assert data["profile"]["key"] == "qnap_qts"


class TestProfileOverride:
    """Tests for PUT/DELETE /api/device-profiles/{key}/override"""

    def test_override_requires_admin(self, viewer_headers):
        """Viewer cannot save override (403)"""
        response = requests.put(
            f"{BASE_URL}/api/device-profiles/synology_dsm/override",
            headers=viewer_headers,
            json={"thresholds": {"disk_temp_crit_c": 60}}
        )
        assert response.status_code == 403, f"Expected 403, got {response.status_code}"

    def test_override_nonexistent_profile_returns_404(self, admin_headers):
        """Override on non-existent profile returns 404"""
        response = requests.put(
            f"{BASE_URL}/api/device-profiles/nonexistent_xyz/override",
            headers=admin_headers,
            json={"thresholds": {"cpu_warn_pct": 80}}
        )
        assert response.status_code == 404

    def test_save_and_verify_override(self, admin_headers):
        """Save override and verify it's applied"""
        # Save override
        override_data = {"thresholds": {"disk_temp_crit_c": 60}}
        response = requests.put(
            f"{BASE_URL}/api/device-profiles/synology_dsm/override",
            headers=admin_headers,
            json=override_data
        )
        assert response.status_code == 200, f"Failed to save override: {response.text}"
        
        # Verify override is applied
        response = requests.get(f"{BASE_URL}/api/device-profiles/synology_dsm", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        
        assert data.get("_has_overrides") is True, "Should have _has_overrides=true"
        assert data["thresholds"]["disk_temp_crit_c"] == 60, "Override not applied"

    def test_delete_override(self, admin_headers):
        """Delete override resets to seed values"""
        # First ensure there's an override
        requests.put(
            f"{BASE_URL}/api/device-profiles/synology_dsm/override",
            headers=admin_headers,
            json={"thresholds": {"disk_temp_crit_c": 60}}
        )
        
        # Delete override
        response = requests.delete(
            f"{BASE_URL}/api/device-profiles/synology_dsm/override",
            headers=admin_headers
        )
        assert response.status_code == 200, f"Failed to delete override: {response.text}"
        
        # Verify override is removed
        response = requests.get(f"{BASE_URL}/api/device-profiles/synology_dsm", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        
        # _has_overrides should be False after deletion
        assert data.get("_has_overrides") is False, "Override should be removed"


class TestApplyProfile:
    """Tests for POST /api/device-profiles/apply"""

    def test_apply_requires_profile_or_match(self, admin_headers):
        """Apply without profile_key and no matching device returns 404"""
        response = requests.post(
            f"{BASE_URL}/api/device-profiles/apply",
            headers=admin_headers,
            json={"device_ip": "192.168.99.99"}  # Non-existent device
        )
        # Should return 404 because device doesn't exist and no profile_key given
        assert response.status_code == 404

    def test_apply_nonexistent_profile_returns_404(self, admin_headers):
        """Apply with non-existent profile_key returns 404"""
        response = requests.post(
            f"{BASE_URL}/api/device-profiles/apply",
            headers=admin_headers,
            json={"device_ip": "192.168.1.1", "profile_key": "nonexistent_xyz"}
        )
        assert response.status_code == 404

    def test_apply_requires_device_ip(self, admin_headers):
        """Apply without device_ip returns 400"""
        response = requests.post(
            f"{BASE_URL}/api/device-profiles/apply",
            headers=admin_headers,
            json={"profile_key": "hp_procurve"}
        )
        assert response.status_code == 400


class TestVendorsList:
    """Tests for GET /api/device-profiles/list/vendors"""

    def test_list_vendors_returns_10_items(self, admin_headers):
        """Returns 10 vendor items for dropdown"""
        response = requests.get(f"{BASE_URL}/api/device-profiles/list/vendors", headers=admin_headers)
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        
        assert "items" in data, "Missing items array"
        assert len(data["items"]) == 10, f"Expected 10 items, got {len(data['items'])}"

    def test_vendor_item_structure(self, admin_headers):
        """Each vendor item has key, vendor, family, label"""
        response = requests.get(f"{BASE_URL}/api/device-profiles/list/vendors", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        
        for item in data["items"]:
            assert "key" in item, "Missing key"
            assert "vendor" in item, "Missing vendor"
            assert "family" in item, "Missing family"
            assert "label" in item, "Missing label"


class TestConnectorAutoClassify:
    """Tests for connector auto-classification via device-report"""

    def test_connector_device_report_endpoint_exists(self, admin_headers):
        """Verify connector device-report endpoint exists (requires connector auth)"""
        # This endpoint requires connector HMAC auth, so we just verify it exists
        # by checking that it doesn't return 404
        response = requests.post(
            f"{BASE_URL}/api/connector/device-report",
            headers=admin_headers,
            json={"hostname": "test", "devices": []}
        )
        # Should return 401 (missing connector auth) not 404
        assert response.status_code in [401, 403, 422], f"Unexpected status: {response.status_code}"


class TestProfileSpecificDetails:
    """Tests for specific profile details"""

    def test_synology_has_api_endpoints(self, admin_headers):
        """Synology profile has API endpoints for DSM"""
        response = requests.get(f"{BASE_URL}/api/device-profiles/synology_dsm", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        
        assert "api_endpoints" in data, "Synology should have api_endpoints"
        api = data["api_endpoints"]
        assert "login" in api
        assert "system_info" in api

    def test_fortinet_has_api_endpoints(self, admin_headers):
        """Fortinet profile has API endpoints for FortiOS"""
        response = requests.get(f"{BASE_URL}/api/device-profiles/fortinet_fortigate", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        
        assert "api_endpoints" in data
        api = data["api_endpoints"]
        assert "vpn_tunnels" in api
        assert "ha_status" in api

    def test_apc_ups_has_battery_oids(self, admin_headers):
        """APC UPS profile has battery monitoring OIDs"""
        response = requests.get(f"{BASE_URL}/api/device-profiles/apc_ups", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        
        oids = data.get("oids", {})
        assert "upsAdvBatteryCapacity" in oids
        assert "upsAdvBatteryRunTime" in oids
        assert "upsBasicBatteryStatus" in oids

    def test_dell_idrac_has_redfish_endpoints(self, admin_headers):
        """Dell iDRAC profile has Redfish API endpoints"""
        response = requests.get(f"{BASE_URL}/api/device-profiles/dell_idrac", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        
        assert "api_endpoints" in data
        api = data["api_endpoints"]
        assert "redfish_systems" in api
        assert "redfish_thermal" in api

    def test_generic_snmp_is_fallback(self, admin_headers):
        """Generic SNMP profile has empty fingerprint (fallback)"""
        response = requests.get(f"{BASE_URL}/api/device-profiles/generic_snmp", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        
        fp = data.get("fingerprint", {})
        assert len(fp.get("sysobjectid_prefixes", [])) == 0
        assert len(fp.get("sysdescr_patterns", [])) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
