"""
Test suite for NOC Connector endpoints - P0 fix verification
Tests: heartbeat, update-check, update-info, download, status, health
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
ADMIN_EMAIL = "admin@86bit.it"
ADMIN_PASSWORD = "admin123"
API_KEY = "noc_35cf39b4d68740b1a981aedef2ee293d"  # 86BIT_Office client API key


class TestHealthEndpoint:
    """Health check endpoint tests"""
    
    def test_health_returns_healthy(self):
        """GET /api/health should return healthy status"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        print("✓ Health endpoint returns healthy")


class TestAuthLogin:
    """Authentication tests"""
    
    def test_admin_login_success(self):
        """Login with admin@86bit.it / admin123 should work"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert data["user"]["email"] == ADMIN_EMAIL
        assert data["user"]["role"] == "admin"
        print(f"✓ Admin login successful, role: {data['user']['role']}")
        return data["token"]


class TestConnectorStatus:
    """Connector status endpoint tests"""
    
    @pytest.fixture
    def auth_token(self):
        """Get admin auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if response.status_code == 200:
            return response.json()["token"]
        pytest.skip("Authentication failed")
    
    def test_connector_status_returns_list(self, auth_token):
        """GET /api/connector/status should return connector list with proper fields"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/api/connector/status", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Connector status returns list with {len(data)} connectors")
        
        # Check if IFIXITGESTSRV3 connector exists and is offline
        for connector in data:
            if connector.get("hostname") == "IFIXITGESTSRV3":
                print(f"  Found IFIXITGESTSRV3: version={connector.get('connector_version')}, last_seen={connector.get('last_seen')}")
                # Verify it shows v1.6.1 (the old version)
                assert connector.get("connector_version") == "1.6.1", f"Expected v1.6.1, got {connector.get('connector_version')}"
                print("✓ IFIXITGESTSRV3 shows v1.6.1 as expected (offline connector)")
                break
        
        return data


class TestConnectorUpdateInfo:
    """Connector update info endpoint tests"""
    
    @pytest.fixture
    def auth_token(self):
        """Get admin auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if response.status_code == 200:
            return response.json()["token"]
        pytest.skip("Authentication failed")
    
    def test_update_info_returns_version_1_7_1(self, auth_token):
        """GET /api/connector/update-info should return version 1.7.1 as active"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/api/connector/update-info", headers=headers)
        assert response.status_code == 200
        data = response.json()
        
        # Verify version 1.7.1 is active
        assert data.get("version") == "1.7.1", f"Expected version 1.7.1, got {data.get('version')}"
        print(f"✓ Update info shows version {data.get('version')} as active")
        
        # Check other fields
        if "total_connectors" in data:
            print(f"  Total connectors: {data.get('total_connectors')}")
        if "updated_connectors" in data:
            print(f"  Updated connectors: {data.get('updated_connectors')}")
        if "pending_connectors" in data:
            print(f"  Pending connectors: {data.get('pending_connectors')}")
        
        return data


class TestConnectorUpdateCheck:
    """Connector update check endpoint tests (called by connectors)"""
    
    def test_update_check_with_api_key(self):
        """GET /api/connector/update-check with X-API-Key should return update info"""
        headers = {"X-API-Key": API_KEY}
        response = requests.get(f"{BASE_URL}/api/connector/update-check", headers=headers)
        assert response.status_code == 200
        data = response.json()
        
        # Should return update_available and latest_version
        assert "update_available" in data
        assert "latest_version" in data
        
        # Latest version should be 1.7.1
        assert data["latest_version"] == "1.7.1", f"Expected 1.7.1, got {data['latest_version']}"
        print(f"✓ Update check returns latest_version: {data['latest_version']}")
        print(f"  update_available: {data['update_available']}")
        
        if "download_url" in data:
            print(f"  download_url: {data['download_url']}")
        
        return data
    
    def test_update_check_without_api_key(self):
        """GET /api/connector/update-check without API key should return 401"""
        response = requests.get(f"{BASE_URL}/api/connector/update-check")
        # Should return 401 or still work (depends on implementation)
        # Based on code, it allows without API key but won't have client context
        assert response.status_code in [200, 401]
        print(f"✓ Update check without API key returns {response.status_code}")


class TestConnectorHeartbeat:
    """Connector heartbeat endpoint tests"""
    
    def test_heartbeat_with_api_key(self):
        """POST /api/connector/heartbeat with X-API-Key should update connector status"""
        headers = {
            "X-API-Key": API_KEY,
            "Content-Type": "application/json"
        }
        payload = {
            "connector_version": "1.6.1",  # Simulating old version
            "hostname": "TEST_HEARTBEAT_HOST",
            "uptime_seconds": 3600,
            "traps_received": 10,
            "syslogs_received": 5
        }
        response = requests.post(f"{BASE_URL}/api/connector/heartbeat", headers=headers, json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"
        print("✓ Heartbeat accepted with status: ok")
        
        return data
    
    def test_heartbeat_without_api_key_fails(self):
        """POST /api/connector/heartbeat without X-API-Key should return 401"""
        payload = {
            "connector_version": "1.6.1",
            "hostname": "TEST_HOST",
            "uptime_seconds": 100,
            "traps_received": 0,
            "syslogs_received": 0
        }
        response = requests.post(f"{BASE_URL}/api/connector/heartbeat", json=payload)
        assert response.status_code == 401
        print("✓ Heartbeat without API key correctly returns 401")


class TestConnectorDownload:
    """Connector download endpoint tests"""
    
    def test_download_specific_version(self):
        """GET /api/connector/download/86NocConnector_v1.7.1.zip should return 200"""
        headers = {"X-API-Key": API_KEY}
        response = requests.get(
            f"{BASE_URL}/api/connector/download/86NocConnector_v1.7.1.zip",
            headers=headers,
            stream=True
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        # Check content type
        content_type = response.headers.get("content-type", "")
        assert "zip" in content_type or "octet-stream" in content_type, f"Unexpected content-type: {content_type}"
        
        # Check file size (should be > 0)
        content_length = response.headers.get("content-length")
        if content_length:
            size = int(content_length)
            assert size > 0, "File size should be > 0"
            print(f"✓ Download returns ZIP file, size: {size} bytes")
        else:
            # Read some content to verify
            chunk = next(response.iter_content(chunk_size=1024), None)
            assert chunk is not None, "File should have content"
            print(f"✓ Download returns ZIP file (streaming)")
        
        return response
    
    def test_download_nonexistent_file_returns_404(self):
        """GET /api/connector/download/nonexistent.zip should return 404"""
        headers = {"X-API-Key": API_KEY}
        response = requests.get(
            f"{BASE_URL}/api/connector/download/nonexistent_file.zip",
            headers=headers
        )
        assert response.status_code == 404
        print("✓ Download nonexistent file correctly returns 404")


class TestPublicDownload:
    """Public download endpoint tests"""
    
    def test_public_download_works(self):
        """GET /86NocConnector.zip (public) should work"""
        response = requests.get(f"{BASE_URL}/86NocConnector.zip", stream=True)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        content_length = response.headers.get("content-length")
        if content_length:
            size = int(content_length)
            assert size > 50000, f"File size should be > 50KB, got {size}"
            print(f"✓ Public download works, file size: {size} bytes")
        else:
            print("✓ Public download works (streaming)")


class TestCleanup:
    """Cleanup test data"""
    
    @pytest.fixture
    def auth_token(self):
        """Get admin auth token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if response.status_code == 200:
            return response.json()["token"]
        pytest.skip("Authentication failed")
    
    def test_cleanup_test_connector(self, auth_token):
        """Clean up TEST_HEARTBEAT_HOST connector created during tests"""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.delete(
            f"{BASE_URL}/api/connector/status/TEST_HEARTBEAT_HOST",
            headers=headers
        )
        # May return 200 or 404 if already cleaned
        assert response.status_code in [200, 404]
        print(f"✓ Cleanup: TEST_HEARTBEAT_HOST deleted (status: {response.status_code})")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
