"""
Test Security Audit Dashboard API
Tests for GET /api/audit/security-dashboard endpoint
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://snmp-monitor-staging.preview.emergentagent.com').rstrip('/')

# Test credentials
ADMIN_EMAIL = "admin@86bit.it"
ADMIN_PASSWORD = "admin123"
NON_ADMIN_EMAIL = "operator@test.com"
NON_ADMIN_PASSWORD = "operator123"


@pytest.fixture(scope="module")
def admin_token():
    """Get admin JWT token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD
    })
    assert response.status_code == 200, f"Admin login failed: {response.text}"
    data = response.json()
    assert "token" in data, "No token in login response"
    return data["token"]


@pytest.fixture(scope="module")
def operator_token():
    """Get operator (non-admin) JWT token - create user if needed"""
    # First try to login
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": NON_ADMIN_EMAIL,
        "password": NON_ADMIN_PASSWORD
    })
    if response.status_code == 200:
        return response.json()["token"]
    
    # If login fails, create the user via admin
    admin_response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD
    })
    if admin_response.status_code != 200:
        pytest.skip("Cannot create operator user - admin login failed")
    
    admin_token = admin_response.json()["token"]
    
    # Create operator user
    create_response = requests.post(
        f"{BASE_URL}/api/admin/users",
        json={
            "email": NON_ADMIN_EMAIL,
            "password": NON_ADMIN_PASSWORD,
            "name": "Test Operator",
            "role": "operator"
        },
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    
    if create_response.status_code not in [200, 201, 400]:  # 400 = already exists
        pytest.skip(f"Cannot create operator user: {create_response.text}")
    
    # Now login as operator
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": NON_ADMIN_EMAIL,
        "password": NON_ADMIN_PASSWORD
    })
    if response.status_code != 200:
        pytest.skip(f"Operator login failed: {response.text}")
    
    return response.json()["token"]


class TestSecurityDashboardEndpoint:
    """Tests for GET /api/audit/security-dashboard"""
    
    def test_security_dashboard_requires_auth(self):
        """Test that endpoint requires authentication"""
        response = requests.get(f"{BASE_URL}/api/audit/security-dashboard")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("PASS: Security dashboard requires authentication")
    
    def test_security_dashboard_admin_access(self, admin_token):
        """Test that admin can access security dashboard"""
        response = requests.get(
            f"{BASE_URL}/api/audit/security-dashboard",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200, f"Admin access failed: {response.status_code} - {response.text}"
        print("PASS: Admin can access security dashboard")
    
    def test_security_dashboard_non_admin_forbidden(self, operator_token):
        """Test that non-admin gets 403 Forbidden"""
        response = requests.get(
            f"{BASE_URL}/api/audit/security-dashboard",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 403, f"Expected 403 for non-admin, got {response.status_code}"
        print("PASS: Non-admin gets 403 Forbidden")
    
    def test_security_dashboard_response_structure(self, admin_token):
        """Test that response contains all required fields"""
        response = requests.get(
            f"{BASE_URL}/api/audit/security-dashboard",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Check top-level keys
        required_keys = ["stats", "failed_logins", "locked_accounts", "suspicious_ips", "timeline", "critical_events"]
        for key in required_keys:
            assert key in data, f"Missing required key: {key}"
        
        print(f"PASS: Response contains all required keys: {required_keys}")
    
    def test_security_dashboard_stats_fields(self, admin_token):
        """Test that stats object contains all required fields"""
        response = requests.get(
            f"{BASE_URL}/api/audit/security-dashboard",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        stats = data.get("stats", {})
        required_stats = [
            "failed_logins_24h",
            "success_logins_24h", 
            "locked_accounts",
            "active_sessions",
            "revoked_tokens_24h",
            "critical_events_24h",
            "twofa_coverage"
        ]
        
        for stat in required_stats:
            assert stat in stats, f"Missing stat: {stat}"
        
        print(f"PASS: Stats contains all required fields: {required_stats}")
        print(f"  - failed_logins_24h: {stats['failed_logins_24h']}")
        print(f"  - success_logins_24h: {stats['success_logins_24h']}")
        print(f"  - locked_accounts: {stats['locked_accounts']}")
        print(f"  - active_sessions: {stats['active_sessions']}")
        print(f"  - revoked_tokens_24h: {stats['revoked_tokens_24h']}")
        print(f"  - critical_events_24h: {stats['critical_events_24h']}")
        print(f"  - twofa_coverage: {stats['twofa_coverage']}")
    
    def test_security_dashboard_failed_logins_structure(self, admin_token):
        """Test failed_logins array structure"""
        response = requests.get(
            f"{BASE_URL}/api/audit/security-dashboard",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        failed_logins = data.get("failed_logins", [])
        assert isinstance(failed_logins, list), "failed_logins should be a list"
        
        # If there are failed logins, check structure
        if len(failed_logins) > 0:
            log = failed_logins[0]
            # Should have timestamp, user_email, ip_address
            assert "timestamp" in log or "action" in log, "Failed login should have timestamp or action"
        
        print(f"PASS: failed_logins is a list with {len(failed_logins)} entries")
    
    def test_security_dashboard_suspicious_ips_structure(self, admin_token):
        """Test suspicious_ips array structure"""
        response = requests.get(
            f"{BASE_URL}/api/audit/security-dashboard",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        suspicious_ips = data.get("suspicious_ips", [])
        assert isinstance(suspicious_ips, list), "suspicious_ips should be a list"
        
        # If there are suspicious IPs, check structure
        if len(suspicious_ips) > 0:
            ip_entry = suspicious_ips[0]
            assert "ip" in ip_entry, "IP entry should have 'ip' field"
            assert "attempts" in ip_entry, "IP entry should have 'attempts' field"
        
        print(f"PASS: suspicious_ips is a list with {len(suspicious_ips)} entries")
    
    def test_security_dashboard_timeline_structure(self, admin_token):
        """Test timeline array structure (7-day data)"""
        response = requests.get(
            f"{BASE_URL}/api/audit/security-dashboard",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        timeline = data.get("timeline", [])
        assert isinstance(timeline, list), "timeline should be a list"
        
        # If there's timeline data, check structure
        if len(timeline) > 0:
            day_entry = timeline[0]
            assert "date" in day_entry, "Timeline entry should have 'date' field"
            assert "failed" in day_entry, "Timeline entry should have 'failed' field"
            assert "success" in day_entry, "Timeline entry should have 'success' field"
            assert "total" in day_entry, "Timeline entry should have 'total' field"
        
        print(f"PASS: timeline is a list with {len(timeline)} entries (7-day data)")
    
    def test_security_dashboard_critical_events_structure(self, admin_token):
        """Test critical_events array structure"""
        response = requests.get(
            f"{BASE_URL}/api/audit/security-dashboard",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        critical_events = data.get("critical_events", [])
        assert isinstance(critical_events, list), "critical_events should be a list"
        
        # If there are critical events, check structure
        if len(critical_events) > 0:
            event = critical_events[0]
            assert "action" in event or "severity" in event, "Event should have action or severity"
        
        print(f"PASS: critical_events is a list with {len(critical_events)} entries")
    
    def test_security_dashboard_locked_accounts_structure(self, admin_token):
        """Test locked_accounts array structure"""
        response = requests.get(
            f"{BASE_URL}/api/audit/security-dashboard",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        
        locked_accounts = data.get("locked_accounts", [])
        assert isinstance(locked_accounts, list), "locked_accounts should be a list"
        
        # If there are locked accounts, check structure
        if len(locked_accounts) > 0:
            account = locked_accounts[0]
            assert "email" in account, "Locked account should have 'email' field"
        
        print(f"PASS: locked_accounts is a list with {len(locked_accounts)} entries")


class TestSecurityDashboardDataIntegrity:
    """Tests for data integrity and values"""
    
    def test_stats_values_are_numeric(self, admin_token):
        """Test that numeric stats are actually numbers"""
        response = requests.get(
            f"{BASE_URL}/api/audit/security-dashboard",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        stats = response.json().get("stats", {})
        
        numeric_fields = [
            "failed_logins_24h",
            "success_logins_24h",
            "locked_accounts",
            "active_sessions",
            "revoked_tokens_24h",
            "critical_events_24h"
        ]
        
        for field in numeric_fields:
            value = stats.get(field)
            assert isinstance(value, (int, float)), f"{field} should be numeric, got {type(value)}"
            assert value >= 0, f"{field} should be non-negative"
        
        print("PASS: All numeric stats are valid non-negative numbers")
    
    def test_twofa_coverage_format(self, admin_token):
        """Test that twofa_coverage is in correct format (e.g., '1/5')"""
        response = requests.get(
            f"{BASE_URL}/api/audit/security-dashboard",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        stats = response.json().get("stats", {})
        
        twofa = stats.get("twofa_coverage", "")
        assert "/" in str(twofa), f"twofa_coverage should be in 'X/Y' format, got: {twofa}"
        
        print(f"PASS: twofa_coverage format is correct: {twofa}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
