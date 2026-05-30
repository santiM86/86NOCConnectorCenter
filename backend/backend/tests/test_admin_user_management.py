"""
Backend API tests for NOC Alert Command Center - Admin User Management
Tests: Admin user CRUD, Role management, 2FA management, Access control
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
ADMIN_EMAIL = "admin@86bit.it"
ADMIN_PASSWORD = "admin123"
NON_ADMIN_EMAIL = "viewer@test.it"
NON_ADMIN_PASSWORD = "password123"


class TestAdminAuthentication:
    """Test admin authentication and access control"""
    
    def test_admin_login(self):
        """Test admin user can login successfully"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
        )
        assert response.status_code == 200, f"Admin login failed: {response.text}"
        data = response.json()
        assert "token" in data
        assert "user" in data
        assert data["user"]["email"] == ADMIN_EMAIL
        assert data["user"]["role"] == "admin"
        print(f"✓ Admin login successful - role: {data['user']['role']}")
    
    def test_non_admin_login(self):
        """Test non-admin user can login but has limited access"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": NON_ADMIN_EMAIL, "password": NON_ADMIN_PASSWORD}
        )
        # Non-admin user may not exist yet, so we just check the response
        if response.status_code == 200:
            data = response.json()
            assert data["user"]["role"] != "admin"
            print(f"✓ Non-admin login successful - role: {data['user']['role']}")
        else:
            print(f"⚠ Non-admin user doesn't exist yet (expected for fresh setup)")


class TestAdminUserListEndpoint:
    """Test GET /api/admin/users endpoint"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Login as admin and get auth token"""
        login_response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
        )
        assert login_response.status_code == 200, f"Admin login failed: {login_response.text}"
        self.token = login_response.json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_list_users_as_admin(self):
        """Test admin can list all users"""
        response = requests.get(f"{BASE_URL}/api/admin/users", headers=self.headers)
        assert response.status_code == 200, f"List users failed: {response.text}"
        data = response.json()
        assert isinstance(data, list)
        
        # Check user structure
        if data:
            user = data[0]
            expected_fields = ["id", "email", "name", "role"]
            for field in expected_fields:
                assert field in user, f"Missing field: {field}"
            # Ensure sensitive fields are not exposed
            assert "password_hash" not in user, "password_hash should not be in response"
            assert "totp_secret" not in user, "totp_secret should not be in response"
        
        print(f"✓ Admin can list users - found {len(data)} users")
    
    def test_list_users_as_non_admin_forbidden(self):
        """Test non-admin cannot list users (403 Forbidden)"""
        # First try to login as non-admin
        login_response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": NON_ADMIN_EMAIL, "password": NON_ADMIN_PASSWORD}
        )
        
        if login_response.status_code != 200:
            pytest.skip("Non-admin user doesn't exist - skipping access control test")
        
        non_admin_token = login_response.json()["token"]
        non_admin_headers = {"Authorization": f"Bearer {non_admin_token}"}
        
        response = requests.get(f"{BASE_URL}/api/admin/users", headers=non_admin_headers)
        assert response.status_code == 403, f"Expected 403, got {response.status_code}"
        print("✓ Non-admin correctly denied access to user list (403)")


class TestAdminUserCRUD:
    """Test admin user CRUD operations"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Login as admin and get auth token"""
        login_response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
        )
        assert login_response.status_code == 200, f"Admin login failed: {login_response.text}"
        self.token = login_response.json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.created_user_ids = []
    
    def teardown_method(self, method):
        """Cleanup created test users"""
        for user_id in self.created_user_ids:
            try:
                requests.delete(f"{BASE_URL}/api/admin/users/{user_id}", headers=self.headers)
            except:
                pass
    
    def test_create_user_with_operator_role(self):
        """Test admin can create a new user with operator role"""
        unique_email = f"TEST_operator_{uuid.uuid4().hex[:8]}@test.it"
        user_data = {
            "email": unique_email,
            "password": "TestPassword123!",
            "name": "Test Operator",
            "role": "operator"
        }
        
        response = requests.post(f"{BASE_URL}/api/admin/users", json=user_data, headers=self.headers)
        assert response.status_code == 200, f"Create user failed: {response.text}"
        
        data = response.json()
        assert data["email"] == unique_email
        assert data["name"] == "Test Operator"
        assert data["role"] == "operator"
        assert data["two_factor_enabled"] == False
        assert "id" in data
        
        self.created_user_ids.append(data["id"])
        print(f"✓ Created operator user: {unique_email}")
    
    def test_create_user_with_viewer_role(self):
        """Test admin can create a new user with viewer role"""
        unique_email = f"TEST_viewer_{uuid.uuid4().hex[:8]}@test.it"
        user_data = {
            "email": unique_email,
            "password": "TestPassword123!",
            "name": "Test Viewer",
            "role": "viewer"
        }
        
        response = requests.post(f"{BASE_URL}/api/admin/users", json=user_data, headers=self.headers)
        assert response.status_code == 200, f"Create user failed: {response.text}"
        
        data = response.json()
        assert data["role"] == "viewer"
        
        self.created_user_ids.append(data["id"])
        print(f"✓ Created viewer user: {unique_email}")
    
    def test_create_user_with_admin_role(self):
        """Test admin can create a new user with admin role"""
        unique_email = f"TEST_admin_{uuid.uuid4().hex[:8]}@test.it"
        user_data = {
            "email": unique_email,
            "password": "TestPassword123!",
            "name": "Test Admin",
            "role": "admin"
        }
        
        response = requests.post(f"{BASE_URL}/api/admin/users", json=user_data, headers=self.headers)
        assert response.status_code == 200, f"Create user failed: {response.text}"
        
        data = response.json()
        assert data["role"] == "admin"
        
        self.created_user_ids.append(data["id"])
        print(f"✓ Created admin user: {unique_email}")
    
    def test_create_user_invalid_role(self):
        """Test creating user with invalid role fails"""
        unique_email = f"TEST_invalid_{uuid.uuid4().hex[:8]}@test.it"
        user_data = {
            "email": unique_email,
            "password": "TestPassword123!",
            "name": "Test Invalid",
            "role": "superadmin"  # Invalid role
        }
        
        response = requests.post(f"{BASE_URL}/api/admin/users", json=user_data, headers=self.headers)
        assert response.status_code == 400, f"Expected 400 for invalid role, got {response.status_code}"
        print("✓ Invalid role correctly rejected (400)")
    
    def test_create_user_duplicate_email(self):
        """Test creating user with duplicate email fails"""
        # Try to create user with existing admin email
        user_data = {
            "email": ADMIN_EMAIL,
            "password": "TestPassword123!",
            "name": "Duplicate Admin",
            "role": "operator"
        }
        
        response = requests.post(f"{BASE_URL}/api/admin/users", json=user_data, headers=self.headers)
        assert response.status_code == 400, f"Expected 400 for duplicate email, got {response.status_code}"
        print("✓ Duplicate email correctly rejected (400)")
    
    def test_update_user_role(self):
        """Test admin can update user role"""
        # First create a user
        unique_email = f"TEST_update_{uuid.uuid4().hex[:8]}@test.it"
        create_response = requests.post(
            f"{BASE_URL}/api/admin/users",
            json={"email": unique_email, "password": "TestPassword123!", "name": "Test Update", "role": "viewer"},
            headers=self.headers
        )
        assert create_response.status_code == 200
        user_id = create_response.json()["id"]
        self.created_user_ids.append(user_id)
        
        # Update role to operator
        update_response = requests.put(
            f"{BASE_URL}/api/admin/users/{user_id}",
            json={"role": "operator"},
            headers=self.headers
        )
        assert update_response.status_code == 200, f"Update failed: {update_response.text}"
        
        data = update_response.json()
        assert data["role"] == "operator"
        print(f"✓ Updated user role from viewer to operator")
    
    def test_update_user_name(self):
        """Test admin can update user name"""
        # First create a user
        unique_email = f"TEST_name_{uuid.uuid4().hex[:8]}@test.it"
        create_response = requests.post(
            f"{BASE_URL}/api/admin/users",
            json={"email": unique_email, "password": "TestPassword123!", "name": "Original Name", "role": "viewer"},
            headers=self.headers
        )
        assert create_response.status_code == 200
        user_id = create_response.json()["id"]
        self.created_user_ids.append(user_id)
        
        # Update name
        update_response = requests.put(
            f"{BASE_URL}/api/admin/users/{user_id}",
            json={"name": "Updated Name"},
            headers=self.headers
        )
        assert update_response.status_code == 200, f"Update failed: {update_response.text}"
        
        data = update_response.json()
        assert data["name"] == "Updated Name"
        print(f"✓ Updated user name successfully")
    
    def test_delete_user(self):
        """Test admin can delete a user"""
        # First create a user
        unique_email = f"TEST_delete_{uuid.uuid4().hex[:8]}@test.it"
        create_response = requests.post(
            f"{BASE_URL}/api/admin/users",
            json={"email": unique_email, "password": "TestPassword123!", "name": "Test Delete", "role": "viewer"},
            headers=self.headers
        )
        assert create_response.status_code == 200
        user_id = create_response.json()["id"]
        
        # Delete user
        delete_response = requests.delete(f"{BASE_URL}/api/admin/users/{user_id}", headers=self.headers)
        assert delete_response.status_code == 200, f"Delete failed: {delete_response.text}"
        
        data = delete_response.json()
        assert data["deleted"] == True
        
        # Verify user is deleted by trying to update
        verify_response = requests.put(
            f"{BASE_URL}/api/admin/users/{user_id}",
            json={"name": "Should Fail"},
            headers=self.headers
        )
        assert verify_response.status_code == 404
        print(f"✓ Deleted user and verified removal")
    
    def test_delete_nonexistent_user(self):
        """Test deleting non-existent user returns 404"""
        fake_id = str(uuid.uuid4())
        response = requests.delete(f"{BASE_URL}/api/admin/users/{fake_id}", headers=self.headers)
        assert response.status_code == 404
        print("✓ Delete non-existent user correctly returns 404")


class TestAdmin2FAManagement:
    """Test admin 2FA management endpoints"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Login as admin and get auth token"""
        login_response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
        )
        assert login_response.status_code == 200, f"Admin login failed: {login_response.text}"
        self.token = login_response.json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.created_user_ids = []
    
    def teardown_method(self, method):
        """Cleanup created test users"""
        for user_id in self.created_user_ids:
            try:
                requests.delete(f"{BASE_URL}/api/admin/users/{user_id}", headers=self.headers)
            except:
                pass
    
    def test_reset_2fa_for_user(self):
        """Test admin can reset 2FA for a user"""
        # First create a user
        unique_email = f"TEST_2fa_reset_{uuid.uuid4().hex[:8]}@test.it"
        create_response = requests.post(
            f"{BASE_URL}/api/admin/users",
            json={"email": unique_email, "password": "TestPassword123!", "name": "Test 2FA Reset", "role": "operator"},
            headers=self.headers
        )
        assert create_response.status_code == 200
        user_id = create_response.json()["id"]
        self.created_user_ids.append(user_id)
        
        # Reset 2FA
        reset_response = requests.post(f"{BASE_URL}/api/admin/users/{user_id}/reset-2fa", headers=self.headers)
        assert reset_response.status_code == 200, f"Reset 2FA failed: {reset_response.text}"
        
        data = reset_response.json()
        assert data["reset"] == True
        print(f"✓ Reset 2FA for user successfully")
    
    def test_force_setup_2fa_returns_qr_code(self):
        """Test admin can generate 2FA QR code for a user"""
        # First create a user
        unique_email = f"TEST_2fa_setup_{uuid.uuid4().hex[:8]}@test.it"
        create_response = requests.post(
            f"{BASE_URL}/api/admin/users",
            json={"email": unique_email, "password": "TestPassword123!", "name": "Test 2FA Setup", "role": "operator"},
            headers=self.headers
        )
        assert create_response.status_code == 200
        user_id = create_response.json()["id"]
        self.created_user_ids.append(user_id)
        
        # Force 2FA setup
        setup_response = requests.post(f"{BASE_URL}/api/admin/users/{user_id}/force-2fa", headers=self.headers)
        assert setup_response.status_code == 200, f"Force 2FA setup failed: {setup_response.text}"
        
        data = setup_response.json()
        assert "secret" in data, "Response should contain TOTP secret"
        assert "qr_code" in data, "Response should contain QR code"
        assert "uri" in data, "Response should contain TOTP URI"
        assert "user_email" in data, "Response should contain user email"
        assert data["user_email"] == unique_email
        
        # Verify QR code is base64 encoded PNG
        assert len(data["qr_code"]) > 100, "QR code should be a valid base64 string"
        print(f"✓ Generated 2FA QR code for user - secret length: {len(data['secret'])}")
    
    def test_confirm_2fa_with_invalid_code(self):
        """Test confirming 2FA with invalid code fails"""
        # First create a user and setup 2FA
        unique_email = f"TEST_2fa_confirm_{uuid.uuid4().hex[:8]}@test.it"
        create_response = requests.post(
            f"{BASE_URL}/api/admin/users",
            json={"email": unique_email, "password": "TestPassword123!", "name": "Test 2FA Confirm", "role": "operator"},
            headers=self.headers
        )
        assert create_response.status_code == 200
        user_id = create_response.json()["id"]
        self.created_user_ids.append(user_id)
        
        # Force 2FA setup
        setup_response = requests.post(f"{BASE_URL}/api/admin/users/{user_id}/force-2fa", headers=self.headers)
        assert setup_response.status_code == 200
        
        # Try to confirm with invalid code
        confirm_response = requests.post(
            f"{BASE_URL}/api/admin/users/{user_id}/confirm-2fa",
            json={"code": "000000"},  # Invalid code
            headers=self.headers
        )
        assert confirm_response.status_code == 401, f"Expected 401 for invalid code, got {confirm_response.status_code}"
        print("✓ Invalid 2FA code correctly rejected (401)")
    
    def test_confirm_2fa_without_setup(self):
        """Test confirming 2FA without setup fails"""
        # First create a user (no 2FA setup)
        unique_email = f"TEST_2fa_no_setup_{uuid.uuid4().hex[:8]}@test.it"
        create_response = requests.post(
            f"{BASE_URL}/api/admin/users",
            json={"email": unique_email, "password": "TestPassword123!", "name": "Test No Setup", "role": "operator"},
            headers=self.headers
        )
        assert create_response.status_code == 200
        user_id = create_response.json()["id"]
        self.created_user_ids.append(user_id)
        
        # Try to confirm without setup
        confirm_response = requests.post(
            f"{BASE_URL}/api/admin/users/{user_id}/confirm-2fa",
            json={"code": "123456"},
            headers=self.headers
        )
        assert confirm_response.status_code == 400, f"Expected 400 for no setup, got {confirm_response.status_code}"
        print("✓ Confirm 2FA without setup correctly rejected (400)")


class TestAccessControl:
    """Test access control for admin endpoints"""
    
    def test_unauthenticated_access_denied(self):
        """Test unauthenticated requests are denied"""
        response = requests.get(f"{BASE_URL}/api/admin/users")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("✓ Unauthenticated access correctly denied")
    
    def test_non_admin_create_user_forbidden(self):
        """Test non-admin cannot create users"""
        # First login as admin to create a non-admin user
        admin_login = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
        )
        assert admin_login.status_code == 200
        admin_token = admin_login.json()["token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        
        # Create a viewer user
        unique_email = f"TEST_viewer_access_{uuid.uuid4().hex[:8]}@test.it"
        create_response = requests.post(
            f"{BASE_URL}/api/admin/users",
            json={"email": unique_email, "password": "TestPassword123!", "name": "Test Viewer Access", "role": "viewer"},
            headers=admin_headers
        )
        
        if create_response.status_code != 200:
            pytest.skip("Could not create test viewer user")
        
        user_id = create_response.json()["id"]
        
        try:
            # Login as the viewer
            viewer_login = requests.post(
                f"{BASE_URL}/api/auth/login",
                json={"email": unique_email, "password": "TestPassword123!"}
            )
            assert viewer_login.status_code == 200
            viewer_token = viewer_login.json()["token"]
            viewer_headers = {"Authorization": f"Bearer {viewer_token}"}
            
            # Try to create a user as viewer
            create_as_viewer = requests.post(
                f"{BASE_URL}/api/admin/users",
                json={"email": "should_fail@test.it", "password": "TestPassword123!", "name": "Should Fail", "role": "viewer"},
                headers=viewer_headers
            )
            assert create_as_viewer.status_code == 403, f"Expected 403, got {create_as_viewer.status_code}"
            print("✓ Non-admin correctly denied user creation (403)")
        finally:
            # Cleanup
            requests.delete(f"{BASE_URL}/api/admin/users/{user_id}", headers=admin_headers)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
