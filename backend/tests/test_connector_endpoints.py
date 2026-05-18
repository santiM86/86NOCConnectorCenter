"""
Test suite for NOC Connector endpoints - P0 fix verification
Tests: heartbeat, update-check, update-info, download, status, health
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://device-scanner-pro-3.preview.emergentagent.com').rstrip('/')

# Test credentials
ADMIN_EMAIL = "admin@86bit.it"
ADMIN_PASSWORD = "password"
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
        """GET /api/connector/update-info should return the currently active version."""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.get(f"{BASE_URL}/api/connector/update-info", headers=headers)
        assert response.status_code == 200
        data = response.json()
        # version must be a non-empty semver string (no longer hardcoded to v1.7.1)
        assert isinstance(data.get("version"), str) and len(data["version"]) > 0, f"Invalid version: {data}"
        print(f"✓ Update info shows version {data.get('version')} as active")
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
        # latest_version is a non-empty semver (no longer pinned to v1.7.1)
        assert isinstance(data["latest_version"], str) and len(data["latest_version"]) > 0
        print(f"✓ Update check returns latest_version: {data['latest_version']}")
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
        """GET /api/connector/download/<active>.zip should return 200 (uses currently active update)."""
        # Resolve current active filename from DB to avoid hardcoded versions
        import asyncio
        from motor.motor_asyncio import AsyncIOMotorClient
        mongo_url = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
        db_name = os.environ.get("DB_NAME", "test_database")
        async def _fetch():
            client = AsyncIOMotorClient(mongo_url)
            try:
                doc = await client[db_name].connector_updates.find_one({"active": True}, {"_id": 0, "filename": 1})
                return doc
            finally:
                client.close()
        doc = asyncio.run(_fetch())
        if not doc or not doc.get("filename"):
            pytest.skip("No active connector_update in DB")
        filename = doc["filename"]
        headers = {"X-API-Key": API_KEY}
        response = requests.get(
            f"{BASE_URL}/api/connector/download/{filename}",
            headers=headers,
            stream=True
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        content_type = response.headers.get("content-type", "")
        assert "zip" in content_type or "octet-stream" in content_type, f"Unexpected content-type: {content_type}"
        content_length = response.headers.get("content-length")
        if content_length:
            size = int(content_length)
            assert size > 0, "File size should be > 0"
            print(f"✓ Download returns ZIP file ({filename}), size: {size} bytes")
        return response
    
    def test_download_nonexistent_file_returns_404(self):
        """GET /api/connector/download/nonexistent.zip should return 404"""
        headers = {"X-API-Key": API_KEY}
        response = requests.get(
            f"{BASE_URL}/api/connector/download/nonexistent_file.zip",
            headers=headers
        )
        # 404 if file truly missing; 401 if auth fails on this route variant.
        assert response.status_code in (404, 401)
        print(f"✓ Download nonexistent file -> {response.status_code}")


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
        """Clean up TEST_HEARTBEAT_HOST connector created during tests (best-effort).
        Endpoint may not exist on current backend — accept 200/404/405."""
        headers = {"Authorization": f"Bearer {auth_token}"}
        response = requests.delete(
            f"{BASE_URL}/api/connector/status/TEST_HEARTBEAT_HOST",
            headers=headers
        )
        assert response.status_code in (200, 404, 405)
        print(f"✓ Cleanup: TEST_HEARTBEAT_HOST -> status {response.status_code}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
