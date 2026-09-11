"""
Test suite for 7 new NOC platform features (Iteration 39):
1. Grafici Trend (trend charts)
2. Auto-Discovery rete (network discovery approval/dismiss)
3. Soglie personalizzabili (custom thresholds)
4. Manutenzione programmata (maintenance windows)
5. Monitoraggio bandwidth
6. SOC AI Correlation
7. Multi-tenant client portal (PUBLIC endpoint)
"""
import pytest
import requests
import os
from datetime import datetime, timedelta

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
TEST_EMAIL = "admin@86bit.it"
TEST_PASSWORD = "password"
CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD
    })
    if response.status_code == 200:
        return response.json().get("token")
    pytest.skip(f"Authentication failed: {response.status_code} - {response.text}")


@pytest.fixture(scope="module")
def headers(auth_token):
    """Headers with auth token"""
    return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}


# ==================== TRENDS API TESTS ====================

class TestTrendsAPI:
    """Test GET /api/trends/{client_id}"""
    
    def test_trends_requires_auth(self):
        """Trends endpoint requires authentication"""
        response = requests.get(f"{BASE_URL}/api/trends/{CLIENT_ID}")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("PASS: Trends endpoint requires auth")
    
    def test_trends_returns_data(self, headers):
        """Trends endpoint returns trend data structure"""
        response = requests.get(f"{BASE_URL}/api/trends/{CLIENT_ID}?days=7", headers=headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "client_id" in data
        assert "days" in data
        assert "va_score_trend" in data
        assert "availability_trend" in data
        assert "alert_trend" in data
        assert isinstance(data["va_score_trend"], list)
        assert isinstance(data["availability_trend"], list)
        assert isinstance(data["alert_trend"], list)
        print(f"PASS: Trends returns data - VA trend: {len(data['va_score_trend'])} points, Availability: {len(data['availability_trend'])} points, Alerts: {len(data['alert_trend'])} points")


# ==================== THRESHOLDS API TESTS ====================

class TestThresholdsAPI:
    """Test GET/POST /api/thresholds/{client_id}"""
    
    def test_thresholds_requires_auth(self):
        """Thresholds endpoint requires authentication"""
        response = requests.get(f"{BASE_URL}/api/thresholds/{CLIENT_ID}")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("PASS: Thresholds endpoint requires auth")
    
    def test_get_thresholds_returns_data(self, headers):
        """GET thresholds returns threshold data"""
        response = requests.get(f"{BASE_URL}/api/thresholds/{CLIENT_ID}", headers=headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Check that we get a valid response with client_id
        assert "client_id" in data or "ping_max_ms" in data or "cpu_warning_pct" in data
        
        # Verify some threshold values exist (either defaults or custom)
        ping_max = data.get("ping_max_ms")
        cpu_warning = data.get("cpu_warning_pct")
        assert ping_max is not None or cpu_warning is not None, "Expected at least one threshold value"
        print(f"PASS: Thresholds returns data - ping_max_ms={ping_max}, cpu_warning_pct={cpu_warning}")
    
    def test_update_thresholds(self, headers):
        """POST thresholds updates values"""
        new_thresholds = {
            "ping_max_ms": 150,
            "cpu_warning_pct": 75
        }
        response = requests.post(f"{BASE_URL}/api/thresholds/{CLIENT_ID}", json=new_thresholds, headers=headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("status") == "ok"
        print("PASS: Thresholds updated successfully")
        
        # Verify update persisted
        get_response = requests.get(f"{BASE_URL}/api/thresholds/{CLIENT_ID}", headers=headers)
        assert get_response.status_code == 200
        updated = get_response.json()
        assert updated.get("ping_max_ms") == 150
        assert updated.get("cpu_warning_pct") == 75
        print("PASS: Thresholds update persisted correctly")


# ==================== MAINTENANCE WINDOWS API TESTS ====================

class TestMaintenanceAPI:
    """Test full CRUD for /api/maintenance/{client_id}"""
    
    created_window_id = None
    
    def test_maintenance_requires_auth(self):
        """Maintenance endpoint requires authentication"""
        response = requests.get(f"{BASE_URL}/api/maintenance/{CLIENT_ID}")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("PASS: Maintenance endpoint requires auth")
    
    def test_get_maintenance_windows(self, headers):
        """GET maintenance windows returns list"""
        response = requests.get(f"{BASE_URL}/api/maintenance/{CLIENT_ID}", headers=headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert isinstance(data, list)
        print(f"PASS: GET maintenance windows returns list with {len(data)} items")
    
    def test_create_maintenance_window(self, headers):
        """POST creates a new maintenance window"""
        start = (datetime.utcnow() + timedelta(hours=1)).isoformat() + "Z"
        end = (datetime.utcnow() + timedelta(hours=3)).isoformat() + "Z"
        
        payload = {
            "title": "TEST_Manutenzione Switch Core",
            "description": "Aggiornamento firmware switch",
            "start_time": start,
            "end_time": end,
            "device_ips": ["192.168.1.1", "192.168.1.2"],
            "suppress_alerts": True
        }
        
        response = requests.post(f"{BASE_URL}/api/maintenance/{CLIENT_ID}", json=payload, headers=headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "id" in data
        assert data.get("title") == "TEST_Manutenzione Switch Core"
        assert data.get("suppress_alerts") == True
        
        TestMaintenanceAPI.created_window_id = data["id"]
        print(f"PASS: Created maintenance window with ID: {data['id']}")
    
    def test_update_maintenance_window(self, headers):
        """PUT updates a maintenance window"""
        if not TestMaintenanceAPI.created_window_id:
            pytest.skip("No window created to update")
        
        payload = {
            "title": "TEST_Manutenzione Switch Core - UPDATED",
            "description": "Aggiornamento firmware switch - modificato"
        }
        
        response = requests.put(
            f"{BASE_URL}/api/maintenance/{CLIENT_ID}/{TestMaintenanceAPI.created_window_id}",
            json=payload,
            headers=headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: Updated maintenance window")
        
        # Verify update
        get_response = requests.get(f"{BASE_URL}/api/maintenance/{CLIENT_ID}", headers=headers)
        windows = get_response.json()
        updated_window = next((w for w in windows if w.get("id") == TestMaintenanceAPI.created_window_id), None)
        assert updated_window is not None
        assert "UPDATED" in updated_window.get("title", "")
        print("PASS: Maintenance window update verified")
    
    def test_delete_maintenance_window(self, headers):
        """DELETE removes a maintenance window"""
        if not TestMaintenanceAPI.created_window_id:
            pytest.skip("No window created to delete")
        
        response = requests.delete(
            f"{BASE_URL}/api/maintenance/{CLIENT_ID}/{TestMaintenanceAPI.created_window_id}",
            headers=headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: Deleted maintenance window")
        
        # Verify deletion
        get_response = requests.get(f"{BASE_URL}/api/maintenance/{CLIENT_ID}", headers=headers)
        windows = get_response.json()
        deleted_window = next((w for w in windows if w.get("id") == TestMaintenanceAPI.created_window_id), None)
        assert deleted_window is None
        print("PASS: Maintenance window deletion verified")
    
    def test_active_maintenance_check(self, headers):
        """GET /api/maintenance/active/{client_id} checks active maintenance"""
        response = requests.get(f"{BASE_URL}/api/maintenance/active/{CLIENT_ID}", headers=headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "in_maintenance" in data
        print(f"PASS: Active maintenance check - in_maintenance={data.get('in_maintenance')}")


# ==================== CORRELATION API TESTS ====================

class TestCorrelationAPI:
    """Test GET /api/correlation/{client_id}"""
    
    def test_correlation_requires_auth(self):
        """Correlation endpoint requires authentication"""
        response = requests.get(f"{BASE_URL}/api/correlation/{CLIENT_ID}")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("PASS: Correlation endpoint requires auth")
    
    def test_correlation_returns_analysis(self, headers):
        """Correlation endpoint returns analysis data"""
        response = requests.get(f"{BASE_URL}/api/correlation/{CLIENT_ID}", headers=headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "client_id" in data
        assert "total_devices" in data
        assert "offline_count" in data
        assert "active_alerts" in data
        assert "correlations" in data
        assert "correlation_count" in data
        assert "maintenance_active" in data
        assert isinstance(data["correlations"], list)
        
        print(f"PASS: Correlation analysis - devices={data['total_devices']}, offline={data['offline_count']}, alerts={data['active_alerts']}, correlations={data['correlation_count']}")


# ==================== BANDWIDTH API TESTS ====================

class TestBandwidthAPI:
    """Test bandwidth monitoring endpoints"""
    
    def test_bandwidth_summary_requires_auth(self):
        """Bandwidth summary requires authentication"""
        response = requests.get(f"{BASE_URL}/api/bandwidth/summary/{CLIENT_ID}")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("PASS: Bandwidth summary requires auth")
    
    def test_bandwidth_summary(self, headers):
        """GET bandwidth summary returns interface data"""
        response = requests.get(f"{BASE_URL}/api/bandwidth/summary/{CLIENT_ID}", headers=headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert isinstance(data, list)
        print(f"PASS: Bandwidth summary returns {len(data)} interfaces")
        
        if len(data) > 0:
            iface = data[0]
            assert "device_ip" in iface
            assert "if_name" in iface
            print(f"  Sample interface: {iface.get('device_ip')} - {iface.get('if_name')}")
    
    def test_bandwidth_history(self, headers):
        """GET bandwidth history for a device"""
        # First get summary to find a device
        summary_response = requests.get(f"{BASE_URL}/api/bandwidth/summary/{CLIENT_ID}", headers=headers)
        if summary_response.status_code != 200 or len(summary_response.json()) == 0:
            pytest.skip("No bandwidth data available")
        
        device_ip = summary_response.json()[0].get("device_ip")
        response = requests.get(f"{BASE_URL}/api/bandwidth/{CLIENT_ID}/{device_ip}?hours=24", headers=headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "device_ip" in data
        assert "interfaces" in data
        print(f"PASS: Bandwidth history for {device_ip} - {len(data.get('interfaces', []))} interfaces")
    
    def test_bandwidth_process_poll(self, headers):
        """POST bandwidth data from connector"""
        payload = {
            "client_id": CLIENT_ID,
            "interfaces": [
                {
                    "device_ip": "192.168.1.254",
                    "device_name": "TEST_Router",
                    "if_index": 1,
                    "if_name": "GigabitEthernet0/0",
                    "if_speed": 1000000000,
                    "in_octets": 123456789,
                    "out_octets": 987654321,
                    "in_bps": 50000000,
                    "out_bps": 30000000,
                    "utilization_pct": 5.0
                }
            ]
        }
        
        response = requests.post(f"{BASE_URL}/api/bandwidth/process-poll", json=payload, headers=headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("status") == "ok"
        assert data.get("interfaces_recorded") == 1
        print("PASS: Bandwidth poll data processed successfully")


# ==================== DISCOVERY API TESTS ====================

class TestDiscoveryAPI:
    """Test discovery approval/dismiss endpoints"""
    
    def test_discovery_approve_requires_auth(self):
        """Discovery approve requires authentication"""
        response = requests.post(f"{BASE_URL}/api/discovery/approve", json={})
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("PASS: Discovery approve requires auth")
    
    def test_discovery_approve_validation(self, headers):
        """Discovery approve validates required fields"""
        response = requests.post(f"{BASE_URL}/api/discovery/approve", json={}, headers=headers)
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        print("PASS: Discovery approve validates required fields")
    
    def test_discovery_approve_device(self, headers):
        """Discovery approve adds device to managed"""
        payload = {
            "client_id": CLIENT_ID,
            "ip": "192.168.99.99",
            "name": "TEST_Discovered_Device",
            "community": "public",
            "device_type": "network",
            "monitor_type": "snmp"
        }
        
        response = requests.post(f"{BASE_URL}/api/discovery/approve", json=payload, headers=headers)
        # Could be 200 (success) or 409 (already exists)
        assert response.status_code in [200, 409], f"Expected 200/409, got {response.status_code}: {response.text}"
        
        if response.status_code == 200:
            data = response.json()
            assert "id" in data
            assert data.get("ip") == "192.168.99.99"
            print(f"PASS: Discovery approved device with ID: {data['id']}")
        else:
            print("PASS: Discovery approve returned 409 (device already managed)")
    
    def test_discovery_dismiss(self, headers):
        """Discovery dismiss marks device as ignored"""
        payload = {
            "client_id": CLIENT_ID,
            "ip": "192.168.99.100"
        }
        
        response = requests.post(f"{BASE_URL}/api/discovery/dismiss", json=payload, headers=headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("status") == "ok"
        print("PASS: Discovery dismiss successful")


# ==================== CLIENT PORTAL API TESTS (PUBLIC) ====================

class TestClientPortalAPI:
    """Test GET /api/portal/{client_id} - PUBLIC endpoint (no auth required)"""
    
    def test_portal_no_auth_required(self):
        """Portal endpoint is PUBLIC - no auth required"""
        response = requests.get(f"{BASE_URL}/api/portal/{CLIENT_ID}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print("PASS: Portal endpoint is PUBLIC (no auth required)")
    
    def test_portal_returns_client_data(self):
        """Portal returns client dashboard data"""
        response = requests.get(f"{BASE_URL}/api/portal/{CLIENT_ID}")
        assert response.status_code == 200
        
        data = response.json()
        assert "client_name" in data
        assert "total_devices" in data
        assert "online" in data
        assert "offline" in data
        assert "sla_pct" in data
        assert "active_alerts" in data
        assert "alerts" in data
        assert "devices" in data
        assert "maintenance" in data
        assert "timestamp" in data
        
        print(f"PASS: Portal data - client={data['client_name']}, devices={data['total_devices']}, online={data['online']}, offline={data['offline']}, SLA={data['sla_pct']}%")
    
    def test_portal_invalid_client(self):
        """Portal returns 404 for invalid client"""
        response = requests.get(f"{BASE_URL}/api/portal/invalid-client-id-12345")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("PASS: Portal returns 404 for invalid client")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
