"""
Test suite for External WAN Monitor API endpoints.
Tests: CRUD operations for WAN targets, probe status, and client-specific status.
"""
import pytest
import requests
import os
import uuid
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
TEST_CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"

@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token for admin user"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "admin@86bit.it",
        "password": "password"
    })
    if response.status_code == 200:
        return response.json().get("token")
    pytest.skip(f"Authentication failed: {response.status_code} - {response.text}")

@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Headers with auth token"""
    return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}


class TestExternalMonitorTargets:
    """Tests for WAN target CRUD operations"""
    
    def test_get_targets_list(self, auth_headers):
        """GET /api/external-monitor/targets - should return list of WAN targets"""
        response = requests.get(f"{BASE_URL}/api/external-monitor/targets", headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "targets" in data, "Response should contain 'targets' key"
        assert isinstance(data["targets"], list), "targets should be a list"
        
        # Verify existing targets (2 should exist per context)
        if len(data["targets"]) >= 2:
            print(f"Found {len(data['targets'])} existing WAN targets")
            for t in data["targets"]:
                assert "id" in t, "Target should have id"
                assert "client_id" in t, "Target should have client_id"
                assert "label" in t, "Target should have label"
                assert "device_type" in t, "Target should have device_type"
                assert "public_ip" in t, "Target should have public_ip"
                assert "check_ports" in t, "Target should have check_ports"
                print(f"  - {t['label']} ({t['device_type']}): {t['public_ip']} ports={t['check_ports']}")
    
    def test_get_targets_by_client(self, auth_headers):
        """GET /api/external-monitor/targets?client_id=xxx - filter by client"""
        response = requests.get(
            f"{BASE_URL}/api/external-monitor/targets?client_id={TEST_CLIENT_ID}", 
            headers=auth_headers
        )
        assert response.status_code == 200
        
        data = response.json()
        for t in data["targets"]:
            assert t["client_id"] == TEST_CLIENT_ID, f"Target client_id should match filter"
    
    def test_create_target_and_delete(self, auth_headers):
        """POST /api/external-monitor/targets - create a temporary target then delete"""
        # Create a temporary target
        new_target = {
            "client_id": TEST_CLIENT_ID,
            "label": "TEST_Temporary_Target",
            "device_type": "router",
            "public_ip": "93.184.216.34",  # example.com IP
            "check_ports": [80, 443],
            "enabled": True
        }
        
        create_response = requests.post(
            f"{BASE_URL}/api/external-monitor/targets",
            headers=auth_headers,
            json=new_target
        )
        assert create_response.status_code == 200, f"Create failed: {create_response.text}"
        
        created = create_response.json()
        assert created["status"] == "ok", "Create should return status ok"
        assert "target" in created, "Response should contain target"
        
        target_id = created["target"]["id"]
        assert target_id, "Created target should have an id"
        assert created["target"]["label"] == new_target["label"]
        assert created["target"]["public_ip"] == new_target["public_ip"]
        assert created["target"]["device_type"] == new_target["device_type"]
        print(f"Created temporary target: {target_id}")
        
        # Verify it appears in list
        list_response = requests.get(f"{BASE_URL}/api/external-monitor/targets", headers=auth_headers)
        targets = list_response.json()["targets"]
        found = any(t["id"] == target_id for t in targets)
        assert found, "Created target should appear in list"
        
        # Delete the temporary target
        delete_response = requests.delete(
            f"{BASE_URL}/api/external-monitor/targets/{target_id}",
            headers=auth_headers
        )
        assert delete_response.status_code == 200, f"Delete failed: {delete_response.text}"
        assert delete_response.json()["status"] == "ok"
        print(f"Deleted temporary target: {target_id}")
        
        # Verify it's gone
        list_response2 = requests.get(f"{BASE_URL}/api/external-monitor/targets", headers=auth_headers)
        targets2 = list_response2.json()["targets"]
        found2 = any(t["id"] == target_id for t in targets2)
        assert not found2, "Deleted target should not appear in list"
    
    def test_create_target_validation(self, auth_headers):
        """POST /api/external-monitor/targets - validation errors"""
        # Missing required fields
        invalid_target = {
            "client_id": TEST_CLIENT_ID,
            # missing label, device_type, public_ip
        }
        
        response = requests.post(
            f"{BASE_URL}/api/external-monitor/targets",
            headers=auth_headers,
            json=invalid_target
        )
        # Should fail with 422 validation error
        assert response.status_code == 422, f"Expected 422 for invalid data, got {response.status_code}"


class TestExternalMonitorStatus:
    """Tests for WAN probe status endpoints"""
    
    def test_get_all_status(self, auth_headers):
        """GET /api/external-monitor/status - returns probe results and diagnoses"""
        response = requests.get(f"{BASE_URL}/api/external-monitor/status", headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "results" in data, "Response should contain 'results'"
        assert "diagnoses" in data, "Response should contain 'diagnoses'"
        
        # Check results structure
        for r in data["results"]:
            assert "target_id" in r, "Result should have target_id"
            assert "client_id" in r, "Result should have client_id"
            assert "status" in r, "Result should have status"
            assert r["status"] in ["online", "offline", "degraded", "unknown"], f"Invalid status: {r['status']}"
            assert "ping" in r, "Result should have ping data"
            assert "ports" in r, "Result should have ports data"
            print(f"  Target {r.get('label', r['target_id'])}: {r['status']} - ping={r['ping']}")
        
        # Check diagnoses structure
        for d in data["diagnoses"]:
            assert "client_id" in d, "Diagnosis should have client_id"
            assert "diagnosis" in d, "Diagnosis should have diagnosis code"
            assert "diagnosis_text" in d, "Diagnosis should have diagnosis_text"
            print(f"  Client {d.get('client_name', d['client_id'])}: {d['diagnosis']} - {d['diagnosis_text']}")
    
    def test_get_client_status(self, auth_headers):
        """GET /api/external-monitor/status/{client_id} - returns status for specific client"""
        response = requests.get(
            f"{BASE_URL}/api/external-monitor/status/{TEST_CLIENT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "results" in data, "Response should contain 'results'"
        assert "diagnosis" in data, "Response should contain 'diagnosis'"
        
        # All results should be for the requested client
        for r in data["results"]:
            assert r["client_id"] == TEST_CLIENT_ID, f"Result client_id should match requested"
        
        # Diagnosis should be for the requested client
        if data["diagnosis"]:
            assert data["diagnosis"]["client_id"] == TEST_CLIENT_ID


class TestExternalMonitorProbe:
    """Tests for probe-now endpoint"""
    
    def test_probe_now(self, auth_headers):
        """POST /api/external-monitor/probe-now - triggers immediate probe"""
        response = requests.post(
            f"{BASE_URL}/api/external-monitor/probe-now",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data["status"] == "ok", "Probe should return status ok"
        assert "message" in data, "Response should contain message"
        print(f"Probe triggered: {data['message']}")
        
        # Wait for probe to complete
        time.sleep(5)
        
        # Verify results are updated
        status_response = requests.get(f"{BASE_URL}/api/external-monitor/status", headers=auth_headers)
        assert status_response.status_code == 200
        
        results = status_response.json()["results"]
        if results:
            # Check that checked_at is recent
            for r in results:
                if "checked_at" in r:
                    print(f"  {r.get('label', 'Unknown')}: checked at {r['checked_at']}")


class TestTvDashboardWanIntegration:
    """Tests for WAN data in TV Dashboard"""
    
    def test_tv_dashboard_has_wan_data(self):
        """GET /api/tv/dashboard - should include WAN targets and diagnosis per client"""
        # TV Dashboard doesn't require auth
        response = requests.get(f"{BASE_URL}/api/tv/dashboard")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "clients" in data, "TV Dashboard should have clients"
        
        # Check that clients have WAN data
        for client in data["clients"]:
            assert "wan_targets" in client, f"Client {client['name']} should have wan_targets"
            assert "wan_diagnosis" in client, f"Client {client['name']} should have wan_diagnosis"
            assert "wan_diagnosis_text" in client, f"Client {client['name']} should have wan_diagnosis_text"
            
            if client["wan_targets"]:
                print(f"Client {client['name']}:")
                print(f"  WAN Diagnosis: {client['wan_diagnosis']} - {client['wan_diagnosis_text']}")
                for wt in client["wan_targets"]:
                    assert "label" in wt, "WAN target should have label"
                    assert "device_type" in wt, "WAN target should have device_type"
                    assert "public_ip" in wt, "WAN target should have public_ip"
                    assert "status" in wt, "WAN target should have status"
                    print(f"    - {wt['label']} ({wt['device_type']}): {wt['status']} @ {wt['public_ip']}")


class TestExternalMonitorHistory:
    """Tests for probe history endpoint"""
    
    def test_get_probe_history(self, auth_headers):
        """GET /api/external-monitor/history/{target_id} - returns historical data"""
        # First get a target ID
        targets_response = requests.get(f"{BASE_URL}/api/external-monitor/targets", headers=auth_headers)
        targets = targets_response.json()["targets"]
        
        if not targets:
            pytest.skip("No targets available for history test")
        
        target_id = targets[0]["id"]
        
        response = requests.get(
            f"{BASE_URL}/api/external-monitor/history/{target_id}?hours=24",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "history" in data, "Response should contain 'history'"
        assert isinstance(data["history"], list), "history should be a list"
        
        print(f"Found {len(data['history'])} history entries for target {target_id}")
        
        # Check history entry structure
        for h in data["history"][:5]:  # Check first 5
            assert "target_id" in h, "History entry should have target_id"
            assert "status" in h, "History entry should have status"
            assert "timestamp" in h, "History entry should have timestamp"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
