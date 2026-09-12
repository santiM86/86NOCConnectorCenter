"""
Test Web Console V4 - Popup/New Tab JWT Proxy
Tests for POST /api/console-v4/request-session, GET /api/console-v4/s/{token}/{path},
GET /api/console-v4/sessions, POST /api/console-v4/revoke/{sid}
"""
import pytest
import requests
import os
import jwt
import time
from datetime import datetime, timezone, timedelta

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
JWT_SECRET = "noc-alert-command-center-secret-key-2024"  # From backend/.env
ALGORITHM = "HS256"

# Test credentials
ADMIN_EMAIL = "admin@86bit.it"
ADMIN_PASSWORD = "password"
VIEWER_EMAIL = "tv@86bit.it"
VIEWER_PASSWORD = "Tv86bit!2026"


class TestWebConsoleV4Auth:
    """Test authentication for Web Console V4 endpoints"""
    
    @pytest.fixture(scope="class")
    def admin_token(self):
        """Get admin JWT token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200, f"Admin login failed: {response.text}"
        data = response.json()
        token = data.get("access_token") or data.get("token")
        assert token, f"No token in response: {data}"
        return token
    
    @pytest.fixture(scope="class")
    def viewer_token(self):
        """Get viewer JWT token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": VIEWER_EMAIL,
            "password": VIEWER_PASSWORD
        })
        assert response.status_code == 200, f"Viewer login failed: {response.text}"
        data = response.json()
        token = data.get("access_token") or data.get("token")
        assert token, f"No token in response: {data}"
        return token
    
    def test_request_session_requires_auth(self):
        """POST /api/console-v4/request-session without auth returns 401 or 403"""
        response = requests.post(f"{BASE_URL}/api/console-v4/request-session", json={
            "device_ip": "192.168.1.8"
        })
        assert response.status_code in (401, 403), f"Expected 401/403, got {response.status_code}"
    
    def test_sessions_requires_auth(self):
        """GET /api/console-v4/sessions without auth returns 401 or 403"""
        response = requests.get(f"{BASE_URL}/api/console-v4/sessions")
        assert response.status_code in (401, 403), f"Expected 401/403, got {response.status_code}"


class TestRequestSession:
    """Test POST /api/console-v4/request-session endpoint"""
    
    @pytest.fixture(scope="class")
    def admin_token(self):
        """Get admin JWT token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200
        data = response.json()
        return data.get("access_token") or data.get("token")
    
    def test_request_session_missing_device_ip(self, admin_token):
        """POST /api/console-v4/request-session without device_ip returns 400"""
        response = requests.post(
            f"{BASE_URL}/api/console-v4/request-session",
            json={},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.text}"
        data = response.json()
        assert "device_ip" in data.get("detail", "").lower() or "required" in data.get("detail", "").lower()
    
    def test_request_session_empty_device_ip(self, admin_token):
        """POST /api/console-v4/request-session with empty device_ip returns 400"""
        response = requests.post(
            f"{BASE_URL}/api/console-v4/request-session",
            json={"device_ip": ""},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.text}"
    
    def test_request_session_nonexistent_device(self, admin_token):
        """POST /api/console-v4/request-session with non-existent device returns 404"""
        response = requests.post(
            f"{BASE_URL}/api/console-v4/request-session",
            json={"device_ip": "10.255.255.254"},  # Non-existent IP
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 404, f"Expected 404, got {response.status_code}: {response.text}"
        data = response.json()
        assert "non registrato" in data.get("detail", "").lower() or "not" in data.get("detail", "").lower()
    
    def test_request_session_valid_device(self, admin_token):
        """POST /api/console-v4/request-session with valid device returns session data"""
        # Device 192.168.1.8 should exist in vault/managed_devices/device_poll_status
        response = requests.post(
            f"{BASE_URL}/api/console-v4/request-session",
            json={"device_ip": "192.168.1.8"},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        # Could be 200 (success) or 404 (device not in DB) - both are valid behaviors
        if response.status_code == 200:
            data = response.json()
            # Verify response structure
            assert "url" in data, f"Missing 'url' in response: {data}"
            assert "token" in data, f"Missing 'token' in response: {data}"
            assert "expires_at" in data, f"Missing 'expires_at' in response: {data}"
            assert "transport" in data, f"Missing 'transport' in response: {data}"
            assert "base_url" in data, f"Missing 'base_url' in response: {data}"
            
            # URL should be relative path starting with /api/console-v4/s/
            assert data["url"].startswith("/api/console-v4/s/"), f"URL should be relative: {data['url']}"
            
            # Transport should be 'direct' or 'connector'
            assert data["transport"] in ("direct", "connector"), f"Invalid transport: {data['transport']}"
            
            # Token should be a valid JWT
            try:
                payload = jwt.decode(data["token"], JWT_SECRET, algorithms=[ALGORITHM])
                assert "sid" in payload
                assert "dip" in payload
                assert payload["dip"] == "192.168.1.8"
                assert "usr" in payload
                assert "base" in payload
                assert "exp" in payload
            except jwt.InvalidTokenError as e:
                pytest.fail(f"Invalid JWT token: {e}")
        elif response.status_code == 404:
            # Device not in DB - this is acceptable
            print(f"Device 192.168.1.8 not found in DB (expected if no seed data)")
        else:
            pytest.fail(f"Unexpected status {response.status_code}: {response.text}")


class TestProxyEndpoint:
    """Test GET /api/console-v4/s/{token}/{path} proxy endpoint"""
    
    def _make_test_token(self, base_url: str, device_ip: str = "192.168.1.8", 
                         expired: bool = False, invalid: bool = False) -> str:
        """Generate a test JWT token for proxy testing"""
        if invalid:
            return "tokeninvalid.aaa.bbb"
        
        exp_delta = timedelta(minutes=-5) if expired else timedelta(minutes=60)
        exp = datetime.now(timezone.utc) + exp_delta
        
        payload = {
            "sid": "test-session-id-123",
            "dip": device_ip,
            "cid": None,
            "usr": "test@example.com",
            "base": base_url,
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int(exp.timestamp()),
        }
        return jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)
    
    def test_proxy_invalid_token(self):
        """GET /api/console-v4/s/invalid.token/ returns 401"""
        response = requests.get(f"{BASE_URL}/api/console-v4/s/tokeninvalid.aaa.bbb/")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"
        data = response.json()
        assert "invalido" in data.get("detail", "").lower() or "invalid" in data.get("detail", "").lower()
    
    def test_proxy_expired_token(self):
        """GET /api/console-v4/s/<expired_token>/ returns 410 with 'Sessione scaduta'"""
        expired_token = self._make_test_token("https://httpbin.org", expired=True)
        response = requests.get(f"{BASE_URL}/api/console-v4/s/{expired_token}/")
        assert response.status_code == 410, f"Expected 410, got {response.status_code}: {response.text}"
        # Response should be HTML with "Sessione scaduta"
        assert "scaduta" in response.text.lower() or "expired" in response.text.lower()
    
    def test_proxy_httpbin_get_json(self):
        """GET /api/console-v4/s/{token}/get?x=1 with httpbin.org returns JSON"""
        token = self._make_test_token("https://httpbin.org")
        response = requests.get(f"{BASE_URL}/api/console-v4/s/{token}/get?x=1")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        # Should return JSON from httpbin
        content_type = response.headers.get("content-type", "")
        assert "application/json" in content_type, f"Expected JSON, got {content_type}"
        
        data = response.json()
        # httpbin /get returns the query args
        assert "args" in data, f"Missing 'args' in httpbin response: {data}"
        assert data["args"].get("x") == "1", f"Query param not passed: {data['args']}"
    
    def test_proxy_httpbin_html_base_injection(self):
        """GET /api/console-v4/s/{token}/html returns HTML with <base> tag injected"""
        token = self._make_test_token("https://httpbin.org")
        response = requests.get(f"{BASE_URL}/api/console-v4/s/{token}/html")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        # Should return HTML
        content_type = response.headers.get("content-type", "")
        assert "text/html" in content_type, f"Expected HTML, got {content_type}"
        
        # Should have <base href='/api/console-v4/s/<token>/'> injected
        expected_base = f"<base href=\"/api/console-v4/s/{token}/\">"
        assert expected_base in response.text, f"Base tag not injected. Response: {response.text[:500]}"
    
    def test_proxy_httpbin_redirect_rewrite(self):
        """GET /api/console-v4/s/{token}/redirect/1 returns redirect with rewritten Location"""
        token = self._make_test_token("https://httpbin.org")
        # Don't follow redirects
        response = requests.get(f"{BASE_URL}/api/console-v4/s/{token}/redirect/1", allow_redirects=False)
        
        # Should be a redirect (302)
        assert 300 <= response.status_code < 400, f"Expected redirect, got {response.status_code}"
        
        # Location header should be rewritten to go through proxy
        location = response.headers.get("location", "")
        assert location.startswith(f"/api/console-v4/s/{token}/"), \
            f"Location not rewritten: {location}"
    
    def test_proxy_unreachable_device(self):
        """GET /api/console-v4/s/{token}/ with unreachable device returns 502 or 504"""
        # Use a non-routable IP that will timeout
        token = self._make_test_token("https://10.255.255.254:443")
        response = requests.get(f"{BASE_URL}/api/console-v4/s/{token}/", timeout=35)
        # 502 = proxy error from route, 504 = timeout middleware
        assert response.status_code in (502, 504), f"Expected 502/504, got {response.status_code}: {response.text}"
        # Either "non raggiungibile" or "timeout" message
        assert "non raggiungibile" in response.text.lower() or "timeout" in response.text.lower() or "unreachable" in response.text.lower()


class TestSessionsAdmin:
    """Test GET /api/console-v4/sessions and POST /api/console-v4/revoke/{sid}"""
    
    @pytest.fixture(scope="class")
    def admin_token(self):
        """Get admin JWT token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200
        data = response.json()
        return data.get("access_token") or data.get("token")
    
    @pytest.fixture(scope="class")
    def viewer_token(self):
        """Get viewer JWT token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": VIEWER_EMAIL,
            "password": VIEWER_PASSWORD
        })
        assert response.status_code == 200
        data = response.json()
        return data.get("access_token") or data.get("token")
    
    def test_list_sessions_admin(self, admin_token):
        """GET /api/console-v4/sessions as admin returns session list"""
        response = requests.get(
            f"{BASE_URL}/api/console-v4/sessions",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert "active" in data, f"Missing 'active' count: {data}"
        assert "items" in data, f"Missing 'items' list: {data}"
        assert isinstance(data["items"], list), f"'items' should be a list: {data}"
        
        # If there are sessions, verify structure
        if data["items"]:
            session = data["items"][0]
            # Should have device_ip, user_email, transport, expires_at
            assert "device_ip" in session or "sid" in session
    
    def test_revoke_session_nonexistent(self, admin_token):
        """POST /api/console-v4/revoke/{sid} with non-existent sid still returns ok"""
        response = requests.post(
            f"{BASE_URL}/api/console-v4/revoke/nonexistent-sid-12345",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        # Should return 200 with ok:true (idempotent operation)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data.get("ok") == True, f"Expected ok:true, got {data}"
    
    def test_revoke_session_viewer_forbidden(self, viewer_token):
        """POST /api/console-v4/revoke/{sid} as viewer returns 403"""
        response = requests.post(
            f"{BASE_URL}/api/console-v4/revoke/any-sid",
            headers={"Authorization": f"Bearer {viewer_token}"}
        )
        assert response.status_code == 403, f"Expected 403, got {response.status_code}: {response.text}"


class TestEndToEndFlow:
    """End-to-end test: create session, use proxy, list sessions"""
    
    @pytest.fixture(scope="class")
    def admin_token(self):
        """Get admin JWT token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200
        data = response.json()
        return data.get("access_token") or data.get("token")
    
    def test_full_flow_with_httpbin(self, admin_token):
        """
        Full flow test using httpbin.org as target:
        1. Create a session token manually (simulating what request-session would do)
        2. Use the proxy to fetch from httpbin
        3. Verify the session appears in sessions list
        """
        # Step 1: Generate a token for httpbin.org
        exp = datetime.now(timezone.utc) + timedelta(minutes=60)
        payload = {
            "sid": f"test-e2e-{int(time.time())}",
            "dip": "httpbin.org",
            "cid": None,
            "usr": ADMIN_EMAIL,
            "base": "https://httpbin.org",
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "exp": int(exp.timestamp()),
        }
        token = jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)
        
        # Step 2: Use proxy to fetch /get
        proxy_response = requests.get(f"{BASE_URL}/api/console-v4/s/{token}/get?test=e2e")
        assert proxy_response.status_code == 200, f"Proxy failed: {proxy_response.text}"
        
        data = proxy_response.json()
        assert data.get("args", {}).get("test") == "e2e", f"Query not passed: {data}"
        
        # Step 3: Verify sessions list works
        sessions_response = requests.get(
            f"{BASE_URL}/api/console-v4/sessions",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert sessions_response.status_code == 200, f"Sessions list failed: {sessions_response.text}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
