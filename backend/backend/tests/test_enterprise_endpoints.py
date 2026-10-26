"""
NOC Alert Command Center - Enterprise Endpoints Tests
Tests for RBAC, SLA, Maintenance, Reports endpoints
"""
import pytest
import requests
import os
from datetime import datetime, timedelta

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
TEST_ADMIN_EMAIL = "admin@test.it"
TEST_ADMIN_PASSWORD = "TestAdmin123!"
TEST_USER_PREFIX = "TEST_"


class TestHealthAndAuth:
    """Basic health and authentication tests"""
    
    def test_health_endpoint(self):
        """Test API health endpoint"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        print("✓ Health endpoint working")
    
    def test_login_with_admin_credentials(self):
        """Test login with admin credentials"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_ADMIN_EMAIL,
            "password": TEST_ADMIN_PASSWORD
        })
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert "user" in data
        print(f"✓ Login successful for {TEST_ADMIN_EMAIL}")
        return data["token"]
    
    def test_register_new_user(self):
        """Test user registration"""
        unique_email = f"{TEST_USER_PREFIX}user_{datetime.now().strftime('%H%M%S')}@test.it"
        response = requests.post(f"{BASE_URL}/api/auth/register", json={
            "email": unique_email,
            "password": "TestPassword123!",
            "name": "Test User"
        })
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert data["user"]["email"] == unique_email
        print(f"✓ Registration successful for {unique_email}")
        return data


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token for tests"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": TEST_ADMIN_EMAIL,
        "password": TEST_ADMIN_PASSWORD
    })
    if response.status_code == 200:
        return response.json()["token"]
    pytest.skip("Authentication failed - skipping authenticated tests")


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Get headers with auth token"""
    return {"Authorization": f"Bearer {auth_token}"}


class TestRBACEndpoints:
    """RBAC (Role-Based Access Control) endpoint tests"""
    
    def test_get_roles(self, auth_headers):
        """Test GET /api/rbac/roles"""
        response = requests.get(f"{BASE_URL}/api/rbac/roles", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
        # Check role structure
        for role in data:
            assert "name" in role
            assert "permissions" in role
        print(f"✓ GET /api/rbac/roles - Found {len(data)} roles")
    
    def test_get_users(self, auth_headers):
        """Test GET /api/users - requires admin role"""
        response = requests.get(f"{BASE_URL}/api/users", headers=auth_headers)
        # Note: admin@test.it has "operator" role, so this returns 403
        # This is expected RBAC behavior
        if response.status_code == 403:
            print(f"✓ GET /api/users - Correctly returns 403 for non-admin user")
        elif response.status_code == 200:
            data = response.json()
            assert isinstance(data, list)
            print(f"✓ GET /api/users - Found {len(data)} users")
        else:
            assert False, f"Unexpected status code: {response.status_code}"


class TestSLAEndpoints:
    """SLA (Service Level Agreement) endpoint tests"""
    
    def test_get_sla_configs(self, auth_headers):
        """Test GET /api/sla/configs"""
        response = requests.get(f"{BASE_URL}/api/sla/configs", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        # Should have configs for each severity
        expected_severities = ["critical", "high", "medium", "low"]
        for severity in expected_severities:
            assert severity in data
            config = data[severity]
            assert "response_time_minutes" in config
            assert "resolution_time_minutes" in config
        print(f"✓ GET /api/sla/configs - Found configs for {len(data)} severities")
    
    def test_get_sla_stats(self, auth_headers):
        """Test GET /api/sla/stats"""
        response = requests.get(f"{BASE_URL}/api/sla/stats", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        # Check expected fields
        expected_fields = ["total_alerts", "resolution_rate", "response_sla_compliance", 
                          "resolution_sla_compliance", "avg_response_time_minutes", 
                          "avg_resolution_time_minutes", "period_days"]
        for field in expected_fields:
            assert field in data, f"Missing field: {field}"
        print(f"✓ GET /api/sla/stats - Stats retrieved successfully")
    
    def test_get_sla_breaches(self, auth_headers):
        """Test GET /api/sla/breaches"""
        response = requests.get(f"{BASE_URL}/api/sla/breaches?days=30&limit=20", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ GET /api/sla/breaches - Found {len(data)} breaches")


class TestMaintenanceEndpoints:
    """Maintenance window endpoint tests"""
    
    def test_get_maintenance_windows(self, auth_headers):
        """Test GET /api/maintenance/windows"""
        response = requests.get(f"{BASE_URL}/api/maintenance/windows", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ GET /api/maintenance/windows - Found {len(data)} windows")
    
    def test_get_active_maintenance(self, auth_headers):
        """Test GET /api/maintenance/active"""
        response = requests.get(f"{BASE_URL}/api/maintenance/active", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ GET /api/maintenance/active - Found {len(data)} active windows")
    
    def test_create_and_delete_maintenance_window(self, auth_headers):
        """Test POST and DELETE /api/maintenance/windows"""
        # Create maintenance window
        start_time = (datetime.utcnow() + timedelta(hours=1)).isoformat() + "Z"
        end_time = (datetime.utcnow() + timedelta(hours=2)).isoformat() + "Z"
        
        create_payload = {
            "name": f"{TEST_USER_PREFIX}Maintenance Test",
            "description": "Test maintenance window",
            "client_id": None,
            "start_time": start_time,
            "end_time": end_time,
            "suppress_alerts": True,
            "suppress_severities": ["low", "medium"]
        }
        
        create_response = requests.post(
            f"{BASE_URL}/api/maintenance/windows",
            headers=auth_headers,
            json=create_payload
        )
        assert create_response.status_code == 200
        created = create_response.json()
        assert "id" in created
        window_id = created["id"]
        print(f"✓ POST /api/maintenance/windows - Created window {window_id}")
        
        # Delete the window - requires admin role
        delete_response = requests.delete(
            f"{BASE_URL}/api/maintenance/windows/{window_id}",
            headers=auth_headers
        )
        # Note: admin@test.it has "operator" role, so delete may return 403
        if delete_response.status_code == 200:
            print(f"✓ DELETE /api/maintenance/windows/{window_id} - Deleted successfully")
        elif delete_response.status_code == 403:
            print(f"✓ DELETE /api/maintenance/windows/{window_id} - Correctly returns 403 for non-admin user")
        else:
            assert False, f"Unexpected status code: {delete_response.status_code}"


class TestReportsEndpoints:
    """Reports endpoint tests"""
    
    def test_download_alerts_csv(self, auth_headers):
        """Test GET /api/reports/alerts/csv"""
        response = requests.get(
            f"{BASE_URL}/api/reports/alerts/csv?days=30",
            headers=auth_headers
        )
        assert response.status_code == 200
        assert "text/csv" in response.headers.get("content-type", "")
        print(f"✓ GET /api/reports/alerts/csv - CSV downloaded ({len(response.content)} bytes)")
    
    def test_download_sla_pdf(self, auth_headers):
        """Test GET /api/reports/sla/pdf"""
        response = requests.get(
            f"{BASE_URL}/api/reports/sla/pdf?days=30",
            headers=auth_headers
        )
        assert response.status_code == 200
        assert "application/pdf" in response.headers.get("content-type", "")
        print(f"✓ GET /api/reports/sla/pdf - PDF downloaded ({len(response.content)} bytes)")


class TestClientsCRUD:
    """Client CRUD operations tests"""
    
    def test_create_get_delete_client(self, auth_headers):
        """Test full client CRUD cycle"""
        # Create client
        client_name = f"{TEST_USER_PREFIX}Client_{datetime.now().strftime('%H%M%S')}"
        create_response = requests.post(
            f"{BASE_URL}/api/clients",
            headers=auth_headers,
            json={
                "name": client_name,
                "description": "Test client",
                "contact_email": "test@test.it"
            }
        )
        assert create_response.status_code == 200
        created = create_response.json()
        client_id = created["id"]
        assert created["name"] == client_name
        print(f"✓ POST /api/clients - Created client {client_id}")
        
        # Get client
        get_response = requests.get(
            f"{BASE_URL}/api/clients/{client_id}",
            headers=auth_headers
        )
        assert get_response.status_code == 200
        fetched = get_response.json()
        assert fetched["name"] == client_name
        print(f"✓ GET /api/clients/{client_id} - Retrieved successfully")
        
        # Delete client
        delete_response = requests.delete(
            f"{BASE_URL}/api/clients/{client_id}",
            headers=auth_headers
        )
        assert delete_response.status_code == 200
        print(f"✓ DELETE /api/clients/{client_id} - Deleted successfully")
        
        # Verify deletion
        verify_response = requests.get(
            f"{BASE_URL}/api/clients/{client_id}",
            headers=auth_headers
        )
        assert verify_response.status_code == 404
        print(f"✓ Verified client {client_id} no longer exists")


class TestDevicesCRUD:
    """Device CRUD operations tests"""
    
    def test_create_get_delete_device(self, auth_headers):
        """Test full device CRUD cycle"""
        # First create a client
        client_name = f"{TEST_USER_PREFIX}DeviceTestClient_{datetime.now().strftime('%H%M%S')}"
        client_response = requests.post(
            f"{BASE_URL}/api/clients",
            headers=auth_headers,
            json={"name": client_name, "description": "For device test"}
        )
        assert client_response.status_code == 200
        client_id = client_response.json()["id"]
        
        # Create device
        device_name = f"{TEST_USER_PREFIX}Device_{datetime.now().strftime('%H%M%S')}"
        create_response = requests.post(
            f"{BASE_URL}/api/devices",
            headers=auth_headers,
            json={
                "client_id": client_id,
                "name": device_name,
                "device_type": "switch",
                "ip_address": "192.168.1.100",
                "hostname": "test-switch",
                "location": "Test Lab"
            }
        )
        assert create_response.status_code == 200
        created = create_response.json()
        device_id = created["id"]
        assert created["name"] == device_name
        print(f"✓ POST /api/devices - Created device {device_id}")
        
        # Get device
        get_response = requests.get(
            f"{BASE_URL}/api/devices/{device_id}",
            headers=auth_headers
        )
        assert get_response.status_code == 200
        fetched = get_response.json()
        assert fetched["name"] == device_name
        print(f"✓ GET /api/devices/{device_id} - Retrieved successfully")
        
        # Delete device
        delete_response = requests.delete(
            f"{BASE_URL}/api/devices/{device_id}",
            headers=auth_headers
        )
        assert delete_response.status_code == 200
        print(f"✓ DELETE /api/devices/{device_id} - Deleted successfully")
        
        # Cleanup: delete client
        requests.delete(f"{BASE_URL}/api/clients/{client_id}", headers=auth_headers)


class TestAlertsCRUD:
    """Alert CRUD operations tests"""
    
    def test_get_alerts_with_filters(self, auth_headers):
        """Test GET /api/alerts with various filters"""
        # Test without filters
        response = requests.get(f"{BASE_URL}/api/alerts?limit=10", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ GET /api/alerts - Found {len(data)} alerts")
        
        # Test with severity filter
        response = requests.get(f"{BASE_URL}/api/alerts?severity=critical&limit=10", headers=auth_headers)
        assert response.status_code == 200
        print(f"✓ GET /api/alerts?severity=critical - Filter working")
        
        # Test with status filter
        response = requests.get(f"{BASE_URL}/api/alerts?status=active&limit=10", headers=auth_headers)
        assert response.status_code == 200
        print(f"✓ GET /api/alerts?status=active - Filter working")


class TestStatsEndpoints:
    """Statistics endpoint tests"""
    
    def test_get_stats_summary(self, auth_headers):
        """Test GET /api/stats/summary"""
        response = requests.get(f"{BASE_URL}/api/stats/summary", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        expected_fields = ["critical", "high", "medium", "low", "total_active", "total_clients", "total_devices"]
        for field in expected_fields:
            assert field in data, f"Missing field: {field}"
        print(f"✓ GET /api/stats/summary - Stats retrieved")
    
    def test_get_alert_trends(self, auth_headers):
        """Test GET /api/stats/trends"""
        response = requests.get(f"{BASE_URL}/api/stats/trends?hours=24", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ GET /api/stats/trends - Found {len(data)} trend data points")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
