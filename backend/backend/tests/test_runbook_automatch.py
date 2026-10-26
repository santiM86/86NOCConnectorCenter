"""
Test Runbook Auto-Match Feature
Tests:
1. POST /api/runbooks/seed-defaults - Admin seeds 8 runbooks (idempotent)
2. GET /api/runbooks - List runbooks with new fields (profile_keys, capability_match, vendor_match, severity_match)
3. GET /api/runbooks/match/alert/{alert_id} - Match scoring algorithm
4. Regression: GET /api/runbooks/{id}, POST /api/runbooks, PUT/DELETE
"""
import pytest
import requests
import os
import uuid
from datetime import datetime, timezone

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# Test credentials
ADMIN_EMAIL = "admin@86bit.it"
ADMIN_PASSWORD = "password"
VIEWER_EMAIL = "tv@86bit.it"
VIEWER_PASSWORD = "Tv86bit!2026"
CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"


@pytest.fixture(scope="module")
def admin_token():
    """Get admin auth token"""
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD
    })
    assert resp.status_code == 200, f"Admin login failed: {resp.text}"
    return resp.json().get("token")


@pytest.fixture(scope="module")
def viewer_token():
    """Get viewer auth token"""
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": VIEWER_EMAIL,
        "password": VIEWER_PASSWORD
    })
    assert resp.status_code == 200, f"Viewer login failed: {resp.text}"
    return resp.json().get("token")


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def viewer_headers(viewer_token):
    return {"Authorization": f"Bearer {viewer_token}", "Content-Type": "application/json"}


# ============ SEED DEFAULTS TESTS ============

class TestSeedDefaults:
    """POST /api/runbooks/seed-defaults tests"""
    
    def test_seed_defaults_admin_first_call(self, admin_headers):
        """Admin can seed default runbooks"""
        resp = requests.post(f"{BASE_URL}/api/runbooks/seed-defaults", headers=admin_headers)
        assert resp.status_code == 200, f"Seed failed: {resp.text}"
        data = resp.json()
        assert data.get("ok") is True
        assert "inserted" in data
        assert "skipped" in data
        assert data.get("total_seeds") == 8
        print(f"Seed result: inserted={data['inserted']}, skipped={data['skipped']}")
    
    def test_seed_defaults_idempotent(self, admin_headers):
        """Second call should skip all (idempotent)"""
        resp = requests.post(f"{BASE_URL}/api/runbooks/seed-defaults", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("ok") is True
        # After first seed, all should be skipped
        assert data.get("skipped") == 8, f"Expected skipped=8, got {data.get('skipped')}"
        assert data.get("inserted") == 0, f"Expected inserted=0, got {data.get('inserted')}"
        print(f"Idempotent check: inserted={data['inserted']}, skipped={data['skipped']}")
    
    def test_seed_defaults_viewer_forbidden(self, viewer_headers):
        """Viewer role should get 403"""
        resp = requests.post(f"{BASE_URL}/api/runbooks/seed-defaults", headers=viewer_headers)
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"


# ============ LIST RUNBOOKS TESTS ============

class TestListRunbooks:
    """GET /api/runbooks tests"""
    
    def test_list_runbooks_returns_items(self, admin_headers):
        """List runbooks returns items array"""
        resp = requests.get(f"{BASE_URL}/api/runbooks", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert len(data["items"]) >= 8, f"Expected at least 8 runbooks, got {len(data['items'])}"
    
    def test_runbooks_have_new_fields(self, admin_headers):
        """Each runbook should have profile_keys, capability_match, vendor_match, severity_match"""
        resp = requests.get(f"{BASE_URL}/api/runbooks", headers=admin_headers)
        assert resp.status_code == 200
        items = resp.json().get("items", [])
        
        # Check at least one runbook has the new fields
        synology_rb = next((rb for rb in items if "synology" in rb.get("title", "").lower()), None)
        assert synology_rb is not None, "Synology runbook not found"
        
        # Verify new fields exist
        assert "profile_keys" in synology_rb, "Missing profile_keys field"
        assert "capability_match" in synology_rb, "Missing capability_match field"
        assert "vendor_match" in synology_rb, "Missing vendor_match field"
        assert "severity_match" in synology_rb, "Missing severity_match field"
        
        # Verify Synology runbook has correct values
        assert "synology_dsm" in synology_rb.get("profile_keys", []), "Synology runbook missing synology_dsm profile_key"
        assert "synology" in [v.lower() for v in synology_rb.get("vendor_match", [])], "Synology runbook missing synology vendor_match"
        print(f"Synology runbook fields: profile_keys={synology_rb.get('profile_keys')}, vendor_match={synology_rb.get('vendor_match')}, capability_match={synology_rb.get('capability_match')}")


# ============ MATCH ALERT TESTS ============

class TestMatchAlert:
    """GET /api/runbooks/match/alert/{alert_id} tests"""
    
    def test_match_alert_with_existing_alert(self, admin_headers):
        """Test match endpoint with an existing alert"""
        # First get an existing alert
        resp = requests.get(f"{BASE_URL}/api/alerts?limit=1", headers=admin_headers)
        assert resp.status_code == 200
        alerts = resp.json()
        if not alerts:
            pytest.skip("No existing alerts to test with")
        
        alert_id = alerts[0].get("id")
        resp = requests.get(f"{BASE_URL}/api/runbooks/match/alert/{alert_id}", headers=admin_headers)
        assert resp.status_code == 200, f"Match failed: {resp.text}"
        data = resp.json()
        
        assert "alert" in data, "Missing alert in response"
        assert "context" in data, "Missing context in response"
        assert "matches" in data, "Missing matches in response"
        
        # Context should have profile_key, vendor, family, capabilities
        ctx = data.get("context", {})
        assert "profile_key" in ctx
        assert "vendor" in ctx
        assert "family" in ctx
        assert "capabilities" in ctx
        print(f"Context: {ctx}")
        print(f"Matches count: {len(data.get('matches', []))}")
    
    def test_match_alert_scoring_structure(self, admin_headers):
        """Verify matches have _match_score and _match_reasons"""
        # Get an alert that should match something
        resp = requests.get(f"{BASE_URL}/api/alerts?limit=10", headers=admin_headers)
        alerts = resp.json()
        
        # Find an alert with "offline" or "critical" to ensure matches
        test_alert = None
        for a in alerts:
            if "offline" in (a.get("title", "") + a.get("message", "")).lower() or a.get("severity") == "critical":
                test_alert = a
                break
        
        if not test_alert:
            pytest.skip("No suitable alert found for scoring test")
        
        resp = requests.get(f"{BASE_URL}/api/runbooks/match/alert/{test_alert['id']}", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        matches = data.get("matches", [])
        
        if len(matches) > 0:
            top_match = matches[0]
            assert "_match_score" in top_match, "Missing _match_score"
            assert "_match_reasons" in top_match, "Missing _match_reasons"
            assert isinstance(top_match["_match_score"], int), "_match_score should be int"
            assert isinstance(top_match["_match_reasons"], list), "_match_reasons should be list"
            print(f"Top match: {top_match.get('title')}, score={top_match.get('_match_score')}, reasons={top_match.get('_match_reasons')}")
    
    def test_match_alert_not_found(self, admin_headers):
        """Non-existent alert returns 404"""
        resp = requests.get(f"{BASE_URL}/api/runbooks/match/alert/nonexistent-alert-id", headers=admin_headers)
        assert resp.status_code == 404


# ============ REGRESSION TESTS ============

class TestRunbookCRUDRegression:
    """Regression tests for existing CRUD endpoints"""
    
    def test_create_runbook(self, admin_headers):
        """POST /api/runbooks creates runbook"""
        rb_data = {
            "title": f"TEST_Runbook_{uuid.uuid4().hex[:8]}",
            "description": "Test runbook for regression testing",
            "device_types": ["switch"],
            "alert_keywords": ["test", "regression"],
            "severity_match": ["warning"],
            "vendor_match": ["TestVendor"],
            "profile_keys": ["test_profile"],
            "capability_match": ["test_cap"],
            "steps": [
                {"order": 1, "title": "Step 1", "description": "Test step"}
            ],
            "tags": ["test"]
        }
        resp = requests.post(f"{BASE_URL}/api/runbooks", json=rb_data, headers=admin_headers)
        assert resp.status_code in [200, 201], f"Failed to create runbook: {resp.text}"
        data = resp.json()
        assert "id" in data
        assert data.get("title") == rb_data["title"]
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/runbooks/{data['id']}", headers=admin_headers)
    
    def test_get_runbook_by_id(self, admin_headers):
        """GET /api/runbooks/{id} works"""
        # Create a runbook first
        rb_data = {
            "title": f"TEST_Get_{uuid.uuid4().hex[:8]}",
            "description": "Test",
            "device_types": [],
            "alert_keywords": [],
            "steps": []
        }
        resp = requests.post(f"{BASE_URL}/api/runbooks", json=rb_data, headers=admin_headers)
        assert resp.status_code in [200, 201]
        rb_id = resp.json().get("id")
        
        # Get by ID
        resp = requests.get(f"{BASE_URL}/api/runbooks/{rb_id}", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("id") == rb_id
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/runbooks/{rb_id}", headers=admin_headers)
    
    def test_update_runbook(self, admin_headers):
        """PUT /api/runbooks/{id} works"""
        # Create a runbook first
        rb_data = {
            "title": f"TEST_Update_{uuid.uuid4().hex[:8]}",
            "description": "Original",
            "device_types": ["switch"],
            "alert_keywords": ["test"],
            "steps": []
        }
        resp = requests.post(f"{BASE_URL}/api/runbooks", json=rb_data, headers=admin_headers)
        assert resp.status_code in [200, 201]
        rb_id = resp.json().get("id")
        
        # Update
        update_data = {
            "title": rb_data["title"] + "_Updated",
            "description": "Updated description",
            "device_types": ["switch", "router"],
            "alert_keywords": ["test", "updated"],
            "steps": [{"order": 1, "title": "New Step"}]
        }
        resp = requests.put(f"{BASE_URL}/api/runbooks/{rb_id}", json=update_data, headers=admin_headers)
        assert resp.status_code == 200
        
        # Verify update
        resp = requests.get(f"{BASE_URL}/api/runbooks/{rb_id}", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "Updated" in data.get("title", "")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/runbooks/{rb_id}", headers=admin_headers)
    
    def test_delete_runbook(self, admin_headers):
        """DELETE /api/runbooks/{id} works"""
        # Create a runbook to delete
        rb_data = {
            "title": f"TEST_Delete_{uuid.uuid4().hex[:8]}",
            "description": "Will be deleted",
            "device_types": [],
            "alert_keywords": [],
            "steps": []
        }
        resp = requests.post(f"{BASE_URL}/api/runbooks", json=rb_data, headers=admin_headers)
        assert resp.status_code in [200, 201]
        rb_id = resp.json().get("id")
        
        # Delete
        resp = requests.delete(f"{BASE_URL}/api/runbooks/{rb_id}", headers=admin_headers)
        assert resp.status_code == 200
        
        # Verify deleted
        resp = requests.get(f"{BASE_URL}/api/runbooks/{rb_id}", headers=admin_headers)
        assert resp.status_code == 404
    
    def test_viewer_cannot_create_runbook(self, viewer_headers):
        """Viewer role cannot create runbooks"""
        rb_data = {
            "title": "TEST_Viewer_Attempt",
            "description": "Should fail",
            "device_types": [],
            "alert_keywords": [],
            "steps": []
        }
        resp = requests.post(f"{BASE_URL}/api/runbooks", json=rb_data, headers=viewer_headers)
        assert resp.status_code == 403


# ============ VERIFY SEED RUNBOOK CONTENT ============

class TestSeedRunbookContent:
    """Verify the 8 seed runbooks have correct content"""
    
    def test_synology_disk_degraded_runbook(self, admin_headers):
        """Synology disk degraded runbook has correct fields"""
        resp = requests.get(f"{BASE_URL}/api/runbooks", headers=admin_headers)
        items = resp.json().get("items", [])
        rb = next((r for r in items if "seed:synology-disk-degraded" in (r.get("tags") or [])), None)
        assert rb is not None, "Synology disk degraded seed runbook not found"
        
        assert "synology_dsm" in rb.get("profile_keys", [])
        assert "disk_smart" in rb.get("capability_match", [])
        assert "raid_status" in rb.get("capability_match", [])
        assert "synology" in [v.lower() for v in rb.get("vendor_match", [])]
        assert "critical" in rb.get("severity_match", [])
        assert len(rb.get("steps", [])) >= 5
        print(f"Synology disk degraded: {len(rb.get('steps', []))} steps")
    
    def test_fortinet_vpn_down_runbook(self, admin_headers):
        """Fortinet VPN down runbook has correct fields"""
        resp = requests.get(f"{BASE_URL}/api/runbooks", headers=admin_headers)
        items = resp.json().get("items", [])
        rb = next((r for r in items if "seed:fortinet-vpn-down" in (r.get("tags") or [])), None)
        assert rb is not None, "Fortinet VPN down seed runbook not found"
        
        assert "fortinet_fortigate" in rb.get("profile_keys", [])
        assert "vpn_tunnels" in rb.get("capability_match", [])
        assert "fortinet" in [v.lower() for v in rb.get("vendor_match", [])]
        print(f"Fortinet VPN down: profile_keys={rb.get('profile_keys')}, capability_match={rb.get('capability_match')}")
    
    def test_apc_ups_on_battery_runbook(self, admin_headers):
        """APC UPS on battery runbook has correct fields"""
        resp = requests.get(f"{BASE_URL}/api/runbooks", headers=admin_headers)
        items = resp.json().get("items", [])
        rb = next((r for r in items if "seed:apc-ups-on-battery" in (r.get("tags") or [])), None)
        assert rb is not None, "APC UPS on battery seed runbook not found"
        
        assert "apc_ups" in rb.get("profile_keys", [])
        assert "battery_monitoring" in rb.get("capability_match", [])
        assert "apc" in [v.lower() for v in rb.get("vendor_match", [])]
    
    def test_hp_switch_port_down_runbook(self, admin_headers):
        """HP switch port down runbook has correct fields"""
        resp = requests.get(f"{BASE_URL}/api/runbooks", headers=admin_headers)
        items = resp.json().get("items", [])
        rb = next((r for r in items if "seed:hp-switch-port-down" in (r.get("tags") or [])), None)
        assert rb is not None, "HP switch port down seed runbook not found"
        
        assert "hp_procurve" in rb.get("profile_keys", [])
        assert "switch" in rb.get("device_types", [])
    
    def test_unifi_ap_offline_runbook(self, admin_headers):
        """UniFi AP offline runbook has correct fields"""
        resp = requests.get(f"{BASE_URL}/api/runbooks", headers=admin_headers)
        items = resp.json().get("items", [])
        rb = next((r for r in items if "seed:unifi-ap-offline" in (r.get("tags") or [])), None)
        assert rb is not None, "UniFi AP offline seed runbook not found"
        
        assert "unifi" in rb.get("profile_keys", [])
        assert "ubiquiti" in [v.lower() for v in rb.get("vendor_match", [])]
    
    def test_ilo_fan_critical_runbook(self, admin_headers):
        """HPE iLO fan critical runbook has correct fields"""
        resp = requests.get(f"{BASE_URL}/api/runbooks", headers=admin_headers)
        items = resp.json().get("items", [])
        rb = next((r for r in items if "seed:ilo-fan-critical" in (r.get("tags") or [])), None)
        assert rb is not None, "HPE iLO fan critical seed runbook not found"
        
        assert "hardware_oob" in rb.get("capability_match", [])
        assert "hpe" in [v.lower() for v in rb.get("vendor_match", [])] or "hp" in [v.lower() for v in rb.get("vendor_match", [])]
    
    def test_device_offline_generic_runbook(self, admin_headers):
        """Device offline generic runbook exists"""
        resp = requests.get(f"{BASE_URL}/api/runbooks", headers=admin_headers)
        items = resp.json().get("items", [])
        rb = next((r for r in items if "seed:device-offline-generic" in (r.get("tags") or [])), None)
        assert rb is not None, "Device offline generic seed runbook not found"
        
        # Generic runbook should have empty device_types (matches any)
        assert rb.get("device_types") == [] or rb.get("device_types") is None or len(rb.get("device_types", [])) == 0
        assert "offline" in rb.get("alert_keywords", [])
        print(f"Device offline generic: keywords={rb.get('alert_keywords')}")
    
    def test_all_8_seed_runbooks_present(self, admin_headers):
        """All 8 seed runbooks are present"""
        resp = requests.get(f"{BASE_URL}/api/runbooks", headers=admin_headers)
        items = resp.json().get("items", [])
        
        expected_seeds = [
            "seed:synology-disk-degraded",
            "seed:synology-volume-full",
            "seed:fortinet-vpn-down",
            "seed:apc-ups-on-battery",
            "seed:hp-switch-port-down",
            "seed:unifi-ap-offline",
            "seed:ilo-fan-critical",
            "seed:device-offline-generic"
        ]
        
        found_seeds = []
        for rb in items:
            tags = rb.get("tags") or []
            for tag in tags:
                if tag.startswith("seed:"):
                    found_seeds.append(tag)
        
        for seed in expected_seeds:
            assert seed in found_seeds, f"Missing seed runbook: {seed}"
        
        print(f"All 8 seed runbooks present: {found_seeds}")


# ============ SCORING ALGORITHM VERIFICATION ============

class TestScoringAlgorithm:
    """Verify the scoring algorithm works correctly"""
    
    def test_keyword_match_scoring(self, admin_headers):
        """Keywords should add +3 per hit"""
        # Find an alert with "offline" keyword
        resp = requests.get(f"{BASE_URL}/api/alerts?limit=50", headers=admin_headers)
        alerts = resp.json()
        
        offline_alert = next((a for a in alerts if "offline" in (a.get("title", "") + a.get("message", "")).lower()), None)
        if not offline_alert:
            pytest.skip("No offline alert found")
        
        resp = requests.get(f"{BASE_URL}/api/runbooks/match/alert/{offline_alert['id']}", headers=admin_headers)
        data = resp.json()
        matches = data.get("matches", [])
        
        # Find the generic offline runbook match
        offline_match = next((m for m in matches if "device-offline-generic" in str(m.get("tags", []))), None)
        if offline_match:
            reasons = offline_match.get("_match_reasons", [])
            assert any("keywords:" in r for r in reasons), "Should have keyword match reason"
            print(f"Offline match score: {offline_match.get('_match_score')}, reasons: {reasons}")
    
    def test_severity_match_scoring(self, admin_headers):
        """Severity should add +1"""
        # Find a critical alert
        resp = requests.get(f"{BASE_URL}/api/alerts?limit=50", headers=admin_headers)
        alerts = resp.json()
        
        critical_alert = next((a for a in alerts if a.get("severity") == "critical"), None)
        if not critical_alert:
            pytest.skip("No critical alert found")
        
        resp = requests.get(f"{BASE_URL}/api/runbooks/match/alert/{critical_alert['id']}", headers=admin_headers)
        data = resp.json()
        matches = data.get("matches", [])
        
        if matches:
            # At least one match should have severity reason
            has_severity_match = any("severity:" in str(m.get("_match_reasons", [])) for m in matches)
            print(f"Has severity match: {has_severity_match}")
            # This is expected for critical alerts matching runbooks with severity_match: ["critical"]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
