"""
Test suite to validate server.py refactoring from 3247 lines to modular routes.
Tests all critical endpoints to ensure refactoring didn't break functionality.
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials from iteration_19.json
TEST_USER_EMAIL = "test_refactor@86bit.it"
TEST_USER_PASSWORD = "Test1234!"
ADMIN_EMAIL = "admin@86bit.it"
ADMIN_PASSWORD = "admin123"


class TestHealthAndRoot:
    """Health check and root endpoint tests"""
    
    def test_health_endpoint(self):
        """GET /api/health - should return healthy status"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200, f"Health check failed: {response.text}"
        data = response.json()
        assert data.get("status") == "healthy"
        print("✓ Health endpoint working")
    
    def test_root_endpoint(self):
        """GET /api/ - should return API info"""
        response = requests.get(f"{BASE_URL}/api/")
        assert response.status_code == 200, f"Root endpoint failed: {response.text}"
        data = response.json()
        assert "NOC Alert Command Center" in data.get("message", "")
        assert data.get("version") == "2.0.0"
        print("✓ Root endpoint working")


class TestAuthentication:
    """Authentication endpoint tests - routes/auth.py"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get auth token for test user"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_USER_EMAIL,
            "password": TEST_USER_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("token")
        # Try admin if test user doesn't exist
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("token")
        pytest.skip(f"Authentication failed: {response.text}")
    
    def test_login_valid_credentials(self):
        """POST /api/auth/login - login with valid credentials"""
        # Try test_refactor user first
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": TEST_USER_EMAIL,
            "password": TEST_USER_PASSWORD
        })
        if response.status_code != 200:
            # Fallback to admin
            response = requests.post(f"{BASE_URL}/api/auth/login", json={
                "email": ADMIN_EMAIL,
                "password": ADMIN_PASSWORD
            })
        
        assert response.status_code == 200, f"Login failed: {response.text}"
        data = response.json()
        assert "token" in data, "No token in response"
        assert "user" in data, "No user in response"
        assert "email" in data["user"], "No email in user"
        print(f"✓ Login successful for {data['user']['email']}")
    
    def test_login_invalid_credentials(self):
        """POST /api/auth/login - should reject invalid credentials"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "invalid@test.com",
            "password": "wrongpassword"
        })
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("✓ Invalid credentials rejected correctly")
    
    def test_get_current_user(self, auth_token):
        """GET /api/auth/me - get current user with bearer token"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/api/auth/me", headers=headers)
        assert response.status_code == 200, f"Get me failed: {response.text}"
        data = response.json()
        assert "id" in data, "No id in response"
        assert "email" in data, "No email in response"
        assert "role" in data, "No role in response"
        print(f"✓ Get current user working - {data['email']} ({data['role']})")
    
    def test_auth_without_token(self):
        """GET /api/auth/me - should fail without token"""
        response = requests.get(f"{BASE_URL}/api/auth/me")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("✓ Auth without token rejected correctly")


class TestClients:
    """Client endpoint tests - routes/clients.py"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("token")
        pytest.skip("Authentication failed")
    
    def test_list_clients(self, auth_token):
        """GET /api/clients - list all clients"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/api/clients", headers=headers)
        assert response.status_code == 200, f"List clients failed: {response.text}"
        data = response.json()
        assert isinstance(data, list), "Response should be a list"
        print(f"✓ List clients working - {len(data)} clients found")


class TestDevices:
    """Device endpoint tests - routes/devices.py"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("token")
        pytest.skip("Authentication failed")
    
    def test_list_devices(self, auth_token):
        """GET /api/devices - list all devices"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/api/devices", headers=headers)
        assert response.status_code == 200, f"List devices failed: {response.text}"
        data = response.json()
        assert isinstance(data, list), "Response should be a list"
        print(f"✓ List devices working - {len(data)} devices found")


class TestAlerts:
    """Alert endpoint tests - routes/alerts.py"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("token")
        pytest.skip("Authentication failed")
    
    def test_list_alerts(self, auth_token):
        """GET /api/alerts - list all alerts"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/api/alerts", headers=headers)
        assert response.status_code == 200, f"List alerts failed: {response.text}"
        data = response.json()
        assert isinstance(data, list), "Response should be a list"
        print(f"✓ List alerts working - {len(data)} alerts found")
    
    def test_stats_summary(self, auth_token):
        """GET /api/stats/summary - get stats summary"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/api/stats/summary", headers=headers)
        assert response.status_code == 200, f"Stats summary failed: {response.text}"
        data = response.json()
        assert "critical" in data, "No critical count in response"
        assert "high" in data, "No high count in response"
        assert "total_active" in data, "No total_active in response"
        print(f"✓ Stats summary working - {data['total_active']} active alerts")


class TestConnector:
    """Connector endpoint tests - routes/connector.py"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("token")
        pytest.skip("Authentication failed")
    
    def test_connector_status(self, auth_token):
        """GET /api/connector/status - get connector status"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/api/connector/status", headers=headers)
        assert response.status_code == 200, f"Connector status failed: {response.text}"
        data = response.json()
        assert isinstance(data, list), "Response should be a list"
        print(f"✓ Connector status working - {len(data)} connectors found")
    
    def test_device_poll_status(self, auth_token):
        """GET /api/connector/device-poll-status - get device poll statuses"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/api/connector/device-poll-status", headers=headers)
        assert response.status_code == 200, f"Device poll status failed: {response.text}"
        data = response.json()
        assert isinstance(data, list), "Response should be a list"
        print(f"✓ Device poll status working - {len(data)} devices found")
    
    def test_connector_update_info(self, auth_token):
        """GET /api/connector/update-info - get connector update info"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/api/connector/update-info", headers=headers)
        assert response.status_code == 200, f"Update info failed: {response.text}"
        data = response.json()
        assert "version" in data or "total_connectors" in data, "Missing expected fields"
        print(f"✓ Connector update info working")


class TestSettings:
    """Settings endpoint tests - routes/settings.py"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("token")
        pytest.skip("Authentication failed")
    
    def test_notification_settings(self, auth_token):
        """GET /api/settings/notifications - get notification settings"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/api/settings/notifications", headers=headers)
        assert response.status_code == 200, f"Notification settings failed: {response.text}"
        data = response.json()
        assert isinstance(data, dict), "Response should be a dict"
        print(f"✓ Notification settings working")


class TestAudit:
    """Audit endpoint tests - routes/audit_routes.py"""
    
    @pytest.fixture(scope="class")
    def auth_token(self):
        """Get auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if response.status_code == 200:
            return response.json().get("token")
        pytest.skip("Authentication failed")
    
    def test_audit_logs(self, auth_token):
        """GET /api/audit/logs - get audit logs"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/api/audit/logs", headers=headers)
        assert response.status_code == 200, f"Audit logs failed: {response.text}"
        data = response.json()
        assert isinstance(data, list), "Response should be a list"
        print(f"✓ Audit logs working - {len(data)} logs found")


class TestSecurityHeaders:
    """Test security headers are present after refactoring"""
    
    def test_security_headers_present(self):
        """Verify security headers are added by middleware"""
        response = requests.get(f"{BASE_URL}/api/health")
        headers = response.headers
        
        # Check critical security headers
        assert "X-Frame-Options" in headers, "Missing X-Frame-Options header"
        assert "X-Content-Type-Options" in headers, "Missing X-Content-Type-Options header"
        assert "X-XSS-Protection" in headers, "Missing X-XSS-Protection header"
        print("✓ Security headers present")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
