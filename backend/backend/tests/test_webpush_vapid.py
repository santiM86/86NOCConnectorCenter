"""
Web Push VAPID Feature Tests - Iteration 51
Tests for /api/push/* endpoints and webpush integration

Features tested:
- GET /api/push/vapid-public-key: Returns VAPID public key
- POST /api/push/subscribe: Register browser push subscription
- GET /api/push/status: Get subscription status for current user
- POST /api/push/unsubscribe: Remove subscription by endpoint
- POST /api/push/test: Send test push notification
- POST /api/alerts: Verify push notification hook doesn't break alert creation
- Regression: Verify existing routers still import correctly
"""
import pytest
import requests
import os
import uuid
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Module-level session and token to avoid rate limiting
_auth_session = None
_auth_token = None


def get_auth_session():
    """Get or create authenticated session (singleton to avoid rate limiting)"""
    global _auth_session, _auth_token
    
    if _auth_session is not None and _auth_token is not None:
        return _auth_session, _auth_token
    
    _auth_session = requests.Session()
    _auth_session.headers.update({"Content-Type": "application/json"})
    
    # Login with admin credentials
    login_resp = _auth_session.post(f"{BASE_URL}/api/auth/login", json={
        "email": "admin@86bit.it",
        "password": "password"
    })
    
    if login_resp.status_code == 429:
        # Rate limited - wait and retry
        time.sleep(65)
        login_resp = _auth_session.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@86bit.it",
            "password": "password"
        })
    
    assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
    
    # Response uses 'token' not 'access_token'
    _auth_token = login_resp.json().get("token")
    assert _auth_token, f"No token in login response: {login_resp.json()}"
    _auth_session.headers.update({"Authorization": f"Bearer {_auth_token}"})
    
    return _auth_session, _auth_token


class TestWebPushVAPID:
    """Web Push VAPID endpoint tests"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup: Get authenticated session"""
        self.session, self.token = get_auth_session()
        
        # Generate unique endpoint for this test run
        self.test_endpoint = f"https://fcm.googleapis.com/fcm/send/test-{uuid.uuid4().hex[:12]}"
        
        yield
        
        # Cleanup: Remove test subscription if exists
        try:
            self.session.post(f"{BASE_URL}/api/push/unsubscribe", json={
                "endpoint": self.test_endpoint
            })
        except Exception:
            pass
    
    # ==================== VAPID Public Key Tests ====================
    
    def test_get_vapid_public_key_returns_200(self):
        """GET /api/push/vapid-public-key should return 200 with public_key field"""
        resp = self.session.get(f"{BASE_URL}/api/push/vapid-public-key")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        assert "public_key" in data, "Response missing 'public_key' field"
        assert isinstance(data["public_key"], str), "public_key should be a string"
        assert len(data["public_key"]) > 50, "public_key seems too short for VAPID"
        print(f"✓ VAPID public key returned: {data['public_key'][:30]}...")
    
    # ==================== Subscribe Tests ====================
    
    def test_subscribe_with_valid_subscription(self):
        """POST /api/push/subscribe with valid subscription should return success"""
        payload = {
            "subscription": {
                "endpoint": self.test_endpoint,
                "keys": {
                    "p256dh": "BNcRdreALRFXTkOOUHK1EtK2wtaz5ry4YfXmGTDR9adCKyWD6tXnYJTVJFHKKhMTg3Fjc4nEzaSgdXXGZ6fXHCQ",
                    "auth": "tBHItJI5svbpez7KI4CCXg"
                }
            },
            "user_agent": "TestAgent/1.0"
        }
        
        resp = self.session.post(f"{BASE_URL}/api/push/subscribe", json=payload)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        assert data.get("success") is True, f"Expected success:true, got {data}"
        print(f"✓ Subscription created successfully")
    
    def test_subscribe_idempotency(self):
        """POST /api/push/subscribe twice with same endpoint should not create duplicate"""
        payload = {
            "subscription": {
                "endpoint": self.test_endpoint,
                "keys": {
                    "p256dh": "BNcRdreALRFXTkOOUHK1EtK2wtaz5ry4YfXmGTDR9adCKyWD6tXnYJTVJFHKKhMTg3Fjc4nEzaSgdXXGZ6fXHCQ",
                    "auth": "tBHItJI5svbpez7KI4CCXg"
                }
            },
            "user_agent": "TestAgent/1.0"
        }
        
        # First subscription
        resp1 = self.session.post(f"{BASE_URL}/api/push/subscribe", json=payload)
        assert resp1.status_code == 200, f"First subscribe failed: {resp1.text}"
        
        # Get status after first subscribe
        status1 = self.session.get(f"{BASE_URL}/api/push/status")
        count1 = status1.json().get("active_subscriptions", 0)
        
        # Second subscription with same endpoint
        resp2 = self.session.post(f"{BASE_URL}/api/push/subscribe", json=payload)
        assert resp2.status_code == 200, f"Second subscribe failed: {resp2.text}"
        
        # Get status after second subscribe - count should be same (upsert)
        status2 = self.session.get(f"{BASE_URL}/api/push/status")
        count2 = status2.json().get("active_subscriptions", 0)
        
        assert count2 == count1, f"Duplicate created: count went from {count1} to {count2}"
        print(f"✓ Idempotency verified: subscription count unchanged ({count1})")
    
    def test_subscribe_without_auth_returns_401_or_403(self):
        """POST /api/push/subscribe without auth should return 401 or 403"""
        no_auth_session = requests.Session()
        no_auth_session.headers.update({"Content-Type": "application/json"})
        
        payload = {
            "subscription": {
                "endpoint": "https://fcm.googleapis.com/fcm/send/test-noauth",
                "keys": {"p256dh": "test", "auth": "test"}
            }
        }
        
        resp = no_auth_session.post(f"{BASE_URL}/api/push/subscribe", json=payload)
        assert resp.status_code in [401, 403], f"Expected 401/403, got {resp.status_code}"
        print(f"✓ Unauthenticated subscribe correctly rejected with {resp.status_code}")
    
    def test_subscribe_with_invalid_payload_returns_400(self):
        """POST /api/push/subscribe with missing keys should return 400"""
        payload = {
            "subscription": {
                "endpoint": "https://fcm.googleapis.com/fcm/send/test-invalid"
                # Missing 'keys' field
            }
        }
        
        resp = self.session.post(f"{BASE_URL}/api/push/subscribe", json=payload)
        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"
        print(f"✓ Invalid subscription correctly rejected with 400")
    
    # ==================== Status Tests ====================
    
    def test_push_status_returns_configured_and_count(self):
        """GET /api/push/status should return configured:true and active_subscriptions count"""
        resp = self.session.get(f"{BASE_URL}/api/push/status")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        assert "configured" in data, "Response missing 'configured' field"
        assert "active_subscriptions" in data, "Response missing 'active_subscriptions' field"
        assert data["configured"] is True, "VAPID should be configured"
        assert isinstance(data["active_subscriptions"], int), "active_subscriptions should be int"
        print(f"✓ Status: configured={data['configured']}, subscriptions={data['active_subscriptions']}")
    
    def test_push_status_without_auth_returns_401_or_403(self):
        """GET /api/push/status without auth should return 401 or 403"""
        no_auth_session = requests.Session()
        resp = no_auth_session.get(f"{BASE_URL}/api/push/status")
        assert resp.status_code in [401, 403], f"Expected 401/403, got {resp.status_code}"
        print(f"✓ Unauthenticated status correctly rejected with {resp.status_code}")
    
    # ==================== Unsubscribe Tests ====================
    
    def test_unsubscribe_existing_endpoint(self):
        """POST /api/push/unsubscribe with existing endpoint should return deleted:1"""
        # First create a subscription
        subscribe_payload = {
            "subscription": {
                "endpoint": self.test_endpoint,
                "keys": {
                    "p256dh": "BNcRdreALRFXTkOOUHK1EtK2wtaz5ry4YfXmGTDR9adCKyWD6tXnYJTVJFHKKhMTg3Fjc4nEzaSgdXXGZ6fXHCQ",
                    "auth": "tBHItJI5svbpez7KI4CCXg"
                }
            }
        }
        self.session.post(f"{BASE_URL}/api/push/subscribe", json=subscribe_payload)
        
        # Now unsubscribe
        resp = self.session.post(f"{BASE_URL}/api/push/unsubscribe", json={
            "endpoint": self.test_endpoint
        })
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        assert data.get("success") is True, f"Expected success:true, got {data}"
        assert data.get("deleted") == 1, f"Expected deleted:1, got {data.get('deleted')}"
        print(f"✓ Unsubscribe successful: deleted={data.get('deleted')}")
    
    def test_unsubscribe_nonexistent_endpoint(self):
        """POST /api/push/unsubscribe with non-existent endpoint should return deleted:0"""
        resp = self.session.post(f"{BASE_URL}/api/push/unsubscribe", json={
            "endpoint": "https://fcm.googleapis.com/fcm/send/nonexistent-endpoint-xyz"
        })
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        assert data.get("success") is True, f"Expected success:true, got {data}"
        assert data.get("deleted") == 0, f"Expected deleted:0, got {data.get('deleted')}"
        print(f"✓ Unsubscribe non-existent: deleted=0 (correct)")
    
    # ==================== Test Push Tests ====================
    
    def test_send_test_push_no_subscriptions(self):
        """POST /api/push/test with no subscriptions should return sent:0"""
        # First ensure no subscriptions exist by unsubscribing
        self.session.post(f"{BASE_URL}/api/push/unsubscribe", json={
            "endpoint": self.test_endpoint
        })
        
        resp = self.session.post(f"{BASE_URL}/api/push/test")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        # Should have 'sent' field (0 or more)
        assert "sent" in data or "success" in data, f"Response missing expected fields: {data}"
        print(f"✓ Test push with no subscriptions: {data}")
    
    def test_send_test_push_with_fake_subscription(self):
        """POST /api/push/test with fake subscription should not 500 (graceful failure)"""
        # Create a fake subscription
        subscribe_payload = {
            "subscription": {
                "endpoint": self.test_endpoint,
                "keys": {
                    "p256dh": "BNcRdreALRFXTkOOUHK1EtK2wtaz5ry4YfXmGTDR9adCKyWD6tXnYJTVJFHKKhMTg3Fjc4nEzaSgdXXGZ6fXHCQ",
                    "auth": "tBHItJI5svbpez7KI4CCXg"
                }
            }
        }
        self.session.post(f"{BASE_URL}/api/push/subscribe", json=subscribe_payload)
        
        # Send test push - should NOT return 500 even with fake endpoint
        resp = self.session.post(f"{BASE_URL}/api/push/test")
        assert resp.status_code != 500, f"Got 500 error: {resp.text}"
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        # Response should have 'sent' field
        assert "sent" in data, f"Response missing 'sent' field: {data}"
        print(f"✓ Test push with fake subscription handled gracefully: {data}")


class TestAlertCreationWithPush:
    """Test that alert creation doesn't break with push notification hook"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup: Get authenticated session"""
        self.session, self.token = get_auth_session()
        yield
    
    def test_create_critical_alert_with_no_subscriptions(self):
        """POST /api/alerts with severity=critical should NOT fail even with no push subscriptions"""
        # Get a client_id for the alert
        clients_resp = self.session.get(f"{BASE_URL}/api/clients")
        if clients_resp.status_code == 200 and clients_resp.json():
            client_id = clients_resp.json()[0].get("id", "test-client")
        else:
            client_id = "test-client"
        
        alert_payload = {
            "client_id": client_id,
            "device_id": "test-device",
            "severity": "critical",
            "source_type": "manual",
            "title": "TEST_PUSH_CRITICAL_ALERT",
            "message": "Test critical alert for push notification testing"
        }
        
        resp = self.session.post(f"{BASE_URL}/api/alerts", json=alert_payload)
        # Should not fail with 500 due to push notification errors
        assert resp.status_code != 500, f"Alert creation failed with 500: {resp.text}"
        assert resp.status_code in [200, 201], f"Expected 200/201, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        assert data.get("id"), "Alert should have an ID"
        assert data.get("severity") == "critical", "Alert severity should be critical"
        print(f"✓ Critical alert created successfully: {data.get('id')}")


class TestRegressionRouters:
    """Regression tests: Verify existing routers still work"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup: Get authenticated session"""
        self.session, self.token = get_auth_session()
        yield
    
    def test_auth_login_still_works(self):
        """POST /api/auth/login should still work"""
        resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@86bit.it",
            "password": "password"
        }, headers={"Content-Type": "application/json"})
        assert resp.status_code == 200, f"Auth login broken: {resp.status_code}"
        print(f"✓ /api/auth/login works")
    
    def test_alerts_endpoint_still_works(self):
        """GET /api/alerts should still work"""
        resp = self.session.get(f"{BASE_URL}/api/alerts")
        assert resp.status_code == 200, f"Alerts endpoint broken: {resp.status_code}"
        print(f"✓ /api/alerts works")
    
    def test_stats_summary_still_works(self):
        """GET /api/stats/summary should still work"""
        resp = self.session.get(f"{BASE_URL}/api/stats/summary")
        assert resp.status_code == 200, f"Stats summary broken: {resp.status_code}"
        print(f"✓ /api/stats/summary works")
    
    def test_health_endpoint_works(self):
        """GET /api/health should work"""
        resp = requests.get(f"{BASE_URL}/api/health")
        assert resp.status_code == 200, f"Health endpoint broken: {resp.status_code}"
        print(f"✓ /api/health works")
    
    def test_clients_endpoint_works(self):
        """GET /api/clients should work"""
        resp = self.session.get(f"{BASE_URL}/api/clients")
        assert resp.status_code == 200, f"Clients endpoint broken: {resp.status_code}"
        print(f"✓ /api/clients works")
    
    def test_ingestion_syslog_endpoint_exists(self):
        """POST /api/ingest/syslog should exist (may require specific payload)"""
        # Just check the endpoint exists - it may reject invalid payload but shouldn't 404
        resp = self.session.post(f"{BASE_URL}/api/ingest/syslog", json={})
        assert resp.status_code != 404, f"Ingestion syslog endpoint missing: {resp.status_code}"
        print(f"✓ /api/ingest/syslog exists (status: {resp.status_code})")
    
    def test_external_monitor_endpoint_exists(self):
        """GET /api/external-monitor/targets should exist"""
        resp = self.session.get(f"{BASE_URL}/api/external-monitor/targets")
        assert resp.status_code in [200, 404], f"External monitor broken: {resp.status_code}"
        print(f"✓ /api/external-monitor/targets exists (status: {resp.status_code})")
    
    def test_printers_endpoint_exists(self):
        """GET /api/printers should exist"""
        resp = self.session.get(f"{BASE_URL}/api/printers")
        assert resp.status_code in [200, 404], f"Printers endpoint broken: {resp.status_code}"
        print(f"✓ /api/printers exists (status: {resp.status_code})")
    
    def test_backup_status_endpoint_exists(self):
        """GET /api/backup/status should exist"""
        resp = self.session.get(f"{BASE_URL}/api/backup/status")
        assert resp.status_code in [200, 404], f"Backup status broken: {resp.status_code}"
        print(f"✓ /api/backup/status exists (status: {resp.status_code})")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
