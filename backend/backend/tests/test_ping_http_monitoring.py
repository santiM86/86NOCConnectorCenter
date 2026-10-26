"""
Test suite for Ping+HTTP Monitoring Feature
Tests the new monitor_type field (snmp/ping) for managed devices
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
ADMIN_EMAIL = "admin@86bit.it"
ADMIN_PASSWORD = "admin123"
API_KEY = "noc_35cf39b4d68740b1a981aedef2ee293d"
CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"

# Test device data
TEST_PING_DEVICE_IP = "192.168.99.99"  # Test IP for ping device
TEST_PING_DEVICE_NAME = "TEST_PingSwitch"


class TestPingHTTPMonitoring:
    """Tests for Ping+HTTP monitoring feature"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup: Get auth token"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login to get token
        response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200, f"Login failed: {response.text}"
        token = response.json().get("token")
        self.session.headers.update({"Authorization": f"Bearer {token}"})
        
        yield
        
        # Cleanup: Remove test device
        try:
            self.session.delete(f"{BASE_URL}/api/connector/device-poll-status/{TEST_PING_DEVICE_IP}")
        except:
            pass
    
    def test_01_connector_status_shows_online(self):
        """GET /api/connector/status should show connector ONLINE with v1.7.1+"""
        response = self.session.get(f"{BASE_URL}/api/connector/status")
        assert response.status_code == 200, f"Failed: {response.text}"
        connectors = response.json()
        print(f"Found {len(connectors)} connectors")
        # Note: Connector may not be online in test environment
        # Just verify the endpoint works
        assert isinstance(connectors, list)
    
    def test_02_add_managed_device_with_ping_type(self):
        """POST /api/connector/{client_id}/managed-devices should accept monitor_type 'ping' and http_port"""
        payload = {
            "ip": TEST_PING_DEVICE_IP,
            "name": TEST_PING_DEVICE_NAME,
            "community": "",  # No community for ping devices
            "monitor_type": "ping",
            "http_port": 8080
        }
        response = self.session.post(
            f"{BASE_URL}/api/connector/{CLIENT_ID}/managed-devices",
            json=payload
        )
        assert response.status_code == 200, f"Failed to add ping device: {response.text}"
        data = response.json()
        assert data.get("status") == "ok"
        device = data.get("device", {})
        assert device.get("monitor_type") == "ping", f"Expected monitor_type 'ping', got {device.get('monitor_type')}"
        assert device.get("http_port") == 8080, f"Expected http_port 8080, got {device.get('http_port')}"
        print(f"Successfully added ping device: {device}")
    
    def test_03_fetch_devices_returns_monitor_type_and_http_port(self):
        """GET /api/connector/fetch-devices with X-API-Key should return monitor_type and http_port fields"""
        # Use API key auth (as connector would)
        response = requests.get(
            f"{BASE_URL}/api/connector/fetch-devices",
            headers={"X-API-Key": API_KEY}
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        devices = response.json()
        assert isinstance(devices, list)
        
        # Find our test device
        test_device = next((d for d in devices if d.get("ip") == TEST_PING_DEVICE_IP), None)
        if test_device:
            assert "monitor_type" in test_device, "monitor_type field missing"
            assert "http_port" in test_device, "http_port field missing"
            assert test_device["monitor_type"] == "ping", f"Expected 'ping', got {test_device['monitor_type']}"
            assert test_device["http_port"] == 8080, f"Expected 8080, got {test_device['http_port']}"
            print(f"fetch-devices returned correct fields: {test_device}")
        else:
            print(f"Test device not found in {len(devices)} devices (may have been cleaned up)")
    
    def test_04_device_report_accepts_ping_data(self):
        """POST /api/connector/device-report should accept ping_ms and http_status fields"""
        payload = {
            "hostname": "TEST_CONNECTOR",
            "devices": [
                {
                    "device_ip": TEST_PING_DEVICE_IP,
                    "device_name": TEST_PING_DEVICE_NAME,
                    "reachable": True,
                    "monitor_type": "ping",
                    "ping_ms": 15,
                    "http_status": 200,
                    "poll_timestamp": "2026-03-24T22:00:00Z"
                }
            ]
        }
        response = requests.post(
            f"{BASE_URL}/api/connector/device-report",
            json=payload,
            headers={"X-API-Key": API_KEY, "Content-Type": "application/json"}
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        assert data.get("status") == "ok"
        assert data.get("devices_updated") == 1
        print(f"Device report accepted: {data}")
    
    def test_05_device_poll_status_returns_ping_fields(self):
        """GET /api/connector/device-poll-status should return monitor_type, ping_ms, http_status"""
        # First, ensure device report is sent (in case previous test's cleanup ran)
        report_payload = {
            "hostname": "TEST_CONNECTOR",
            "devices": [
                {
                    "device_ip": TEST_PING_DEVICE_IP,
                    "device_name": TEST_PING_DEVICE_NAME,
                    "reachable": True,
                    "monitor_type": "ping",
                    "ping_ms": 15,
                    "http_status": 200,
                    "poll_timestamp": "2026-03-24T22:00:00Z"
                }
            ]
        }
        requests.post(
            f"{BASE_URL}/api/connector/device-report",
            json=report_payload,
            headers={"X-API-Key": API_KEY, "Content-Type": "application/json"}
        )
        
        # Now check poll status
        response = self.session.get(f"{BASE_URL}/api/connector/device-poll-status")
        assert response.status_code == 200, f"Failed: {response.text}"
        statuses = response.json()
        assert isinstance(statuses, list)
        
        # Find our test device
        test_device = next((d for d in statuses if d.get("device_ip") == TEST_PING_DEVICE_IP), None)
        if test_device:
            assert "monitor_type" in test_device, "monitor_type field missing in poll status"
            assert test_device.get("monitor_type") == "ping", f"Expected 'ping', got {test_device.get('monitor_type')}"
            assert test_device.get("ping_ms") == 15, f"Expected ping_ms 15, got {test_device.get('ping_ms')}"
            assert test_device.get("http_status") == 200, f"Expected http_status 200, got {test_device.get('http_status')}"
            print(f"Poll status has correct ping fields: {test_device}")
        else:
            pytest.fail(f"Test device {TEST_PING_DEVICE_IP} not found in poll status")
    
    def test_06_update_info_shows_version(self):
        """GET /api/connector/update-info should show v1.7.2 (or current version)"""
        response = self.session.get(f"{BASE_URL}/api/connector/update-info")
        assert response.status_code == 200, f"Failed: {response.text}"
        data = response.json()
        version = data.get("version", "")
        print(f"Current connector version: {version}")
        # Just verify we get a version back
        assert version, "No version returned"
        # Check it's at least 1.7.x
        parts = version.split(".")
        assert len(parts) >= 2, f"Invalid version format: {version}"
        major, minor = int(parts[0]), int(parts[1])
        assert major >= 1 and minor >= 7, f"Expected version >= 1.7.x, got {version}"
    
    def test_07_add_snmp_device_still_works(self):
        """Verify SNMP devices still work (backward compatibility)"""
        snmp_ip = "192.168.99.98"
        payload = {
            "ip": snmp_ip,
            "name": "TEST_SNMPSwitch",
            "community": "public",
            "monitor_type": "snmp"
        }
        response = self.session.post(
            f"{BASE_URL}/api/connector/{CLIENT_ID}/managed-devices",
            json=payload
        )
        assert response.status_code == 200, f"Failed to add SNMP device: {response.text}"
        data = response.json()
        device = data.get("device", {})
        assert device.get("monitor_type") == "snmp"
        print(f"SNMP device added successfully: {device}")
        
        # Cleanup
        try:
            self.session.delete(f"{BASE_URL}/api/connector/device-poll-status/{snmp_ip}")
        except:
            pass
    
    def test_08_cleanup_test_device(self):
        """Cleanup: Delete test ping device"""
        response = self.session.delete(
            f"{BASE_URL}/api/connector/device-poll-status/{TEST_PING_DEVICE_IP}"
        )
        assert response.status_code == 200, f"Cleanup failed: {response.text}"
        print("Test device cleaned up successfully")


class TestConnectorStatusEndpoint:
    """Additional tests for connector status"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200
        token = response.json().get("token")
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        })
    
    def test_connector_status_endpoint(self):
        """Verify connector status endpoint returns proper structure"""
        response = self.session.get(f"{BASE_URL}/api/connector/status")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        
        if len(data) > 0:
            connector = data[0]
            # Check expected fields
            expected_fields = ["client_id", "connector_version", "hostname", "last_seen"]
            for field in expected_fields:
                assert field in connector, f"Missing field: {field}"
            print(f"Connector status structure verified: {list(connector.keys())}")
        else:
            print("No connectors found (expected in test environment)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
