"""
Test suite for Redfish Direct Polling & Failover Features (Iteration 17)
Tests:
- POST /api/vault/credentials - create with external_url field
- GET /api/vault/credentials - list with masked passwords
- GET /api/vault/credentials/{id} - decrypt credentials
- PUT /api/vault/credentials/{id}/direct-poll - enable/disable direct polling
- GET /api/redfish/failover-status - returns polling mode for each iLO device
- POST /api/redfish/test-connection - test Redfish connection from backend
- POST /api/redfish/poll-now - trigger manual poll
- GET /api/connector/vault/credentials - connector fetches credentials via API key
- Role-based access: non-admin gets 403 on vault and redfish endpoints
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
ADMIN_EMAIL = "admin@86bit.it"
ADMIN_PASSWORD = "admin123"
CONNECTOR_API_KEY = "noc_35cf39b4d68740b1a981aedef2ee293d"

# Existing credential IDs from the review request
EXISTING_ILO_CRED_ID = "6d272a2c-f7ea-4628-b9fd-ed0a12f44ba5"
EXISTING_SNMP_CRED_ID = "2bf9db52-ecb2-45a8-a1cb-6aeb102777a4"


@pytest.fixture(scope="module")
def admin_token():
    """Get admin authentication token."""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD
    })
    assert response.status_code == 200, f"Admin login failed: {response.text}"
    return response.json()["token"]


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    """Headers with admin auth token."""
    return {
        "Authorization": f"Bearer {admin_token}",
        "Content-Type": "application/json"
    }


@pytest.fixture(scope="module")
def operator_token():
    """Get or create operator user and return token."""
    # Try to login as operator
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "operator@test.com",
        "password": "operator123"
    })
    if response.status_code == 200:
        return response.json()["token"]
    
    # Create operator user if doesn't exist
    admin_resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD
    })
    admin_token = admin_resp.json()["token"]
    
    requests.post(f"{BASE_URL}/api/admin/users", 
        headers={"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"},
        json={
            "email": "operator@test.com",
            "password": "operator123",
            "name": "Test Operator",
            "role": "operator"
        }
    )
    
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "operator@test.com",
        "password": "operator123"
    })
    if response.status_code == 200:
        return response.json()["token"]
    pytest.skip("Could not create operator user")


@pytest.fixture(scope="module")
def operator_headers(operator_token):
    """Headers with operator auth token."""
    return {
        "Authorization": f"Bearer {operator_token}",
        "Content-Type": "application/json"
    }


class TestVaultCredentialsWithExternalUrl:
    """Test vault credentials CRUD with external_url field."""
    
    def test_list_credentials_returns_masked_passwords(self, admin_headers):
        """GET /api/vault/credentials returns credentials with masked passwords."""
        response = requests.get(f"{BASE_URL}/api/vault/credentials", headers=admin_headers)
        assert response.status_code == 200, f"Failed: {response.text}"
        
        creds = response.json()
        assert isinstance(creds, list)
        
        # Check that passwords are masked
        for cred in creds:
            assert cred.get("password") == "********", f"Password not masked for {cred.get('id')}"
            assert "username" in cred, "Username should be present"
            assert "password_enc" not in cred, "Encrypted password should not be exposed"
            assert "username_enc" not in cred, "Encrypted username should not be exposed"
    
    def test_get_existing_ilo_credential_decrypted(self, admin_headers):
        """GET /api/vault/credentials/{id} returns decrypted credentials for existing ILO."""
        response = requests.get(f"{BASE_URL}/api/vault/credentials/{EXISTING_ILO_CRED_ID}", headers=admin_headers)
        assert response.status_code == 200, f"Failed: {response.text}"
        
        cred = response.json()
        assert cred.get("id") == EXISTING_ILO_CRED_ID
        assert cred.get("credential_type") == "ilo"
        assert cred.get("username") is not None, "Username should be decrypted"
        assert cred.get("password") is not None, "Password should be decrypted"
        assert cred.get("password") != "********", "Password should be decrypted, not masked"
    
    def test_create_credential_with_external_url(self, admin_headers):
        """POST /api/vault/credentials creates credential with external_url field."""
        test_cred = {
            "device_ip": "10.0.0.99",
            "device_name": "TEST_ILO_External",
            "credential_type": "ilo",
            "username": "testadmin",
            "password": "testpass123",
            "external_url": "https://ilo-test.example.com:443",
            "port": 443,
            "notes": "Test credential with external URL"
        }
        
        response = requests.post(f"{BASE_URL}/api/vault/credentials", headers=admin_headers, json=test_cred)
        assert response.status_code == 200, f"Failed: {response.text}"
        
        data = response.json()
        assert data.get("status") == "ok"
        assert "id" in data
        
        # Verify the credential was created with external_url
        cred_id = data["id"]
        get_resp = requests.get(f"{BASE_URL}/api/vault/credentials/{cred_id}", headers=admin_headers)
        assert get_resp.status_code == 200
        
        cred = get_resp.json()
        assert cred.get("external_url") == "https://ilo-test.example.com:443"
        assert cred.get("username") == "testadmin"
        assert cred.get("password") == "testpass123"
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/vault/credentials/{cred_id}", headers=admin_headers)
    
    def test_get_nonexistent_credential_returns_404(self, admin_headers):
        """GET /api/vault/credentials/{id} returns 404 for non-existent credential."""
        fake_id = str(uuid.uuid4())
        response = requests.get(f"{BASE_URL}/api/vault/credentials/{fake_id}", headers=admin_headers)
        assert response.status_code == 404


class TestDirectPollToggle:
    """Test PUT /api/vault/credentials/{id}/direct-poll endpoint."""
    
    def test_enable_direct_poll(self, admin_headers):
        """PUT /api/vault/credentials/{id}/direct-poll enables direct polling."""
        response = requests.put(
            f"{BASE_URL}/api/vault/credentials/{EXISTING_ILO_CRED_ID}/direct-poll",
            headers=admin_headers,
            json={"direct_poll": True}
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        assert response.json().get("status") == "ok"
    
    def test_disable_direct_poll(self, admin_headers):
        """PUT /api/vault/credentials/{id}/direct-poll disables direct polling."""
        response = requests.put(
            f"{BASE_URL}/api/vault/credentials/{EXISTING_ILO_CRED_ID}/direct-poll",
            headers=admin_headers,
            json={"direct_poll": False}
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        assert response.json().get("status") == "ok"
    
    def test_set_external_url_via_direct_poll(self, admin_headers):
        """PUT /api/vault/credentials/{id}/direct-poll can set external_url."""
        response = requests.put(
            f"{BASE_URL}/api/vault/credentials/{EXISTING_ILO_CRED_ID}/direct-poll",
            headers=admin_headers,
            json={"external_url": "https://ilo.86bit.internal:443"}
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        assert response.json().get("status") == "ok"
    
    def test_direct_poll_nonexistent_credential_returns_404(self, admin_headers):
        """PUT /api/vault/credentials/{id}/direct-poll returns 404 for non-existent credential."""
        fake_id = str(uuid.uuid4())
        response = requests.put(
            f"{BASE_URL}/api/vault/credentials/{fake_id}/direct-poll",
            headers=admin_headers,
            json={"direct_poll": True}
        )
        assert response.status_code == 404
    
    def test_direct_poll_empty_body_returns_400(self, admin_headers):
        """PUT /api/vault/credentials/{id}/direct-poll returns 400 for empty body."""
        response = requests.put(
            f"{BASE_URL}/api/vault/credentials/{EXISTING_ILO_CRED_ID}/direct-poll",
            headers=admin_headers,
            json={}
        )
        assert response.status_code == 400


class TestRedfishFailoverStatus:
    """Test GET /api/redfish/failover-status endpoint."""
    
    def test_get_failover_status(self, admin_headers):
        """GET /api/redfish/failover-status returns polling mode for iLO devices."""
        response = requests.get(f"{BASE_URL}/api/redfish/failover-status", headers=admin_headers)
        assert response.status_code == 200, f"Failed: {response.text}"
        
        data = response.json()
        assert isinstance(data, list)
        
        # Check structure of each item
        for item in data:
            assert "device_ip" in item
            assert "polling_mode" in item
            # polling_mode should be one of: direct, failover, connector, offline
            assert item["polling_mode"] in ["direct", "failover", "connector", "offline"], \
                f"Invalid polling_mode: {item['polling_mode']}"
    
    def test_failover_status_requires_admin(self, operator_headers):
        """GET /api/redfish/failover-status returns 403 for non-admin."""
        response = requests.get(f"{BASE_URL}/api/redfish/failover-status", headers=operator_headers)
        assert response.status_code == 403


class TestRedfishTestConnection:
    """Test POST /api/redfish/test-connection endpoint."""
    
    def test_test_connection_returns_error_gracefully(self, admin_headers):
        """POST /api/redfish/test-connection returns error gracefully for unreachable iLO."""
        response = requests.post(
            f"{BASE_URL}/api/redfish/test-connection",
            headers=admin_headers,
            json={
                "url": "https://192.168.1.99:443",
                "username": "admin",
                "password": "password"
            }
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        
        data = response.json()
        # Should return success=False with an error message
        assert "success" in data
        assert data["success"] == False, "Should fail for unreachable iLO"
        assert "error" in data, "Should include error message"
    
    def test_test_connection_missing_url_returns_400(self, admin_headers):
        """POST /api/redfish/test-connection returns 400 for missing URL."""
        response = requests.post(
            f"{BASE_URL}/api/redfish/test-connection",
            headers=admin_headers,
            json={
                "username": "admin",
                "password": "password"
            }
        )
        assert response.status_code == 400
    
    def test_test_connection_requires_admin(self, operator_headers):
        """POST /api/redfish/test-connection returns 403 for non-admin."""
        response = requests.post(
            f"{BASE_URL}/api/redfish/test-connection",
            headers=operator_headers,
            json={
                "url": "https://192.168.1.99:443",
                "username": "admin",
                "password": "password"
            }
        )
        assert response.status_code == 403


class TestRedfishPollNow:
    """Test POST /api/redfish/poll-now endpoint."""
    
    def test_trigger_manual_poll(self, admin_headers):
        """POST /api/redfish/poll-now triggers manual poll cycle."""
        response = requests.post(f"{BASE_URL}/api/redfish/poll-now", headers=admin_headers)
        assert response.status_code == 200, f"Failed: {response.text}"
        
        data = response.json()
        assert data.get("status") == "ok"
        assert "message" in data
    
    def test_poll_now_requires_admin(self, operator_headers):
        """POST /api/redfish/poll-now returns 403 for non-admin."""
        response = requests.post(f"{BASE_URL}/api/redfish/poll-now", headers=operator_headers)
        assert response.status_code == 403


class TestConnectorVaultCredentials:
    """Test GET /api/connector/vault/credentials endpoint."""
    
    def test_connector_fetches_credentials_with_api_key(self):
        """GET /api/connector/vault/credentials returns decrypted credentials with valid API key."""
        response = requests.get(
            f"{BASE_URL}/api/connector/vault/credentials",
            headers={"X-API-Key": CONNECTOR_API_KEY}
        )
        assert response.status_code == 200, f"Failed: {response.text}"
        
        creds = response.json()
        assert isinstance(creds, list)
        
        # Check that credentials are decrypted
        for cred in creds:
            assert "username" in cred
            assert "password" in cred
            # Password should be decrypted, not masked
            if cred.get("password"):
                assert cred["password"] != "********", "Password should be decrypted for connector"
    
    def test_connector_requires_api_key(self):
        """GET /api/connector/vault/credentials returns 401 without API key."""
        response = requests.get(f"{BASE_URL}/api/connector/vault/credentials")
        assert response.status_code == 401
    
    def test_connector_rejects_invalid_api_key(self):
        """GET /api/connector/vault/credentials returns 401 for invalid API key."""
        response = requests.get(
            f"{BASE_URL}/api/connector/vault/credentials",
            headers={"X-API-Key": "invalid_key_12345"}
        )
        assert response.status_code == 401


class TestRoleBasedAccess:
    """Test that non-admin users get 403 on vault and redfish endpoints."""
    
    def test_vault_list_requires_admin(self, operator_headers):
        """GET /api/vault/credentials returns 403 for non-admin."""
        response = requests.get(f"{BASE_URL}/api/vault/credentials", headers=operator_headers)
        assert response.status_code == 403
    
    def test_vault_get_requires_admin(self, operator_headers):
        """GET /api/vault/credentials/{id} returns 403 for non-admin."""
        response = requests.get(f"{BASE_URL}/api/vault/credentials/{EXISTING_ILO_CRED_ID}", headers=operator_headers)
        assert response.status_code == 403
    
    def test_vault_create_requires_admin(self, operator_headers):
        """POST /api/vault/credentials returns 403 for non-admin."""
        response = requests.post(
            f"{BASE_URL}/api/vault/credentials",
            headers=operator_headers,
            json={
                "device_ip": "10.0.0.1",
                "credential_type": "ilo",
                "username": "test",
                "password": "test"
            }
        )
        assert response.status_code == 403
    
    def test_vault_update_requires_admin(self, operator_headers):
        """PUT /api/vault/credentials/{id} returns 403 for non-admin."""
        response = requests.put(
            f"{BASE_URL}/api/vault/credentials/{EXISTING_ILO_CRED_ID}",
            headers=operator_headers,
            json={"notes": "test"}
        )
        assert response.status_code == 403
    
    def test_vault_delete_requires_admin(self, operator_headers):
        """DELETE /api/vault/credentials/{id} returns 403 for non-admin."""
        response = requests.delete(
            f"{BASE_URL}/api/vault/credentials/{EXISTING_ILO_CRED_ID}",
            headers=operator_headers
        )
        assert response.status_code == 403
    
    def test_direct_poll_requires_admin(self, operator_headers):
        """PUT /api/vault/credentials/{id}/direct-poll returns 403 for non-admin."""
        response = requests.put(
            f"{BASE_URL}/api/vault/credentials/{EXISTING_ILO_CRED_ID}/direct-poll",
            headers=operator_headers,
            json={"direct_poll": True}
        )
        assert response.status_code == 403


class TestEncryptionKeyPersistence:
    """Test that ENCRYPTION_KEY persists and credentials survive restart."""
    
    def test_existing_credentials_decrypt_correctly(self, admin_headers):
        """Existing credentials should decrypt correctly (ENCRYPTION_KEY persistence)."""
        # Get the existing ILO credential
        response = requests.get(f"{BASE_URL}/api/vault/credentials/{EXISTING_ILO_CRED_ID}", headers=admin_headers)
        assert response.status_code == 200, f"Failed: {response.text}"
        
        cred = response.json()
        # Should have decrypted username and password
        assert cred.get("username") is not None
        assert cred.get("password") is not None
        assert cred.get("password") != "********"
        
        # Username should be 'administrator' based on iteration_16 report
        assert cred.get("username") == "administrator", f"Expected 'administrator', got '{cred.get('username')}'"
    
    def test_existing_snmp_credential_decrypts(self, admin_headers):
        """Existing SNMP credential should decrypt correctly."""
        response = requests.get(f"{BASE_URL}/api/vault/credentials/{EXISTING_SNMP_CRED_ID}", headers=admin_headers)
        assert response.status_code == 200, f"Failed: {response.text}"
        
        cred = response.json()
        assert cred.get("credential_type") == "snmp"
        assert cred.get("username") is not None
        assert cred.get("password") is not None
