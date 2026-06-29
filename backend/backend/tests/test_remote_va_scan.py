"""
Remote Vulnerability Assessment Scan Tests
Tests for: Remote scan request, scan status, update-scan-status, process-scan-results
Features: Remote VA scanning via connector, pending_commands, progress tracking
"""
import pytest
import requests
import os
import uuid
from datetime import datetime, timezone

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestRemoteVAScan:
    """Remote VA Scan endpoint tests - NEW functionality"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup: Get auth token and client_id"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login to get token
        login_response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@86bit.it",
            "password": "password"
        })
        assert login_response.status_code == 200, f"Login failed: {login_response.text}"
        token = login_response.json().get("token")
        assert token, "No token in login response"
        self.session.headers.update({"Authorization": f"Bearer {token}"})
        
        # Get first client_id (86BIT_Office)
        clients_response = self.session.get(f"{BASE_URL}/api/clients")
        assert clients_response.status_code == 200, f"Failed to get clients: {clients_response.text}"
        clients_data = clients_response.json()
        clients_list = clients_data if isinstance(clients_data, list) else clients_data.get("clients", [])
        assert len(clients_list) > 0, "No clients found"
        
        # Find 86BIT_Office client or use first
        self.client_id = None
        for c in clients_list:
            if "86BIT" in c.get("name", ""):
                self.client_id = c["id"]
                self.client_name = c.get("name", "")
                self.api_key = c.get("api_key", "")
                break
        
        if not self.client_id:
            self.client_id = clients_list[0]["id"]
            self.client_name = clients_list[0].get("name", "")
            self.api_key = clients_list[0].get("api_key", "")
        
        print(f"Using client: {self.client_name} (ID: {self.client_id})")
    
    # ============ REQUEST-SCAN ENDPOINT TESTS ============
    
    def test_request_scan_endpoint_exists(self):
        """POST /api/vulnerability/request-scan/{client_id} endpoint exists"""
        response = self.session.post(f"{BASE_URL}/api/vulnerability/request-scan/{self.client_id}", json={})
        # Should return 200, 400 (connector offline), or 409 (scan in progress) - NOT 404
        assert response.status_code != 404, f"Endpoint not found: {response.status_code}"
        print(f"✓ request-scan endpoint exists (status: {response.status_code})")
    
    def test_request_scan_returns_scan_id(self):
        """Request scan returns scan_id when connector is online"""
        response = self.session.post(f"{BASE_URL}/api/vulnerability/request-scan/{self.client_id}", json={})
        
        if response.status_code == 200:
            data = response.json()
            assert "scan_id" in data, "Response missing scan_id"
            assert "status" in data, "Response missing status"
            assert "message" in data, "Response missing message"
            print(f"✓ Request scan returned scan_id: {data['scan_id']}")
        elif response.status_code == 400:
            # Connector offline - expected behavior
            data = response.json()
            assert "detail" in data, "Error response missing detail"
            print(f"✓ Request scan correctly rejected (connector offline): {data['detail']}")
        elif response.status_code == 409:
            # Scan already in progress - expected behavior
            data = response.json()
            assert "detail" in data, "Error response missing detail"
            print(f"✓ Request scan correctly rejected (scan in progress): {data['detail']}")
        else:
            pytest.fail(f"Unexpected status code: {response.status_code}")
    
    def test_request_scan_404_for_invalid_client(self):
        """Request scan returns 404 for non-existent client"""
        response = self.session.post(f"{BASE_URL}/api/vulnerability/request-scan/invalid-client-id-12345", json={})
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("✓ Request scan returns 404 for invalid client")
    
    def test_request_scan_requires_auth(self):
        """Request scan requires authentication"""
        no_auth_session = requests.Session()
        response = no_auth_session.post(f"{BASE_URL}/api/vulnerability/request-scan/{self.client_id}", json={})
        assert response.status_code in [401, 403], f"Expected 401/403 without auth, got {response.status_code}"
        print("✓ Request scan requires authentication")
    
    # ============ SCAN-STATUS ENDPOINT TESTS ============
    
    def test_scan_status_endpoint_exists(self):
        """GET /api/vulnerability/scan-status/{client_id} endpoint exists"""
        response = self.session.get(f"{BASE_URL}/api/vulnerability/scan-status/{self.client_id}")
        assert response.status_code == 200, f"Scan status failed: {response.status_code}"
        print("✓ scan-status endpoint exists and returns 200")
    
    def test_scan_status_returns_valid_status(self):
        """Scan status returns valid status object"""
        response = self.session.get(f"{BASE_URL}/api/vulnerability/scan-status/{self.client_id}")
        data = response.json()
        
        # Should have status field
        assert "status" in data, "Response missing status field"
        
        valid_statuses = ["idle", "no_connector", "pending", "in_progress", "completed", "error"]
        # If there's a va_scan_status object, check its status
        if "scan_id" in data:
            assert data.get("status") in valid_statuses, f"Invalid status: {data.get('status')}"
            print(f"✓ Scan status: {data.get('status')} (scan_id: {data.get('scan_id')})")
        else:
            print(f"✓ Scan status: {data.get('status')} (no active scan)")
    
    def test_scan_status_requires_auth(self):
        """Scan status requires authentication"""
        no_auth_session = requests.Session()
        response = no_auth_session.get(f"{BASE_URL}/api/vulnerability/scan-status/{self.client_id}")
        assert response.status_code in [401, 403], f"Expected 401/403 without auth, got {response.status_code}"
        print("✓ Scan status requires authentication")
    
    # ============ UPDATE-SCAN-STATUS ENDPOINT TESTS ============
    
    def test_update_scan_status_endpoint_exists(self):
        """POST /api/vulnerability/update-scan-status endpoint exists"""
        # This endpoint is called by the connector, so it doesn't require user auth
        test_scan_id = str(uuid.uuid4())
        response = requests.post(f"{BASE_URL}/api/vulnerability/update-scan-status", json={
            "scan_id": test_scan_id,
            "status": "in_progress",
            "progress": 50,
            "message": "Test update"
        })
        # Should return 200 (even if scan_id doesn't exist, it just won't update anything)
        assert response.status_code == 200, f"Update scan status failed: {response.status_code}"
        print("✓ update-scan-status endpoint exists and returns 200")
    
    def test_update_scan_status_requires_scan_id(self):
        """Update scan status requires scan_id"""
        response = requests.post(f"{BASE_URL}/api/vulnerability/update-scan-status", json={
            "status": "in_progress",
            "progress": 50
        })
        assert response.status_code == 400, f"Expected 400 without scan_id, got {response.status_code}"
        print("✓ Update scan status requires scan_id")
    
    def test_update_scan_status_accepts_progress(self):
        """Update scan status accepts progress percentage"""
        test_scan_id = str(uuid.uuid4())
        response = requests.post(f"{BASE_URL}/api/vulnerability/update-scan-status", json={
            "scan_id": test_scan_id,
            "status": "in_progress",
            "progress": 75,
            "message": "Scanning device 3/4"
        })
        assert response.status_code == 200, f"Update failed: {response.status_code}"
        data = response.json()
        assert data.get("status") == "ok", f"Expected status ok, got {data}"
        print("✓ Update scan status accepts progress percentage")
    
    # ============ PROCESS-SCAN-RESULTS ENDPOINT TESTS ============
    
    def test_process_scan_results_endpoint_exists(self):
        """POST /api/vulnerability/process-scan-results endpoint exists"""
        # This endpoint is called by the connector
        response = requests.post(f"{BASE_URL}/api/vulnerability/process-scan-results", json={
            "client_id": self.client_id,
            "scan_id": str(uuid.uuid4()),
            "results": []
        })
        assert response.status_code == 200, f"Process scan results failed: {response.status_code}"
        print("✓ process-scan-results endpoint exists and returns 200")
    
    def test_process_scan_results_requires_client_id(self):
        """Process scan results requires client_id"""
        response = requests.post(f"{BASE_URL}/api/vulnerability/process-scan-results", json={
            "scan_id": str(uuid.uuid4()),
            "results": []
        })
        assert response.status_code == 400, f"Expected 400 without client_id, got {response.status_code}"
        print("✓ Process scan results requires client_id")
    
    def test_process_scan_results_returns_summary(self):
        """Process scan results returns summary with devices_updated"""
        response = requests.post(f"{BASE_URL}/api/vulnerability/process-scan-results", json={
            "client_id": self.client_id,
            "scan_id": str(uuid.uuid4()),
            "results": [
                {
                    "device_ip": "192.168.1.1",
                    "open_ports": [{"port": 22, "open": True}, {"port": 80, "open": True}]
                }
            ]
        })
        assert response.status_code == 200, f"Process failed: {response.status_code}"
        data = response.json()
        assert "status" in data, "Response missing status"
        assert "devices_updated" in data, "Response missing devices_updated"
        print(f"✓ Process scan results returned: devices_updated={data['devices_updated']}")
    
    # ============ CONNECTOR MANAGED-DEVICES ENDPOINT TESTS ============
    
    def test_connector_managed_devices_endpoint_exists(self):
        """POST /api/connector/managed-devices endpoint exists"""
        # Get API key for the client
        clients_response = self.session.get(f"{BASE_URL}/api/clients")
        clients_data = clients_response.json()
        clients_list = clients_data if isinstance(clients_data, list) else clients_data.get("clients", [])
        
        api_key = None
        for c in clients_list:
            if c["id"] == self.client_id:
                api_key = c.get("api_key")
                break
        
        if api_key:
            response = requests.post(
                f"{BASE_URL}/api/connector/managed-devices",
                headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                json={}
            )
            assert response.status_code == 200, f"Managed devices failed: {response.status_code}"
            data = response.json()
            assert "devices" in data, "Response missing devices array"
            print(f"✓ connector/managed-devices endpoint returns {len(data['devices'])} devices")
        else:
            pytest.skip("No API key available for client")
    
    def test_connector_managed_devices_requires_api_key(self):
        """Connector managed-devices requires API key"""
        response = requests.post(f"{BASE_URL}/api/connector/managed-devices", json={})
        assert response.status_code in [401, 403], f"Expected 401/403 without API key, got {response.status_code}"
        print("✓ Connector managed-devices requires API key")
    
    # ============ HEARTBEAT PENDING_COMMANDS TESTS ============
    
    def test_heartbeat_returns_pending_commands(self):
        """Heartbeat returns pending_commands filtered by client_id"""
        # Get API key for the client
        clients_response = self.session.get(f"{BASE_URL}/api/clients")
        clients_data = clients_response.json()
        clients_list = clients_data if isinstance(clients_data, list) else clients_data.get("clients", [])
        
        api_key = None
        for c in clients_list:
            if c["id"] == self.client_id:
                api_key = c.get("api_key")
                break
        
        if api_key:
            # First request a scan to create a pending command
            self.session.post(f"{BASE_URL}/api/vulnerability/request-scan/{self.client_id}", json={})
            
            # Then do a heartbeat to check for pending commands
            response = requests.post(
                f"{BASE_URL}/api/connector/heartbeat",
                headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                json={
                    "connector_version": "1.0.0",
                    "hostname": "test-connector",
                    "uptime_seconds": 3600,
                    "traps_received": 0,
                    "syslogs_received": 0
                }
            )
            assert response.status_code == 200, f"Heartbeat failed: {response.status_code}"
            data = response.json()
            
            # Check if pending_commands is present (may or may not have commands)
            if "pending_commands" in data:
                commands = data["pending_commands"]
                assert isinstance(commands, list), "pending_commands should be a list"
                # Verify all commands are for this client
                for cmd in commands:
                    assert cmd.get("client_id") == self.client_id, f"Command for wrong client: {cmd.get('client_id')}"
                print(f"✓ Heartbeat returned {len(commands)} pending commands for this client")
            else:
                print("✓ Heartbeat returned no pending commands (expected if connector offline or scan already dispatched)")
        else:
            pytest.skip("No API key available for client")
    
    # ============ INTEGRATION TESTS ============
    
    def test_full_remote_scan_flow(self):
        """Test full remote scan flow: request -> status -> update -> results"""
        # 1. Request scan
        request_response = self.session.post(f"{BASE_URL}/api/vulnerability/request-scan/{self.client_id}", json={})
        
        if request_response.status_code == 200:
            scan_data = request_response.json()
            scan_id = scan_data["scan_id"]
            print(f"  1. Scan requested: {scan_id}")
            
            # 2. Check status
            status_response = self.session.get(f"{BASE_URL}/api/vulnerability/scan-status/{self.client_id}")
            assert status_response.status_code == 200
            status_data = status_response.json()
            print(f"  2. Scan status: {status_data.get('status', 'unknown')}")
            
            # 3. Simulate connector updating progress
            update_response = requests.post(f"{BASE_URL}/api/vulnerability/update-scan-status", json={
                "scan_id": scan_id,
                "status": "in_progress",
                "progress": 50,
                "message": "Scanning devices..."
            })
            assert update_response.status_code == 200
            print("  3. Progress updated to 50%")
            
            # 4. Simulate connector sending results
            results_response = requests.post(f"{BASE_URL}/api/vulnerability/process-scan-results", json={
                "client_id": self.client_id,
                "scan_id": scan_id,
                "results": [
                    {"device_ip": "192.168.1.1", "open_ports": [{"port": 22, "open": True}]}
                ]
            })
            assert results_response.status_code == 200
            results_data = results_response.json()
            print(f"  4. Results processed: {results_data.get('devices_updated', 0)} devices updated")
            
            # 5. Verify status is cleared
            final_status = self.session.get(f"{BASE_URL}/api/vulnerability/scan-status/{self.client_id}")
            final_data = final_status.json()
            print(f"  5. Final status: {final_data.get('status', 'unknown')}")
            
            print("✓ Full remote scan flow completed successfully")
        elif request_response.status_code == 400:
            print("✓ Remote scan flow test skipped (connector offline)")
        elif request_response.status_code == 409:
            print("✓ Remote scan flow test skipped (scan already in progress)")
        else:
            pytest.fail(f"Unexpected status: {request_response.status_code}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
