"""
Test IP Auto-Ban System
Tests for IP blocking, unblocking, configuration, whitelist, and middleware
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
ADMIN_EMAIL = "admin@86bit.it"
ADMIN_PASSWORD = "admin123"
OPERATOR_EMAIL = "operator@test.com"
OPERATOR_PASSWORD = "operator123"


class TestIPBlockingSystem:
    """Tests for IP Auto-Ban System endpoints"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup: Get admin token for authenticated requests"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login as admin
        login_resp = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert login_resp.status_code == 200, f"Admin login failed: {login_resp.text}"
        self.admin_token = login_resp.json()["token"]
        self.session.headers.update({"Authorization": f"Bearer {self.admin_token}"})
        
        yield
        
        # Cleanup: Unblock any test IPs
        try:
            self.session.post(f"{BASE_URL}/api/security/unblock-ip", json={"ip": "192.168.99.99"})
            self.session.post(f"{BASE_URL}/api/security/unblock-ip", json={"ip": "10.0.0.99"})
            self.session.post(f"{BASE_URL}/api/security/unblock-ip", json={"ip": "172.16.0.99"})
        except:
            pass
    
    # ==================== GET /api/security/blocked-ips ====================
    
    def test_get_blocked_ips_returns_active_and_history(self):
        """GET /api/security/blocked-ips returns active and history arrays"""
        resp = self.session.get(f"{BASE_URL}/api/security/blocked-ips")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        assert "active" in data, "Response should contain 'active' array"
        assert "history" in data, "Response should contain 'history' array"
        assert isinstance(data["active"], list), "'active' should be a list"
        assert isinstance(data["history"], list), "'history' should be a list"
        print(f"✓ GET /api/security/blocked-ips returns active ({len(data['active'])}) and history ({len(data['history'])})")
    
    # ==================== POST /api/security/block-ip ====================
    
    def test_block_ip_success(self):
        """POST /api/security/block-ip blocks an IP and returns ok"""
        test_ip = "192.168.99.99"
        resp = self.session.post(f"{BASE_URL}/api/security/block-ip", json={
            "ip": test_ip,
            "reason": "Test block",
            "duration_hours": 1
        })
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        assert data.get("status") == "ok", f"Expected status 'ok', got {data}"
        print(f"✓ POST /api/security/block-ip blocks IP {test_ip} successfully")
        
        # Verify IP is in blocked list
        blocked_resp = self.session.get(f"{BASE_URL}/api/security/blocked-ips")
        blocked_data = blocked_resp.json()
        blocked_ips = [b["ip"] for b in blocked_data["active"]]
        assert test_ip in blocked_ips, f"IP {test_ip} should be in blocked list"
        print(f"✓ IP {test_ip} verified in blocked list")
    
    def test_block_ip_permanent(self):
        """POST /api/security/block-ip can block IP permanently"""
        test_ip = "10.0.0.99"
        resp = self.session.post(f"{BASE_URL}/api/security/block-ip", json={
            "ip": test_ip,
            "reason": "Permanent test block",
            "permanent": True
        })
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        # Verify permanent flag
        blocked_resp = self.session.get(f"{BASE_URL}/api/security/blocked-ips")
        blocked_data = blocked_resp.json()
        blocked_entry = next((b for b in blocked_data["active"] if b["ip"] == test_ip), None)
        assert blocked_entry is not None, f"IP {test_ip} should be in blocked list"
        assert blocked_entry.get("permanent") == True, "IP should be marked as permanent"
        print(f"✓ IP {test_ip} blocked permanently")
    
    def test_block_ip_requires_ip(self):
        """POST /api/security/block-ip requires IP address"""
        resp = self.session.post(f"{BASE_URL}/api/security/block-ip", json={
            "reason": "No IP provided"
        })
        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"
        print("✓ POST /api/security/block-ip returns 400 when IP is missing")
    
    # ==================== POST /api/security/unblock-ip ====================
    
    def test_unblock_ip_success(self):
        """POST /api/security/unblock-ip unblocks an IP and returns ok"""
        test_ip = "172.16.0.99"
        
        # First block the IP
        self.session.post(f"{BASE_URL}/api/security/block-ip", json={
            "ip": test_ip,
            "reason": "Test for unblock"
        })
        
        # Now unblock
        resp = self.session.post(f"{BASE_URL}/api/security/unblock-ip", json={
            "ip": test_ip
        })
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        assert data.get("status") == "ok", f"Expected status 'ok', got {data}"
        print(f"✓ POST /api/security/unblock-ip unblocks IP {test_ip} successfully")
        
        # Verify IP is no longer in active blocked list
        blocked_resp = self.session.get(f"{BASE_URL}/api/security/blocked-ips")
        blocked_data = blocked_resp.json()
        active_ips = [b["ip"] for b in blocked_data["active"]]
        assert test_ip not in active_ips, f"IP {test_ip} should not be in active blocked list"
        print(f"✓ IP {test_ip} verified removed from active blocked list")
    
    def test_unblock_ip_requires_ip(self):
        """POST /api/security/unblock-ip requires IP address"""
        resp = self.session.post(f"{BASE_URL}/api/security/unblock-ip", json={})
        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"
        print("✓ POST /api/security/unblock-ip returns 400 when IP is missing")
    
    # ==================== GET /api/security/ip-block-config ====================
    
    def test_get_ip_block_config_returns_defaults(self):
        """GET /api/security/ip-block-config returns default config with whitelist"""
        resp = self.session.get(f"{BASE_URL}/api/security/ip-block-config")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        # Check required fields
        assert "enabled" in data, "Config should have 'enabled' field"
        assert "max_attempts" in data, "Config should have 'max_attempts' field"
        assert "window_minutes" in data, "Config should have 'window_minutes' field"
        assert "block_duration_hours" in data, "Config should have 'block_duration_hours' field"
        assert "auto_ban_enabled" in data, "Config should have 'auto_ban_enabled' field"
        assert "whitelist" in data, "Config should have 'whitelist' field"
        
        # Check types
        assert isinstance(data["whitelist"], list), "'whitelist' should be a list"
        assert isinstance(data["max_attempts"], int), "'max_attempts' should be int"
        assert isinstance(data["window_minutes"], int), "'window_minutes' should be int"
        
        print(f"✓ GET /api/security/ip-block-config returns config: enabled={data['enabled']}, max_attempts={data['max_attempts']}, window={data['window_minutes']}min, duration={data['block_duration_hours']}h")
        print(f"  Whitelist: {data['whitelist']}")
    
    # ==================== POST /api/security/ip-block-config ====================
    
    def test_save_ip_block_config(self):
        """POST /api/security/ip-block-config saves new config"""
        # Get current config first
        current_resp = self.session.get(f"{BASE_URL}/api/security/ip-block-config")
        current_config = current_resp.json()
        
        # Update config
        new_config = {
            "enabled": True,
            "max_attempts": 15,
            "window_minutes": 45,
            "block_duration_hours": 12,
            "auto_ban_enabled": True,
            "whitelist": current_config.get("whitelist", [])  # Keep existing whitelist
        }
        
        resp = self.session.post(f"{BASE_URL}/api/security/ip-block-config", json=new_config)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        assert data.get("status") == "ok", f"Expected status 'ok', got {data}"
        print("✓ POST /api/security/ip-block-config saves config successfully")
        
        # Verify config was saved
        verify_resp = self.session.get(f"{BASE_URL}/api/security/ip-block-config")
        verify_data = verify_resp.json()
        assert verify_data["max_attempts"] == 15, f"max_attempts should be 15, got {verify_data['max_attempts']}"
        assert verify_data["window_minutes"] == 45, f"window_minutes should be 45, got {verify_data['window_minutes']}"
        print("✓ Config changes verified")
        
        # Restore original config
        restore_config = {
            "enabled": True,
            "max_attempts": 10,
            "window_minutes": 30,
            "block_duration_hours": 6,
            "auto_ban_enabled": True,
            "whitelist": current_config.get("whitelist", [])
        }
        self.session.post(f"{BASE_URL}/api/security/ip-block-config", json=restore_config)
        print("✓ Original config restored")
    
    # ==================== Whitelist Protection ====================
    
    def test_whitelisted_ip_cannot_be_blocked(self):
        """Whitelisted IP cannot be blocked (returns 400)"""
        # Get current whitelist
        config_resp = self.session.get(f"{BASE_URL}/api/security/ip-block-config")
        config = config_resp.json()
        current_whitelist = config.get("whitelist", [])
        
        # Add test IP to whitelist
        test_ip = "192.168.88.88"
        new_whitelist = list(set(current_whitelist + [test_ip]))
        
        self.session.post(f"{BASE_URL}/api/security/ip-block-config", json={
            **config,
            "whitelist": new_whitelist
        })
        
        # Try to block whitelisted IP
        resp = self.session.post(f"{BASE_URL}/api/security/block-ip", json={
            "ip": test_ip,
            "reason": "Should fail - whitelisted"
        })
        assert resp.status_code == 400, f"Expected 400 for whitelisted IP, got {resp.status_code}: {resp.text}"
        assert "whitelist" in resp.text.lower(), f"Error should mention whitelist: {resp.text}"
        print(f"✓ Whitelisted IP {test_ip} cannot be blocked (400 returned)")
        
        # Restore original whitelist
        self.session.post(f"{BASE_URL}/api/security/ip-block-config", json={
            **config,
            "whitelist": current_whitelist
        })
    
    # ==================== Security Dashboard blocked_ips stat ====================
    
    def test_security_dashboard_includes_blocked_ips_stat(self):
        """Security dashboard now includes blocked_ips stat"""
        resp = self.session.get(f"{BASE_URL}/api/audit/security-dashboard")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        assert "stats" in data, "Response should have 'stats'"
        assert "blocked_ips" in data["stats"], "Stats should include 'blocked_ips'"
        assert isinstance(data["stats"]["blocked_ips"], int), "'blocked_ips' should be an integer"
        print(f"✓ Security dashboard includes blocked_ips stat: {data['stats']['blocked_ips']}")


class TestIPBlockingNonAdmin:
    """Tests for non-admin access to IP blocking endpoints"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup: Get operator token"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # First ensure operator user exists
        admin_session = requests.Session()
        admin_session.headers.update({"Content-Type": "application/json"})
        
        login_resp = admin_session.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        if login_resp.status_code == 200:
            admin_token = login_resp.json()["token"]
            admin_session.headers.update({"Authorization": f"Bearer {admin_token}"})
            
            # Try to create operator user (may already exist)
            admin_session.post(f"{BASE_URL}/api/admin/users", json={
                "email": OPERATOR_EMAIL,
                "password": OPERATOR_PASSWORD,
                "name": "Test Operator",
                "role": "operator"
            })
        
        # Login as operator
        login_resp = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": OPERATOR_EMAIL,
            "password": OPERATOR_PASSWORD
        })
        
        if login_resp.status_code == 200:
            self.operator_token = login_resp.json()["token"]
            self.session.headers.update({"Authorization": f"Bearer {self.operator_token}"})
            self.has_operator = True
        else:
            self.has_operator = False
            print(f"Warning: Could not login as operator: {login_resp.text}")
    
    def test_non_admin_gets_403_on_blocked_ips(self):
        """Non-admin user gets 403 on GET /api/security/blocked-ips"""
        if not self.has_operator:
            pytest.skip("Operator user not available")
        
        resp = self.session.get(f"{BASE_URL}/api/security/blocked-ips")
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
        print("✓ Non-admin gets 403 on GET /api/security/blocked-ips")
    
    def test_non_admin_gets_403_on_block_ip(self):
        """Non-admin user gets 403 on POST /api/security/block-ip"""
        if not self.has_operator:
            pytest.skip("Operator user not available")
        
        resp = self.session.post(f"{BASE_URL}/api/security/block-ip", json={
            "ip": "1.2.3.4",
            "reason": "Test"
        })
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
        print("✓ Non-admin gets 403 on POST /api/security/block-ip")
    
    def test_non_admin_gets_403_on_unblock_ip(self):
        """Non-admin user gets 403 on POST /api/security/unblock-ip"""
        if not self.has_operator:
            pytest.skip("Operator user not available")
        
        resp = self.session.post(f"{BASE_URL}/api/security/unblock-ip", json={
            "ip": "1.2.3.4"
        })
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
        print("✓ Non-admin gets 403 on POST /api/security/unblock-ip")
    
    def test_non_admin_gets_403_on_ip_block_config(self):
        """Non-admin user gets 403 on GET /api/security/ip-block-config"""
        if not self.has_operator:
            pytest.skip("Operator user not available")
        
        resp = self.session.get(f"{BASE_URL}/api/security/ip-block-config")
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
        print("✓ Non-admin gets 403 on GET /api/security/ip-block-config")
    
    def test_non_admin_gets_403_on_save_config(self):
        """Non-admin user gets 403 on POST /api/security/ip-block-config"""
        if not self.has_operator:
            pytest.skip("Operator user not available")
        
        resp = self.session.post(f"{BASE_URL}/api/security/ip-block-config", json={
            "enabled": True
        })
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
        print("✓ Non-admin gets 403 on POST /api/security/ip-block-config")


class TestLoginAfterIPBlockMiddleware:
    """Test that login still works correctly after adding IP block middleware"""
    
    def test_login_works_correctly(self):
        """Login still works correctly after adding IP block middleware"""
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        
        resp = session.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        
        assert resp.status_code == 200, f"Login should work, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "token" in data, "Login should return token"
        assert "user" in data, "Login should return user"
        print("✓ Login works correctly after IP block middleware")
    
    def test_invalid_login_returns_401(self):
        """Invalid login still returns 401 (not blocked by middleware)"""
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        
        resp = session.post(f"{BASE_URL}/api/auth/login", json={
            "email": "nonexistent@test.com",
            "password": "wrongpassword"
        })
        
        assert resp.status_code == 401, f"Invalid login should return 401, got {resp.status_code}: {resp.text}"
        print("✓ Invalid login returns 401 correctly")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
