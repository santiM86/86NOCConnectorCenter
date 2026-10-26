"""
Vault Credentials API Tests
Tests for AES-256-GCM encrypted credentials vault - CRUD operations and access control
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
ADMIN_EMAIL = "admin@86bit.it"
ADMIN_PASSWORD = "admin123"

# Test data prefix for cleanup
TEST_PREFIX = "TEST_VAULT_"


class TestVaultAuth:
    """Test authentication and authorization for vault endpoints"""
    
    @pytest.fixture(scope="class")
    def admin_token(self):
        """Get admin authentication token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200, f"Admin login failed: {response.text}"
        data = response.json()
        return data.get("token")
    
    @pytest.fixture(scope="class")
    def admin_headers(self, admin_token):
        """Headers with admin auth token"""
        return {
            "Authorization": f"Bearer {admin_token}",
            "Content-Type": "application/json"
        }
    
    def test_login_admin_success(self):
        """Test admin login with correct credentials"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert data["user"]["role"] == "admin"
        print(f"✓ Admin login successful, role: {data['user']['role']}")
    
    def test_vault_list_requires_auth(self):
        """Test that vault list endpoint requires authentication"""
        response = requests.get(f"{BASE_URL}/api/vault/credentials")
        assert response.status_code == 403 or response.status_code == 401
        print("✓ Vault list requires authentication")
    
    def test_vault_create_requires_auth(self):
        """Test that vault create endpoint requires authentication"""
        response = requests.post(f"{BASE_URL}/api/vault/credentials", json={
            "credential_type": "ssh",
            "username": "test",
            "password": "test123"
        })
        assert response.status_code == 403 or response.status_code == 401
        print("✓ Vault create requires authentication")


class TestVaultCRUD:
    """Test CRUD operations for vault credentials"""
    
    @pytest.fixture(scope="class")
    def admin_token(self):
        """Get admin authentication token"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200, f"Admin login failed: {response.text}"
        return response.json().get("token")
    
    @pytest.fixture(scope="class")
    def admin_headers(self, admin_token):
        """Headers with admin auth token"""
        return {
            "Authorization": f"Bearer {admin_token}",
            "Content-Type": "application/json"
        }
    
    @pytest.fixture
    def test_credential_data(self):
        """Generate unique test credential data"""
        unique_id = str(uuid.uuid4())[:8]
        return {
            "device_ip": f"192.168.99.{unique_id[:3].replace('-', '1')}",
            "device_name": f"{TEST_PREFIX}Device_{unique_id}",
            "credential_type": "ilo",
            "username": f"admin_{unique_id}",
            "password": f"SecurePass_{unique_id}!",
            "url": f"https://192.168.99.{unique_id[:3].replace('-', '1')}",
            "port": 443,
            "notes": f"Test credential created by pytest - {unique_id}",
            "tags": ["test", "pytest", "vault"]
        }
    
    def test_create_credential_returns_id(self, admin_headers, test_credential_data):
        """POST /api/vault/credentials creates a new credential and returns id"""
        response = requests.post(
            f"{BASE_URL}/api/vault/credentials",
            headers=admin_headers,
            json=test_credential_data
        )
        assert response.status_code == 200, f"Create failed: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert "id" in data, "Response should contain 'id'"
        assert data.get("status") == "ok"
        assert "AES-256-GCM" in data.get("message", "")
        
        print(f"✓ Created credential with id: {data['id']}")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/vault/credentials/{data['id']}", headers=admin_headers)
    
    def test_list_credentials_returns_masked_passwords(self, admin_headers, test_credential_data):
        """GET /api/vault/credentials lists credentials with masked passwords (********)"""
        # First create a credential
        create_resp = requests.post(
            f"{BASE_URL}/api/vault/credentials",
            headers=admin_headers,
            json=test_credential_data
        )
        assert create_resp.status_code == 200
        cred_id = create_resp.json()["id"]
        
        try:
            # List credentials
            response = requests.get(f"{BASE_URL}/api/vault/credentials", headers=admin_headers)
            assert response.status_code == 200, f"List failed: {response.text}"
            
            credentials = response.json()
            assert isinstance(credentials, list), "Response should be a list"
            
            # Find our test credential
            test_cred = next((c for c in credentials if c.get("id") == cred_id), None)
            assert test_cred is not None, "Created credential should be in list"
            
            # Verify password is masked
            assert test_cred.get("password") == "********", f"Password should be masked, got: {test_cred.get('password')}"
            
            # Verify username is decrypted (not encrypted blob)
            assert test_cred.get("username") == test_credential_data["username"], \
                f"Username should be decrypted, got: {test_cred.get('username')}"
            
            # Verify other fields
            assert test_cred.get("device_name") == test_credential_data["device_name"]
            assert test_cred.get("credential_type") == test_credential_data["credential_type"]
            
            print(f"✓ List returns {len(credentials)} credentials with masked passwords")
        finally:
            # Cleanup
            requests.delete(f"{BASE_URL}/api/vault/credentials/{cred_id}", headers=admin_headers)
    
    def test_get_credential_returns_decrypted(self, admin_headers, test_credential_data):
        """GET /api/vault/credentials/{id} returns decrypted username and password"""
        # Create credential
        create_resp = requests.post(
            f"{BASE_URL}/api/vault/credentials",
            headers=admin_headers,
            json=test_credential_data
        )
        assert create_resp.status_code == 200
        cred_id = create_resp.json()["id"]
        
        try:
            # Get single credential (should be decrypted)
            response = requests.get(
                f"{BASE_URL}/api/vault/credentials/{cred_id}",
                headers=admin_headers
            )
            assert response.status_code == 200, f"Get failed: {response.text}"
            
            cred = response.json()
            
            # Verify decrypted values
            assert cred.get("username") == test_credential_data["username"], \
                f"Username should be decrypted: expected {test_credential_data['username']}, got {cred.get('username')}"
            assert cred.get("password") == test_credential_data["password"], \
                f"Password should be decrypted: expected {test_credential_data['password']}, got {cred.get('password')}"
            
            # Verify no encrypted fields exposed
            assert "username_enc" not in cred, "Encrypted username should not be exposed"
            assert "password_enc" not in cred, "Encrypted password should not be exposed"
            
            print(f"✓ Get credential returns decrypted username and password")
        finally:
            # Cleanup
            requests.delete(f"{BASE_URL}/api/vault/credentials/{cred_id}", headers=admin_headers)
    
    def test_update_credential(self, admin_headers, test_credential_data):
        """PUT /api/vault/credentials/{id} updates credential fields"""
        # Create credential
        create_resp = requests.post(
            f"{BASE_URL}/api/vault/credentials",
            headers=admin_headers,
            json=test_credential_data
        )
        assert create_resp.status_code == 200
        cred_id = create_resp.json()["id"]
        
        try:
            # Update credential
            update_data = {
                "device_name": f"{TEST_PREFIX}Updated_Device",
                "username": "updated_admin",
                "password": "UpdatedPass123!",
                "notes": "Updated by pytest"
            }
            
            response = requests.put(
                f"{BASE_URL}/api/vault/credentials/{cred_id}",
                headers=admin_headers,
                json=update_data
            )
            assert response.status_code == 200, f"Update failed: {response.text}"
            
            # Verify update by fetching
            get_resp = requests.get(
                f"{BASE_URL}/api/vault/credentials/{cred_id}",
                headers=admin_headers
            )
            assert get_resp.status_code == 200
            
            updated_cred = get_resp.json()
            assert updated_cred.get("device_name") == update_data["device_name"]
            assert updated_cred.get("username") == update_data["username"]
            assert updated_cred.get("password") == update_data["password"]
            assert updated_cred.get("notes") == update_data["notes"]
            
            print(f"✓ Update credential works correctly")
        finally:
            # Cleanup
            requests.delete(f"{BASE_URL}/api/vault/credentials/{cred_id}", headers=admin_headers)
    
    def test_delete_credential(self, admin_headers, test_credential_data):
        """DELETE /api/vault/credentials/{id} deletes the credential"""
        # Create credential
        create_resp = requests.post(
            f"{BASE_URL}/api/vault/credentials",
            headers=admin_headers,
            json=test_credential_data
        )
        assert create_resp.status_code == 200
        cred_id = create_resp.json()["id"]
        
        # Delete credential
        response = requests.delete(
            f"{BASE_URL}/api/vault/credentials/{cred_id}",
            headers=admin_headers
        )
        assert response.status_code == 200, f"Delete failed: {response.text}"
        
        # Verify deletion
        get_resp = requests.get(
            f"{BASE_URL}/api/vault/credentials/{cred_id}",
            headers=admin_headers
        )
        assert get_resp.status_code == 404, "Deleted credential should return 404"
        
        print(f"✓ Delete credential works correctly")
    
    def test_get_nonexistent_credential_returns_404(self, admin_headers):
        """GET /api/vault/credentials/{id} returns 404 for non-existent credential"""
        fake_id = str(uuid.uuid4())
        response = requests.get(
            f"{BASE_URL}/api/vault/credentials/{fake_id}",
            headers=admin_headers
        )
        assert response.status_code == 404
        print("✓ Non-existent credential returns 404")
    
    def test_delete_nonexistent_credential_returns_404(self, admin_headers):
        """DELETE /api/vault/credentials/{id} returns 404 for non-existent credential"""
        fake_id = str(uuid.uuid4())
        response = requests.delete(
            f"{BASE_URL}/api/vault/credentials/{fake_id}",
            headers=admin_headers
        )
        assert response.status_code == 404
        print("✓ Delete non-existent credential returns 404")


class TestVaultAccessControl:
    """Test access control - only admin can access vault"""
    
    @pytest.fixture(scope="class")
    def operator_token(self):
        """Create or get operator user token"""
        # Try to login as existing operator
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": "operator@test.com",
            "password": "operator123"
        })
        if response.status_code == 200:
            return response.json().get("token")
        
        # If operator doesn't exist, we'll skip these tests
        pytest.skip("Operator user not available for testing")
    
    @pytest.fixture(scope="class")
    def operator_headers(self, operator_token):
        """Headers with operator auth token"""
        return {
            "Authorization": f"Bearer {operator_token}",
            "Content-Type": "application/json"
        }
    
    def test_non_admin_cannot_list_credentials(self, operator_headers):
        """Non-admin user gets 403 on GET /api/vault/credentials"""
        response = requests.get(
            f"{BASE_URL}/api/vault/credentials",
            headers=operator_headers
        )
        assert response.status_code == 403, f"Expected 403, got {response.status_code}"
        print("✓ Non-admin cannot list vault credentials (403)")
    
    def test_non_admin_cannot_create_credential(self, operator_headers):
        """Non-admin user gets 403 on POST /api/vault/credentials"""
        response = requests.post(
            f"{BASE_URL}/api/vault/credentials",
            headers=operator_headers,
            json={
                "credential_type": "ssh",
                "username": "test",
                "password": "test123"
            }
        )
        assert response.status_code == 403, f"Expected 403, got {response.status_code}"
        print("✓ Non-admin cannot create vault credentials (403)")
    
    def test_non_admin_cannot_get_credential(self, operator_headers):
        """Non-admin user gets 403 on GET /api/vault/credentials/{id}"""
        fake_id = str(uuid.uuid4())
        response = requests.get(
            f"{BASE_URL}/api/vault/credentials/{fake_id}",
            headers=operator_headers
        )
        assert response.status_code == 403, f"Expected 403, got {response.status_code}"
        print("✓ Non-admin cannot get vault credential (403)")
    
    def test_non_admin_cannot_update_credential(self, operator_headers):
        """Non-admin user gets 403 on PUT /api/vault/credentials/{id}"""
        fake_id = str(uuid.uuid4())
        response = requests.put(
            f"{BASE_URL}/api/vault/credentials/{fake_id}",
            headers=operator_headers,
            json={"notes": "test"}
        )
        assert response.status_code == 403, f"Expected 403, got {response.status_code}"
        print("✓ Non-admin cannot update vault credential (403)")
    
    def test_non_admin_cannot_delete_credential(self, operator_headers):
        """Non-admin user gets 403 on DELETE /api/vault/credentials/{id}"""
        fake_id = str(uuid.uuid4())
        response = requests.delete(
            f"{BASE_URL}/api/vault/credentials/{fake_id}",
            headers=operator_headers
        )
        assert response.status_code == 403, f"Expected 403, got {response.status_code}"
        print("✓ Non-admin cannot delete vault credential (403)")


class TestVaultCredentialTypes:
    """Test different credential types (ilo, ssh, snmp, web, vpn)"""
    
    @pytest.fixture(scope="class")
    def admin_headers(self):
        """Get admin authentication headers"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200
        token = response.json().get("token")
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    
    @pytest.mark.parametrize("cred_type", ["ilo", "ssh", "snmp", "web", "vpn", "other"])
    def test_create_credential_type(self, admin_headers, cred_type):
        """Test creating credentials of each type"""
        unique_id = str(uuid.uuid4())[:8]
        cred_data = {
            "device_ip": f"10.0.0.{hash(cred_type) % 255}",
            "device_name": f"{TEST_PREFIX}{cred_type.upper()}_Device_{unique_id}",
            "credential_type": cred_type,
            "username": f"{cred_type}_user",
            "password": f"{cred_type}_pass123!",
            "tags": [cred_type, "test"]
        }
        
        response = requests.post(
            f"{BASE_URL}/api/vault/credentials",
            headers=admin_headers,
            json=cred_data
        )
        assert response.status_code == 200, f"Create {cred_type} credential failed: {response.text}"
        cred_id = response.json()["id"]
        
        # Verify type is stored correctly
        get_resp = requests.get(
            f"{BASE_URL}/api/vault/credentials/{cred_id}",
            headers=admin_headers
        )
        assert get_resp.status_code == 200
        assert get_resp.json().get("credential_type") == cred_type
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/vault/credentials/{cred_id}", headers=admin_headers)
        
        print(f"✓ Credential type '{cred_type}' works correctly")


class TestExistingVaultCredentials:
    """Test existing vault credentials mentioned in context"""
    
    @pytest.fixture(scope="class")
    def admin_headers(self):
        """Get admin authentication headers"""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        assert response.status_code == 200
        token = response.json().get("token")
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    
    def test_list_existing_credentials(self, admin_headers):
        """Verify existing credentials are listed"""
        response = requests.get(f"{BASE_URL}/api/vault/credentials", headers=admin_headers)
        assert response.status_code == 200
        
        credentials = response.json()
        print(f"✓ Found {len(credentials)} credentials in vault")
        
        # Print credential info for debugging
        for cred in credentials:
            print(f"  - {cred.get('device_name', 'N/A')} ({cred.get('credential_type', 'N/A')}) - {cred.get('device_ip', 'N/A')}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
