"""
Connector Vault Credentials API Tests
Tests for the NEW endpoint GET /api/connector/vault/credentials
This endpoint allows the Windows connector to fetch decrypted credentials via API key
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

# Test data prefix for cleanup
TEST_PREFIX = "TEST_CONNECTOR_"


class TestConnectorVaultEndpoint:
    """Test the connector vault credentials endpoint"""
    
    @pytest.fixture(scope="class")
    def admin_headers(self):
        """Get admin authentication headers"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200, f"Admin login failed: {response.text}"
        token = response.json().get("token")
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    
    def test_connector_vault_requires_api_key(self):
        """GET /api/connector/vault/credentials requires X-API-Key header"""
        response = requests.get(f"{BASE_URL}/api/connector/vault/credentials")
        assert response.status_code in [401, 403], f"Expected 401/403 without API key, got {response.status_code}"
        print("✓ Connector vault endpoint requires API key")
    
    def test_connector_vault_invalid_api_key(self):
        """GET /api/connector/vault/credentials rejects invalid API key"""
        response = requests.get(
            f"{BASE_URL}/api/connector/vault/credentials",
            headers={"X-API-Key": "invalid_key_12345"}
        )
        assert response.status_code in [401, 403], f"Expected 401/403 with invalid key, got {response.status_code}"
        print("✓ Connector vault endpoint rejects invalid API key")
    
    def test_connector_vault_returns_decrypted_credentials(self):
        """GET /api/connector/vault/credentials returns decrypted credentials with valid API key"""
        response = requests.get(
            f"{BASE_URL}/api/connector/vault/credentials",
            headers={"X-API-Key": CONNECTOR_API_KEY}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        credentials = response.json()
        assert isinstance(credentials, list), "Response should be a list"
        
        print(f"✓ Connector vault returns {len(credentials)} credentials")
        
        # Verify structure of returned credentials
        if len(credentials) > 0:
            cred = credentials[0]
            assert "device_ip" in cred, "Credential should have device_ip"
            assert "device_name" in cred, "Credential should have device_name"
            assert "credential_type" in cred, "Credential should have credential_type"
            assert "username" in cred, "Credential should have username"
            assert "password" in cred, "Credential should have password"
            
            # Verify password is NOT masked (should be decrypted)
            assert cred["password"] != "********", "Password should be decrypted, not masked"
            
            # Verify no encrypted fields exposed
            assert "username_enc" not in cred, "Encrypted username should not be exposed"
            assert "password_enc" not in cred, "Encrypted password should not be exposed"
            
            print(f"✓ Credential structure verified: {cred['device_name']} ({cred['credential_type']})")
    
    def test_connector_vault_returns_existing_credentials(self):
        """Verify existing credentials (ILO, SNMP) are returned"""
        response = requests.get(
            f"{BASE_URL}/api/connector/vault/credentials",
            headers={"X-API-Key": CONNECTOR_API_KEY}
        )
        assert response.status_code == 200
        
        credentials = response.json()
        
        # Check for known credentials
        ilo_cred = next((c for c in credentials if c.get("credential_type") == "ilo"), None)
        snmp_cred = next((c for c in credentials if c.get("credential_type") == "snmp"), None)
        
        if ilo_cred:
            print(f"✓ Found ILO credential: {ilo_cred['device_name']} - {ilo_cred['device_ip']}")
            assert ilo_cred["username"], "ILO credential should have username"
            assert ilo_cred["password"], "ILO credential should have password"
        
        if snmp_cred:
            print(f"✓ Found SNMP credential: {snmp_cred['device_name']} - {snmp_cred['device_ip']}")
            assert snmp_cred["username"], "SNMP credential should have username"
            assert snmp_cred["password"], "SNMP credential should have password"
    
    def test_connector_vault_create_and_fetch(self, admin_headers):
        """Create a credential via admin API and verify connector can fetch it"""
        unique_id = str(uuid.uuid4())[:8]
        
        # Create credential via admin API
        cred_data = {
            "device_ip": f"10.99.99.{hash(unique_id) % 255}",
            "device_name": f"{TEST_PREFIX}Device_{unique_id}",
            "credential_type": "ssh",
            "username": f"connector_test_user_{unique_id}",
            "password": f"ConnectorTestPass_{unique_id}!",
            "port": 22,
            "tags": ["test", "connector"]
        }
        
        create_resp = requests.post(
            f"{BASE_URL}/api/vault/credentials",
            headers=admin_headers,
            json=cred_data
        )
        assert create_resp.status_code == 200, f"Create failed: {create_resp.text}"
        cred_id = create_resp.json()["id"]
        
        try:
            # Fetch via connector API
            connector_resp = requests.get(
                f"{BASE_URL}/api/connector/vault/credentials",
                headers={"X-API-Key": CONNECTOR_API_KEY}
            )
            assert connector_resp.status_code == 200
            
            credentials = connector_resp.json()
            
            # Find our test credential
            test_cred = next((c for c in credentials if c.get("device_name") == cred_data["device_name"]), None)
            assert test_cred is not None, f"Created credential should be in connector response"
            
            # Verify decrypted values match
            assert test_cred["username"] == cred_data["username"], \
                f"Username mismatch: expected {cred_data['username']}, got {test_cred['username']}"
            assert test_cred["password"] == cred_data["password"], \
                f"Password mismatch: expected {cred_data['password']}, got {test_cred['password']}"
            
            print(f"✓ Connector can fetch newly created credential with correct decrypted values")
        finally:
            # Cleanup
            requests.delete(f"{BASE_URL}/api/vault/credentials/{cred_id}", headers=admin_headers)


class TestVaultPersistenceAfterRestart:
    """Test that credentials persist after server restart (ENCRYPTION_KEY fix verification)"""
    
    def test_existing_credentials_decrypt_correctly(self):
        """Verify existing credentials (created before restart) decrypt correctly"""
        response = requests.get(
            f"{BASE_URL}/api/connector/vault/credentials",
            headers={"X-API-Key": CONNECTOR_API_KEY}
        )
        assert response.status_code == 200
        
        credentials = response.json()
        
        # Check that no credentials have decryption errors
        for cred in credentials:
            username = cred.get("username", "")
            password = cred.get("password", "")
            
            # Check for decryption error markers
            assert "[errore decifratura]" not in username, \
                f"Credential {cred.get('device_name')} has decryption error in username"
            assert "[errore decifratura]" not in password, \
                f"Credential {cred.get('device_name')} has decryption error in password"
            assert "error" not in username.lower() or "error" in cred.get("device_name", "").lower(), \
                f"Credential {cred.get('device_name')} may have decryption issue"
        
        print(f"✓ All {len(credentials)} credentials decrypt correctly (ENCRYPTION_KEY persistence verified)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
