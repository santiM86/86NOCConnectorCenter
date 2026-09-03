"""
Test Web Console Proxy and Monitor Type Switching Features
Tests for iteration 9: Web Console Proxy, monitor type switching, security checks
"""
import pytest
import requests
import os
import uuid
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials from iteration_8.json
ADMIN_EMAIL = "admin@86bit.it"
ADMIN_PASSWORD = "admin123"
API_KEY = "noc_35cf39b4d68740b1a981aedef2ee293d"
CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"


class TestAuthentication:
    """Test login and role-based access"""
    
    def test_admin_login(self):
        """Test admin login with correct credentials"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200, f"Login failed: {response.text}"
        data = response.json()
        assert "token" in data
        assert data["user"]["role"] == "admin"
        print(f"✓ Admin login successful, role: {data['user']['role']}")


class TestWebProxyEndpoints:
    """Test Web Console Proxy endpoints"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Get auth token for tests"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200
        self.token = response.json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_create_web_proxy_request_success(self):
        """POST /api/connector/web-proxy/request - create proxy request for managed device"""
        # First, ensure we have a managed device
        # Use existing device from discovery results (192.168.1.1 or 192.168.1.3)
        response = requests.post(
            f"{BASE_URL}/api/connector/web-proxy/request",
            headers=self.headers,
            json={
                "client_id": CLIENT_ID,
                "device_ip": "192.168.1.3",  # Netgear device from test data
                "port": 80,
                "path": "/",
                "method": "GET"
            }
        )
        assert response.status_code == 200, f"Failed to create proxy request: {response.text}"
        data = response.json()
        assert "request_id" in data
        assert data["status"] == "pending"
        print(f"✓ Web proxy request created: {data['request_id']}")
        return data["request_id"]
    
    def test_create_web_proxy_request_non_managed_device(self):
        """POST /api/connector/web-proxy/request - should fail for non-managed device IP"""
        response = requests.post(
            f"{BASE_URL}/api/connector/web-proxy/request",
            headers=self.headers,
            json={
                "client_id": CLIENT_ID,
                "device_ip": "10.99.99.99",  # Non-existent device
                "port": 80,
                "path": "/",
                "method": "GET"
            }
        )
        assert response.status_code == 403, f"Expected 403 for non-managed device, got {response.status_code}: {response.text}"
        print("✓ Non-managed device correctly rejected with 403")
    
    def test_get_pending_requests_with_api_key(self):
        """GET /api/connector/web-proxy/pending - connector polls for pending requests"""
        # First create a request
        create_response = requests.post(
            f"{BASE_URL}/api/connector/web-proxy/request",
            headers=self.headers,
            json={
                "client_id": CLIENT_ID,
                "device_ip": "192.168.1.3",
                "port": 80,
                "path": "/test",
                "method": "GET"
            }
        )
        assert create_response.status_code == 200
        request_id = create_response.json()["request_id"]
        
        # Now poll for pending requests with API key
        response = requests.get(
            f"{BASE_URL}/api/connector/web-proxy/pending",
            headers={"X-API-Key": API_KEY}
        )
        assert response.status_code == 200, f"Failed to get pending requests: {response.text}"
        data = response.json()
        assert "requests" in data
        print(f"✓ Got pending requests: {len(data['requests'])} requests")
    
    def test_get_pending_requests_without_api_key(self):
        """GET /api/connector/web-proxy/pending - should fail without API key"""
        response = requests.get(f"{BASE_URL}/api/connector/web-proxy/pending")
        assert response.status_code == 401, f"Expected 401 without API key, got {response.status_code}"
        print("✓ Pending requests correctly requires API key")
    
    def test_submit_web_proxy_response(self):
        """POST /api/connector/web-proxy/response - connector submits HTML response"""
        # First create a request
        create_response = requests.post(
            f"{BASE_URL}/api/connector/web-proxy/request",
            headers=self.headers,
            json={
                "client_id": CLIENT_ID,
                "device_ip": "192.168.1.3",
                "port": 80,
                "path": "/",
                "method": "GET"
            }
        )
        assert create_response.status_code == 200
        request_id = create_response.json()["request_id"]
        
        # Poll to mark as in_progress
        requests.get(
            f"{BASE_URL}/api/connector/web-proxy/pending",
            headers={"X-API-Key": API_KEY}
        )
        
        # Submit response
        response = requests.post(
            f"{BASE_URL}/api/connector/web-proxy/response",
            headers={"X-API-Key": API_KEY},
            json={
                "request_id": request_id,
                "status_code": 200,
                "content_type": "text/html",
                "body": "<html><head><title>Test Device</title></head><body><h1>Device Web Console</h1></body></html>",
                "title": "Test Device Console"
            }
        )
        assert response.status_code == 200, f"Failed to submit response: {response.text}"
        print(f"✓ Web proxy response submitted for request {request_id}")
        return request_id
    
    def test_get_web_proxy_response(self):
        """GET /api/connector/web-proxy/response/{request_id} - get completed response"""
        # Create and complete a request
        create_response = requests.post(
            f"{BASE_URL}/api/connector/web-proxy/request",
            headers=self.headers,
            json={
                "client_id": CLIENT_ID,
                "device_ip": "192.168.1.3",
                "port": 80,
                "path": "/",
                "method": "GET"
            }
        )
        assert create_response.status_code == 200
        request_id = create_response.json()["request_id"]
        
        # Poll to mark as in_progress
        requests.get(
            f"{BASE_URL}/api/connector/web-proxy/pending",
            headers={"X-API-Key": API_KEY}
        )
        
        # Submit response
        html_body = "<html><head><title>Netgear Switch</title></head><body><h1>Netgear GS108E</h1></body></html>"
        requests.post(
            f"{BASE_URL}/api/connector/web-proxy/response",
            headers={"X-API-Key": API_KEY},
            json={
                "request_id": request_id,
                "status_code": 200,
                "content_type": "text/html",
                "body": html_body,
                "title": "Netgear GS108E"
            }
        )
        
        # Get the response
        response = requests.get(
            f"{BASE_URL}/api/connector/web-proxy/response/{request_id}",
            headers=self.headers
        )
        assert response.status_code == 200, f"Failed to get response: {response.text}"
        data = response.json()
        assert data["status"] == "completed"
        assert data["response"]["body"] == html_body
        assert data["response"]["title"] == "Netgear GS108E"
        print(f"✓ Got completed web proxy response with HTML body")


class TestWebProxySecurity:
    """Test security restrictions for Web Console Proxy"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Get auth token for tests"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200
        self.admin_token = response.json()["token"]
        self.admin_headers = {"Authorization": f"Bearer {self.admin_token}"}
    
    def test_viewer_cannot_create_web_proxy_request(self):
        """Viewer role should NOT be able to create web proxy requests (403)"""
        # First create a viewer user
        viewer_email = f"TEST_viewer_{uuid.uuid4().hex[:8]}@test.com"
        create_response = requests.post(
            f"{BASE_URL}/api/admin/users",
            headers=self.admin_headers,
            json={
                "email": viewer_email,
                "password": "testpass123",
                "name": "Test Viewer",
                "role": "viewer"
            }
        )
        assert create_response.status_code == 200, f"Failed to create viewer: {create_response.text}"
        viewer_id = create_response.json()["id"]
        
        try:
            # Login as viewer
            login_response = requests.post(f"{BASE_URL}/api/auth/login", json={
                "email": viewer_email,
                "password": "testpass123"
            })
            assert login_response.status_code == 200
            viewer_token = login_response.json()["token"]
            viewer_headers = {"Authorization": f"Bearer {viewer_token}"}
            
            # Try to create web proxy request
            response = requests.post(
                f"{BASE_URL}/api/connector/web-proxy/request",
                headers=viewer_headers,
                json={
                    "client_id": CLIENT_ID,
                    "device_ip": "192.168.1.3",
                    "port": 80,
                    "path": "/",
                    "method": "GET"
                }
            )
            assert response.status_code == 403, f"Expected 403 for viewer, got {response.status_code}: {response.text}"
            print("✓ Viewer correctly denied access to web proxy (403)")
        finally:
            # Cleanup: delete test viewer
            requests.delete(f"{BASE_URL}/api/admin/users/{viewer_id}", headers=self.admin_headers)
    
    def test_operator_can_create_web_proxy_request(self):
        """Operator role should be able to create web proxy requests"""
        # First create an operator user
        operator_email = f"TEST_operator_{uuid.uuid4().hex[:8]}@test.com"
        create_response = requests.post(
            f"{BASE_URL}/api/admin/users",
            headers=self.admin_headers,
            json={
                "email": operator_email,
                "password": "testpass123",
                "name": "Test Operator",
                "role": "operator"
            }
        )
        assert create_response.status_code == 200, f"Failed to create operator: {create_response.text}"
        operator_id = create_response.json()["id"]
        
        try:
            # Login as operator
            login_response = requests.post(f"{BASE_URL}/api/auth/login", json={
                "email": operator_email,
                "password": "testpass123"
            })
            assert login_response.status_code == 200
            operator_token = login_response.json()["token"]
            operator_headers = {"Authorization": f"Bearer {operator_token}"}
            
            # Try to create web proxy request
            response = requests.post(
                f"{BASE_URL}/api/connector/web-proxy/request",
                headers=operator_headers,
                json={
                    "client_id": CLIENT_ID,
                    "device_ip": "192.168.1.3",
                    "port": 80,
                    "path": "/",
                    "method": "GET"
                }
            )
            assert response.status_code == 200, f"Operator should be able to create proxy request: {response.text}"
            print("✓ Operator correctly allowed to create web proxy request")
        finally:
            # Cleanup: delete test operator
            requests.delete(f"{BASE_URL}/api/admin/users/{operator_id}", headers=self.admin_headers)


class TestMonitorTypeSwitching:
    """Test monitor type switching endpoint"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Get auth token for tests"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200
        self.token = response.json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_change_monitor_type_to_ping(self):
        """PUT /api/connector/device-poll-status/{ip}/monitor-type - change to ping"""
        device_ip = "192.168.1.3"  # Netgear device
        
        response = requests.put(
            f"{BASE_URL}/api/connector/device-poll-status/{device_ip}/monitor-type",
            headers=self.headers,
            json={
                "monitor_type": "ping",
                "http_port": 80
            }
        )
        assert response.status_code == 200, f"Failed to change monitor type: {response.text}"
        data = response.json()
        assert data["status"] == "ok"
        print(f"✓ Changed {device_ip} monitor type to ping")
    
    def test_change_monitor_type_to_snmp(self):
        """PUT /api/connector/device-poll-status/{ip}/monitor-type - change to snmp"""
        device_ip = "192.168.1.3"
        
        response = requests.put(
            f"{BASE_URL}/api/connector/device-poll-status/{device_ip}/monitor-type",
            headers=self.headers,
            json={
                "monitor_type": "snmp",
                "http_port": 80
            }
        )
        assert response.status_code == 200, f"Failed to change monitor type: {response.text}"
        data = response.json()
        assert data["status"] == "ok"
        print(f"✓ Changed {device_ip} monitor type to snmp")
    
    def test_verify_monitor_type_persisted(self):
        """Verify monitor type change is persisted in device poll status"""
        device_ip = "192.168.1.3"
        
        # Change to ping
        requests.put(
            f"{BASE_URL}/api/connector/device-poll-status/{device_ip}/monitor-type",
            headers=self.headers,
            json={"monitor_type": "ping", "http_port": 80}
        )
        
        # Get device poll status
        response = requests.get(
            f"{BASE_URL}/api/connector/device-poll-status",
            headers=self.headers
        )
        assert response.status_code == 200
        devices = response.json()
        
        # Find our device
        device = next((d for d in devices if d.get("device_ip") == device_ip), None)
        if device:
            assert device.get("monitor_type") == "ping", f"Expected ping, got {device.get('monitor_type')}"
            print(f"✓ Monitor type 'ping' persisted for {device_ip}")
        else:
            print(f"⚠ Device {device_ip} not found in poll status (may not have been polled yet)")


class TestCleanup:
    """Cleanup test data"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Get auth token for tests"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200
        self.token = response.json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_cleanup_test_users(self):
        """Clean up any TEST_ prefixed users"""
        response = requests.get(f"{BASE_URL}/api/admin/users", headers=self.headers)
        if response.status_code == 200:
            users = response.json()
            for user in users:
                if user.get("email", "").startswith("TEST_"):
                    requests.delete(f"{BASE_URL}/api/admin/users/{user['id']}", headers=self.headers)
                    print(f"✓ Cleaned up test user: {user['email']}")
        print("✓ Cleanup completed")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
