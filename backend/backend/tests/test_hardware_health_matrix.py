"""
Test Hardware Health Matrix feature - iteration 54
Tests:
1. GET /api/tv/dashboard - hardware_health + ilo_server_count fields
2. GET /api/tv/clients/{client_id}/hardware-health - aggregated health endpoint
3. GET /api/redfish/metrics/{device_ip} - subsystems in latest response
4. Web Console V4 regression tests
"""
import pytest
import requests
import os
from datetime import datetime, timezone

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
TEST_CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"  # 86BIT_Office

class TestTvDashboardHardwareHealth:
    """Test /api/tv/dashboard hardware_health fields (no auth required)"""
    
    def test_tv_dashboard_returns_200(self):
        """TV dashboard endpoint should be accessible without auth"""
        response = requests.get(f"{BASE_URL}/api/tv/dashboard")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: GET /api/tv/dashboard returns 200")
    
    def test_tv_dashboard_has_clients_array(self):
        """Response should have clients array"""
        response = requests.get(f"{BASE_URL}/api/tv/dashboard")
        assert response.status_code == 200
        data = response.json()
        assert "clients" in data, "Response missing 'clients' field"
        assert isinstance(data["clients"], list), "'clients' should be a list"
        print(f"PASS: TV dashboard has {len(data['clients'])} clients")
    
    def test_tv_dashboard_client_has_hardware_health_field(self):
        """Each client should have hardware_health field (dict or null)"""
        response = requests.get(f"{BASE_URL}/api/tv/dashboard")
        assert response.status_code == 200
        data = response.json()
        
        for client in data["clients"]:
            assert "hardware_health" in client, f"Client {client.get('name')} missing 'hardware_health' field"
            hw = client["hardware_health"]
            # Should be dict with 8 keys or null
            if hw is not None:
                assert isinstance(hw, dict), f"hardware_health should be dict or null, got {type(hw)}"
                expected_keys = {"system", "thermal", "fans", "power", "memory", "storage", "processors", "network"}
                assert set(hw.keys()) == expected_keys, f"hardware_health missing keys: {expected_keys - set(hw.keys())}"
                print(f"  Client '{client.get('name')}' has hardware_health with 8 subsystems")
            else:
                print(f"  Client '{client.get('name')}' has hardware_health=null (no iLO)")
        
        print("PASS: All clients have hardware_health field")
    
    def test_tv_dashboard_client_has_ilo_server_count(self):
        """Each client should have ilo_server_count field (int)"""
        response = requests.get(f"{BASE_URL}/api/tv/dashboard")
        assert response.status_code == 200
        data = response.json()
        
        for client in data["clients"]:
            assert "ilo_server_count" in client, f"Client {client.get('name')} missing 'ilo_server_count' field"
            count = client["ilo_server_count"]
            assert isinstance(count, int), f"ilo_server_count should be int, got {type(count)}"
            assert count >= 0, f"ilo_server_count should be >= 0, got {count}"
            print(f"  Client '{client.get('name')}' has ilo_server_count={count}")
        
        print("PASS: All clients have ilo_server_count field")
    
    def test_tv_dashboard_no_ilo_means_null_health(self):
        """Clients with ilo_server_count=0 should have hardware_health=null"""
        response = requests.get(f"{BASE_URL}/api/tv/dashboard")
        assert response.status_code == 200
        data = response.json()
        
        for client in data["clients"]:
            if client["ilo_server_count"] == 0:
                assert client["hardware_health"] is None, \
                    f"Client '{client.get('name')}' has ilo_server_count=0 but hardware_health is not null"
        
        print("PASS: Clients without iLO have hardware_health=null")


class TestClientHardwareHealthEndpoint:
    """Test /api/tv/clients/{client_id}/hardware-health (no auth required)"""
    
    def test_hardware_health_endpoint_returns_200(self):
        """Endpoint should return 200 for valid client_id"""
        response = requests.get(f"{BASE_URL}/api/tv/clients/{TEST_CLIENT_ID}/hardware-health")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"PASS: GET /api/tv/clients/{TEST_CLIENT_ID}/hardware-health returns 200")
    
    def test_hardware_health_response_structure(self):
        """Response should have client_id, ilo_server_count, subsystems, per_device"""
        response = requests.get(f"{BASE_URL}/api/tv/clients/{TEST_CLIENT_ID}/hardware-health")
        assert response.status_code == 200
        data = response.json()
        
        assert "client_id" in data, "Response missing 'client_id'"
        assert data["client_id"] == TEST_CLIENT_ID, f"client_id mismatch: {data['client_id']}"
        
        assert "ilo_server_count" in data, "Response missing 'ilo_server_count'"
        assert isinstance(data["ilo_server_count"], int), "ilo_server_count should be int"
        
        assert "subsystems" in data, "Response missing 'subsystems'"
        # subsystems can be dict or null
        
        assert "per_device" in data, "Response missing 'per_device'"
        assert isinstance(data["per_device"], list), "per_device should be list"
        
        print(f"PASS: Response structure correct - ilo_server_count={data['ilo_server_count']}, per_device={len(data['per_device'])} devices")
    
    def test_hardware_health_subsystems_structure(self):
        """If subsystems is not null, it should have 8 keys"""
        response = requests.get(f"{BASE_URL}/api/tv/clients/{TEST_CLIENT_ID}/hardware-health")
        assert response.status_code == 200
        data = response.json()
        
        if data["subsystems"] is not None:
            expected_keys = {"system", "thermal", "fans", "power", "memory", "storage", "processors", "network"}
            assert set(data["subsystems"].keys()) == expected_keys, \
                f"subsystems missing keys: {expected_keys - set(data['subsystems'].keys())}"
            
            # Each value should be ok/warning/critical/unknown
            valid_values = {"ok", "warning", "critical", "unknown"}
            for key, value in data["subsystems"].items():
                assert value in valid_values, f"subsystems[{key}] has invalid value: {value}"
            
            print(f"PASS: subsystems has 8 valid keys: {data['subsystems']}")
        else:
            print("PASS: subsystems is null (no iLO devices)")
    
    def test_hardware_health_per_device_structure(self):
        """per_device items should have device_ip, device_name, subsystems"""
        response = requests.get(f"{BASE_URL}/api/tv/clients/{TEST_CLIENT_ID}/hardware-health")
        assert response.status_code == 200
        data = response.json()
        
        for device in data["per_device"]:
            assert "device_ip" in device, "per_device item missing 'device_ip'"
            assert "device_name" in device, "per_device item missing 'device_name'"
            assert "subsystems" in device, "per_device item missing 'subsystems'"
            
            # subsystems should be dict with 8 keys
            subs = device["subsystems"]
            assert isinstance(subs, dict), f"per_device subsystems should be dict"
            expected_keys = {"system", "thermal", "fans", "power", "memory", "storage", "processors", "network"}
            assert set(subs.keys()) == expected_keys, f"per_device subsystems missing keys"
            
            print(f"  Device {device['device_ip']} ({device['device_name']}): {subs}")
        
        if data["per_device"]:
            print(f"PASS: {len(data['per_device'])} devices have correct structure")
        else:
            print("PASS: per_device is empty (no iLO devices)")
    
    def test_hardware_health_nonexistent_client(self):
        """Nonexistent client_id should return ilo_server_count=0, subsystems=null, per_device=[]"""
        fake_client_id = "00000000-0000-0000-0000-000000000000"
        response = requests.get(f"{BASE_URL}/api/tv/clients/{fake_client_id}/hardware-health")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data["ilo_server_count"] == 0, f"Expected ilo_server_count=0, got {data['ilo_server_count']}"
        assert data["subsystems"] is None, f"Expected subsystems=null, got {data['subsystems']}"
        assert data["per_device"] == [], f"Expected per_device=[], got {data['per_device']}"
        
        print("PASS: Nonexistent client returns ilo_server_count=0, subsystems=null, per_device=[]")


class TestRedfishMetricsSubsystems:
    """Test /api/redfish/metrics/{device_ip} subsystems field (auth required)"""
    
    @pytest.fixture
    def auth_token(self):
        """Get auth token for admin user"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@86bit.it",
            "password": "password"
        })
        if response.status_code == 200:
            return response.json().get("token")  # API returns 'token' not 'access_token'
        pytest.skip("Authentication failed")
    
    def test_redfish_metrics_requires_auth(self):
        """Endpoint should require authentication"""
        response = requests.get(f"{BASE_URL}/api/redfish/metrics/192.168.1.1?minutes=60")
        assert response.status_code in [401, 403], f"Expected 401/403 without auth, got {response.status_code}"
        print("PASS: /api/redfish/metrics requires authentication")
    
    def test_redfish_metrics_with_auth(self, auth_token):
        """Endpoint should work with valid auth"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        # Use a test IP - may return 404 if no telemetry
        response = requests.get(f"{BASE_URL}/api/redfish/metrics/192.168.1.1?minutes=60", headers=headers)
        # 200 or 404 are both valid (depends on whether device has telemetry)
        assert response.status_code in [200, 404], f"Expected 200 or 404, got {response.status_code}"
        print(f"PASS: /api/redfish/metrics with auth returns {response.status_code}")
    
    def test_redfish_metrics_response_structure(self, auth_token):
        """If 200, response should have latest with subsystems"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/api/redfish/metrics/192.168.1.1?minutes=60", headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            assert "device_ip" in data, "Response missing 'device_ip'"
            assert "latest" in data, "Response missing 'latest'"
            assert "series" in data, "Response missing 'series'"
            
            # Check series has inlet_temperature and fan_max_percent
            series = data["series"]
            assert "inlet_temperature" in series, "series missing 'inlet_temperature'"
            assert "fan_max_percent" in series, "series missing 'fan_max_percent'"
            
            # Check latest has subsystems if present
            latest = data.get("latest")
            if latest:
                if "subsystems" in latest:
                    subs = latest["subsystems"]
                    expected_keys = {"system", "thermal", "fans", "power", "memory", "storage", "processors", "network"}
                    assert set(subs.keys()) == expected_keys, f"latest.subsystems missing keys"
                    print(f"PASS: latest.subsystems has 8 keys: {subs}")
                
                # Check inlet_celsius and fan_max_percent
                if "inlet_celsius" in latest:
                    print(f"  inlet_celsius: {latest['inlet_celsius']}")
                if "fan_max_percent" in latest:
                    print(f"  fan_max_percent: {latest['fan_max_percent']}")
                if "fan_count" in latest:
                    print(f"  fan_count: {latest['fan_count']}")
            
            print("PASS: Response structure correct")
        else:
            print(f"SKIP: No telemetry data for test device (404)")


class TestWebConsoleV4Regression:
    """Regression tests for Web Console V4 (from iteration 53)"""
    
    @pytest.fixture
    def auth_token(self):
        """Get auth token for admin user"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@86bit.it",
            "password": "password"
        })
        if response.status_code == 200:
            return response.json().get("token")  # API returns 'token' not 'access_token'
        pytest.skip("Authentication failed")
    
    def test_console_v4_request_session_valid(self, auth_token):
        """POST /api/console-v4/request-session with valid device returns session"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        # Use a device that exists in the system
        response = requests.post(
            f"{BASE_URL}/api/console-v4/request-session",
            headers=headers,
            json={"device_ip": "192.168.1.8", "port": 443}
        )
        # May return 200 or 404 depending on device existence
        if response.status_code == 200:
            data = response.json()
            assert "url" in data, "Response missing 'url'"
            assert "token" in data, "Response missing 'token'"
            assert "expires_at" in data, "Response missing 'expires_at'"
            assert "transport" in data, "Response missing 'transport'"
            assert "base_url" in data, "Response missing 'base_url'"
            print(f"PASS: request-session returns valid session structure")
        elif response.status_code == 404:
            print("PASS: request-session returns 404 for nonexistent device (expected)")
        else:
            pytest.fail(f"Unexpected status {response.status_code}: {response.text}")
    
    def test_console_v4_proxy_invalid_token(self):
        """Proxy with invalid token returns 401"""
        response = requests.get(f"{BASE_URL}/api/console-v4/s/invalid.token.here/")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: Proxy with invalid token returns 401")


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
