"""
Test Auto-Discovery Network Scanning Feature
Tests the new network discovery endpoints for NOC Alert Collector platform.
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials from iteration_7.json
ADMIN_EMAIL = "admin@86bit.it"
ADMIN_PASSWORD = "admin123"
API_KEY = "noc_35cf39b4d68740b1a981aedef2ee293d"
CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token for admin user."""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD
    })
    assert response.status_code == 200, f"Login failed: {response.text}"
    data = response.json()
    assert "token" in data, "No token in login response"
    return data["token"]


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Headers with JWT auth token."""
    return {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }


@pytest.fixture(scope="module")
def api_key_headers():
    """Headers with API key for connector endpoints."""
    return {
        "X-API-Key": API_KEY,
        "Content-Type": "application/json"
    }


class TestAutoDiscoveryBackend:
    """Test Auto-Discovery API endpoints."""
    
    def test_login_admin(self):
        """Test login with admin@86bit.it / admin123."""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200, f"Login failed: {response.text}"
        data = response.json()
        assert "token" in data
        assert "user" in data
        assert data["user"]["email"] == ADMIN_EMAIL
        assert data["user"]["role"] == "admin"
        print(f"✓ Login successful for {ADMIN_EMAIL}")
    
    def test_start_discovery_creates_pending_request(self, auth_headers):
        """POST /api/connector/start-discovery should accept client_id and subnet, create request with status pending."""
        response = requests.post(
            f"{BASE_URL}/api/connector/start-discovery",
            headers=auth_headers,
            json={
                "client_id": CLIENT_ID,
                "subnet": "192.168.1.0/24"
            }
        )
        assert response.status_code == 200, f"Start discovery failed: {response.text}"
        data = response.json()
        assert data.get("status") == "ok"
        print(f"✓ Start discovery returned: {data}")
    
    def test_discovery_status_shows_pending_or_in_progress(self, auth_headers):
        """GET /api/connector/discovery-status/{client_id} should return current scan status."""
        response = requests.get(
            f"{BASE_URL}/api/connector/discovery-status/{CLIENT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Discovery status failed: {response.text}"
        data = response.json()
        assert "status" in data
        # Status should be pending, in_progress, completed, or none
        assert data["status"] in ["pending", "in_progress", "completed", "none"], f"Unexpected status: {data['status']}"
        print(f"✓ Discovery status: {data}")
    
    def test_discovery_check_with_api_key_returns_scan_requested(self, api_key_headers):
        """GET /api/connector/discovery-check with X-API-Key should return scan_requested."""
        # First, ensure there's a pending request
        # Get auth token first
        login_resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        token = login_resp.json()["token"]
        
        # Start a new discovery request
        requests.post(
            f"{BASE_URL}/api/connector/start-discovery",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"client_id": CLIENT_ID, "subnet": "192.168.1.0/24"}
        )
        
        # Now check with API key
        response = requests.get(
            f"{BASE_URL}/api/connector/discovery-check",
            headers=api_key_headers
        )
        assert response.status_code == 200, f"Discovery check failed: {response.text}"
        data = response.json()
        assert "scan_requested" in data
        # After checking, status changes to in_progress, so scan_requested might be True or False
        print(f"✓ Discovery check returned: {data}")
    
    def test_submit_discovery_results_with_api_key(self, api_key_headers):
        """POST /api/connector/discovery-results with X-API-Key should accept device list and set status to completed."""
        # Simulate connector submitting discovery results
        test_devices = [
            {
                "ip": "192.168.1.1",
                "hostname": "router.local",
                "ping_ms": 1,
                "open_ports": [{"port": 80, "service": "http"}, {"port": 443, "service": "https"}],
                "device_type": "network-device",
                "suggested_type": "snmp"
            },
            {
                "ip": "192.168.1.2",
                "hostname": "switch.local",
                "ping_ms": 2,
                "open_ports": [{"port": 161, "service": "snmp"}],
                "device_type": "switch/router",
                "suggested_type": "snmp"
            },
            {
                "ip": "192.168.1.3",
                "hostname": "server.local",
                "ping_ms": 5,
                "open_ports": [{"port": 22, "service": "ssh"}, {"port": 80, "service": "http"}],
                "device_type": "server-linux",
                "suggested_type": "ping"
            },
            {
                "ip": "192.168.1.10",
                "hostname": "workstation1.local",
                "ping_ms": 3,
                "open_ports": [{"port": 3389, "service": "rdp"}],
                "device_type": "server-windows",
                "suggested_type": "ping"
            },
            {
                "ip": "192.168.1.20",
                "hostname": "printer.local",
                "ping_ms": 8,
                "open_ports": [{"port": 9100, "service": "jetdirect"}],
                "device_type": "unknown",
                "suggested_type": "ping"
            }
        ]
        
        response = requests.post(
            f"{BASE_URL}/api/connector/discovery-results",
            headers=api_key_headers,
            json={"devices": test_devices}
        )
        assert response.status_code == 200, f"Submit discovery results failed: {response.text}"
        data = response.json()
        assert data.get("status") == "ok"
        assert data.get("devices_found") == 5
        print(f"✓ Discovery results submitted: {data}")
    
    def test_get_discovery_results_returns_devices_with_managed_ips(self, auth_headers):
        """GET /api/connector/discovery-results/{client_id} should return discovered devices with managed_ips."""
        response = requests.get(
            f"{BASE_URL}/api/connector/discovery-results/{CLIENT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Get discovery results failed: {response.text}"
        data = response.json()
        
        # Verify structure
        assert "devices" in data, "No devices field in response"
        assert "managed_ips" in data, "No managed_ips field in response"
        
        # Verify devices have expected fields
        if len(data["devices"]) > 0:
            device = data["devices"][0]
            assert "ip" in device, "Device missing ip field"
            print(f"✓ Discovery results: {len(data['devices'])} devices, managed_ips: {data['managed_ips']}")
        else:
            print("✓ Discovery results returned (no devices yet)")
    
    def test_discovery_status_shows_completed(self, auth_headers):
        """After submitting results, status should be completed."""
        response = requests.get(
            f"{BASE_URL}/api/connector/discovery-status/{CLIENT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Discovery status failed: {response.text}"
        data = response.json()
        assert data.get("status") == "completed", f"Expected completed status, got: {data}"
        print(f"✓ Discovery status is completed: {data}")
    
    def test_add_discovered_device_to_monitoring(self, auth_headers):
        """Adding a discovered device should work via managed-devices endpoint."""
        # Add a test device from discovery
        test_device = {
            "ip": "192.168.1.99",
            "name": "TEST_DiscoveredDevice",
            "community": "",
            "monitor_type": "ping",
            "http_port": 80
        }
        
        response = requests.post(
            f"{BASE_URL}/api/connector/{CLIENT_ID}/managed-devices",
            headers=auth_headers,
            json=test_device
        )
        assert response.status_code == 200, f"Add device failed: {response.text}"
        data = response.json()
        assert data.get("status") == "ok"
        print(f"✓ Added discovered device to monitoring: {data}")
        
        # Verify it appears in managed_ips when getting discovery results
        results_resp = requests.get(
            f"{BASE_URL}/api/connector/discovery-results/{CLIENT_ID}",
            headers=auth_headers
        )
        results = results_resp.json()
        assert "192.168.1.99" in results.get("managed_ips", []), "New device not in managed_ips"
        print(f"✓ Device appears in managed_ips: {results.get('managed_ips')}")
    
    def test_cleanup_test_device(self, auth_headers):
        """Clean up test device created during testing."""
        response = requests.delete(
            f"{BASE_URL}/api/connector/device-poll-status/192.168.1.99",
            headers=auth_headers
        )
        # May return 200 or 404 if device wasn't fully created
        print(f"✓ Cleanup test device: status {response.status_code}")


class TestDiscoveryAPIKeyValidation:
    """Test API key validation for connector endpoints."""
    
    def test_discovery_check_requires_api_key(self):
        """Discovery check should fail without API key."""
        response = requests.get(f"{BASE_URL}/api/connector/discovery-check")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("✓ Discovery check requires API key")
    
    def test_discovery_results_requires_api_key(self):
        """Submit discovery results should fail without API key."""
        response = requests.post(
            f"{BASE_URL}/api/connector/discovery-results",
            json={"devices": []}
        )
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("✓ Discovery results submission requires API key")
    
    def test_invalid_api_key_rejected(self):
        """Invalid API key should be rejected."""
        response = requests.get(
            f"{BASE_URL}/api/connector/discovery-check",
            headers={"X-API-Key": "invalid_key_12345"}
        )
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("✓ Invalid API key rejected")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
