"""
Backend API tests for NOC Alert Command Center - New Features
Tests: Connector status, Stats summary, Health endpoint, PWA manifest, Connector ZIP
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestHealthAndBasicEndpoints:
    """Health check and basic endpoint tests"""
    
    def test_health_endpoint(self):
        """Test GET /api/health returns healthy status"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        print("✓ Health endpoint returns healthy status")
    
    def test_pwa_manifest(self):
        """Test PWA manifest.json is served correctly"""
        response = requests.get(f"{BASE_URL}/manifest.json")
        assert response.status_code == 200
        data = response.json()
        assert data["short_name"] == "NOC Center"
        assert data["name"] == "NOC Command Center - Alert Management"
        assert data["display"] == "standalone"
        assert "icons" in data
        print("✓ PWA manifest.json served correctly")
    
    def test_connector_zip_download(self):
        """Test 86NocConnector.zip is available for download"""
        response = requests.head(f"{BASE_URL}/86NocConnector.zip")
        assert response.status_code == 200
        assert response.headers.get("content-type") == "application/zip"
        print("✓ 86NocConnector.zip available for download")


class TestAuthenticatedEndpoints:
    """Tests requiring authentication"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Login and get auth token"""
        login_response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "admin@test.it", "password": "TestAdmin123!"}
        )
        assert login_response.status_code == 200, f"Login failed: {login_response.text}"
        self.token = login_response.json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
        print("✓ Login successful")
    
    def test_connector_status_endpoint(self):
        """Test GET /api/connector/status returns connector data without _id field"""
        response = requests.get(f"{BASE_URL}/api/connector/status", headers=self.headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        
        # Check that no _id field is present (MongoDB ObjectId issue)
        for connector in data:
            assert "_id" not in connector, "MongoDB _id field should not be in response"
            # Verify expected fields
            if connector:
                expected_fields = ["client_id", "client_name", "connector_version", "hostname", "last_seen"]
                for field in expected_fields:
                    assert field in connector, f"Missing field: {field}"
        
        print(f"✓ Connector status endpoint returns {len(data)} connectors without _id field")
    
    def test_stats_summary_endpoint(self):
        """Test GET /api/stats/summary returns stats data without _id field"""
        response = requests.get(f"{BASE_URL}/api/stats/summary", headers=self.headers)
        assert response.status_code == 200
        data = response.json()
        
        # Check that no _id field is present
        assert "_id" not in data, "MongoDB _id field should not be in response"
        
        # Verify expected fields
        expected_fields = ["critical", "high", "medium", "low", "total_active", "total_clients", "total_devices"]
        for field in expected_fields:
            assert field in data, f"Missing field: {field}"
            assert isinstance(data[field], int), f"Field {field} should be an integer"
        
        print(f"✓ Stats summary endpoint returns data: {data}")
    
    def test_login_flow(self):
        """Test login with admin credentials succeeds"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "admin@test.it", "password": "TestAdmin123!"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert "user" in data
        assert data["user"]["email"] == "admin@test.it"
        print("✓ Login flow works correctly")
    
    def test_alerts_endpoint(self):
        """Test GET /api/alerts returns alerts list"""
        response = requests.get(f"{BASE_URL}/api/alerts", headers=self.headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        
        # Check alert structure if alerts exist
        if data:
            alert = data[0]
            expected_fields = ["id", "severity", "title", "status", "created_at"]
            for field in expected_fields:
                assert field in alert, f"Missing field: {field}"
        
        print(f"✓ Alerts endpoint returns {len(data)} alerts")
    
    def test_clients_endpoint(self):
        """Test GET /api/clients returns clients list"""
        response = requests.get(f"{BASE_URL}/api/clients", headers=self.headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Clients endpoint returns {len(data)} clients")
    
    def test_devices_endpoint(self):
        """Test GET /api/devices returns devices list"""
        response = requests.get(f"{BASE_URL}/api/devices", headers=self.headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Devices endpoint returns {len(data)} devices")
    
    def test_stats_trends_endpoint(self):
        """Test GET /api/stats/trends returns trend data"""
        response = requests.get(f"{BASE_URL}/api/stats/trends?hours=24", headers=self.headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Stats trends endpoint returns {len(data)} data points")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
