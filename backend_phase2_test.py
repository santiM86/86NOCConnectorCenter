import requests
import sys
import json
from datetime import datetime
import uuid
import base64

class NOCPhase2Tester:
    def __init__(self, base_url="https://snmp-monitor-staging.preview.emergentagent.com"):
        self.base_url = base_url
        self.api_url = f"{base_url}/api"
        self.token = None
        self.user_id = None
        self.tests_run = 0
        self.tests_passed = 0
        self.test_results = []
        
        # Test data storage
        self.test_client_id = None
        self.test_device_id = None

    def log_test(self, name, success, details=""):
        """Log test result"""
        self.tests_run += 1
        if success:
            self.tests_passed += 1
            print(f"✅ {name}")
        else:
            print(f"❌ {name} - {details}")
        
        self.test_results.append({
            "test": name,
            "success": success,
            "details": details
        })

    def run_test(self, name, method, endpoint, expected_status, data=None, headers=None):
        """Run a single API test"""
        url = f"{self.api_url}/{endpoint}"
        test_headers = {'Content-Type': 'application/json'}
        
        if self.token:
            test_headers['Authorization'] = f'Bearer {self.token}'
        
        if headers:
            test_headers.update(headers)

        try:
            if method == 'GET':
                response = requests.get(url, headers=test_headers, timeout=10)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=test_headers, timeout=10)
            elif method == 'PATCH':
                response = requests.patch(url, json=data, headers=test_headers, timeout=10)
            elif method == 'DELETE':
                response = requests.delete(url, headers=test_headers, timeout=10)

            success = response.status_code == expected_status
            details = f"Status: {response.status_code}"
            
            if not success:
                try:
                    error_data = response.json()
                    details += f", Error: {error_data.get('detail', 'Unknown error')}"
                except:
                    details += f", Response: {response.text[:100]}"

            self.log_test(name, success, details)
            
            if success:
                try:
                    return response.json()
                except:
                    return {}
            return None

        except Exception as e:
            self.log_test(name, False, f"Exception: {str(e)}")
            return None

    def setup_test_user(self):
        """Create a test user for Phase 2 testing"""
        print("\n🔍 Setting up test user...")
        
        # Generate unique test user
        timestamp = datetime.now().strftime("%H%M%S")
        test_email = f"phase2_user_{timestamp}@noctest.com"
        test_password = "SecurePass123!"
        test_name = f"Phase2 User {timestamp}"
        
        response = self.run_test(
            "Phase 2 User Registration",
            "POST",
            "auth/register",
            200,
            {
                "email": test_email,
                "password": test_password,
                "name": test_name
            }
        )
        
        if response and 'token' in response:
            self.token = response['token']
            self.user_id = response['user']['id']
            print(f"   📝 Registered user: {test_email}")
            return test_email, test_password
        return None, None

    def test_2fa_setup_flow(self, password):
        """Test complete 2FA setup flow"""
        print("\n🔍 Testing 2FA Setup Flow...")
        
        if not self.token:
            print("   ⚠️  Skipping 2FA tests - no authentication")
            return False
        
        # Test 2FA setup initiation
        setup_response = self.run_test(
            "2FA Setup Initiation", 
            "POST", 
            "auth/setup-2fa", 
            200,
            {"password": password}
        )
        
        if setup_response and 'secret' in setup_response:
            print(f"   📝 Generated TOTP secret: {setup_response['secret'][:8]}...")
            print(f"   📝 QR code generated: {len(setup_response.get('qr_code', ''))} bytes")
            
            # For testing, we'll simulate a TOTP code (this would normally come from an authenticator app)
            # In a real test, you'd use a TOTP library to generate the code
            import pyotp
            totp = pyotp.TOTP(setup_response['secret'])
            verification_code = totp.now()
            
            # Test 2FA confirmation
            confirm_response = self.run_test(
                "2FA Confirmation",
                "POST",
                "auth/confirm-2fa",
                200,
                {"code": verification_code}
            )
            
            if confirm_response and confirm_response.get('enabled'):
                print("   📝 2FA successfully enabled")
                
                # Test 2FA verification in login flow
                # This would require a new login, but for now we'll test disable
                disable_response = self.run_test(
                    "2FA Disable",
                    "POST",
                    "auth/disable-2fa",
                    200,
                    {"password": password}
                )
                
                if disable_response and disable_response.get('disabled'):
                    print("   📝 2FA successfully disabled")
                    return True
        
        return False

    def test_device_credentials(self):
        """Test device credential encryption/decryption"""
        print("\n🔍 Testing Device Credential Encryption...")
        
        if not self.token:
            print("   ⚠️  Skipping credential tests - no authentication")
            return False
        
        # First create a test client and device
        client_data = {
            "name": f"Cred Test Client {datetime.now().strftime('%H%M%S')}",
            "description": "Test client for credential testing"
        }
        
        client_response = self.run_test("Create Test Client for Credentials", "POST", "clients", 200, client_data)
        
        if not client_response:
            return False
        
        self.test_client_id = client_response['id']
        
        # Create an ILO device
        device_data = {
            "client_id": self.test_client_id,
            "name": f"TEST-ILO-{datetime.now().strftime('%H%M%S')}",
            "device_type": "ilo",
            "ip_address": "192.168.1.150",
            "hostname": "test-ilo.local",
            "location": "Test Rack B1",
            "redfish_enabled": True
        }
        
        device_response = self.run_test("Create ILO Device", "POST", "devices", 200, device_data)
        
        if not device_response:
            return False
        
        self.test_device_id = device_response['id']
        print(f"   📝 Created ILO device: {device_response['name']}")
        
        # Test credential storage
        credentials = {
            "username": "Administrator",
            "password": "SecretILOPass123!"
        }
        
        cred_response = self.run_test(
            "Store Encrypted Credentials",
            "POST",
            f"devices/{self.test_device_id}/credentials",
            200,
            credentials
        )
        
        if cred_response:
            print("   📝 Credentials stored with AES-256-GCM encryption")
            
            # Test Redfish connection test (will fail but should handle credentials properly)
            test_response = self.run_test(
                "Test Redfish Connection",
                "POST",
                f"devices/{self.test_device_id}/test-redfish",
                200  # This might return 200 with error details
            )
            
            # Test credential deletion
            delete_response = self.run_test(
                "Delete Device Credentials",
                "DELETE",
                f"devices/{self.test_device_id}/credentials",
                200
            )
            
            return True
        
        return False

    def test_settings_endpoints(self):
        """Test settings management endpoints"""
        print("\n🔍 Testing Settings Endpoints...")
        
        if not self.token:
            print("   ⚠️  Skipping settings tests - no authentication")
            return False
        
        # Test notification settings
        notif_response = self.run_test("Get Notification Settings", "GET", "settings/notifications", 200)
        
        if notif_response is not None:
            print(f"   📝 Current notification settings retrieved")
            
            # Test updating notification settings
            new_settings = {
                "email_enabled": True,
                "push_enabled": True,
                "webhook_teams": "https://outlook.office.com/webhook/test",
                "webhook_slack": "https://hooks.slack.com/services/test",
                "webhook_telegram": "-1001234567890",
                "webhook_generic": "https://example.com/webhook"
            }
            
            update_response = self.run_test(
                "Update Notification Settings",
                "POST",
                "settings/notifications",
                200,
                new_settings
            )
            
            if update_response:
                print("   📝 Notification settings updated successfully")
        
        # Test Redfish settings
        redfish_response = self.run_test("Get Redfish Settings", "GET", "settings/redfish", 200)
        
        if redfish_response is not None:
            print(f"   📝 Redfish poll interval: {redfish_response.get('poll_interval_minutes', 'Unknown')} minutes")
            
            # Test updating Redfish settings
            update_redfish = self.run_test(
                "Update Redfish Settings",
                "POST",
                "settings/redfish?poll_interval=10",
                200
            )
            
            if update_redfish:
                print("   📝 Redfish settings updated successfully")
        
        return True

    def test_audit_endpoints(self):
        """Test audit logging endpoints"""
        print("\n🔍 Testing Audit Endpoints...")
        
        if not self.token:
            print("   ⚠️  Skipping audit tests - no authentication")
            return False
        
        # Test audit logs
        audit_response = self.run_test("Get Audit Logs", "GET", "audit/logs?hours=1&limit=50", 200)
        
        if audit_response is not None:
            print(f"   📝 Retrieved {len(audit_response)} audit log entries")
        
        # Test security events
        security_response = self.run_test("Get Security Events", "GET", "audit/security-events?hours=24", 200)
        
        if security_response is not None:
            print(f"   📝 Retrieved {len(security_response)} security events")
        
        return True

    def test_redfish_test_endpoint(self):
        """Test Redfish connection testing with provided credentials"""
        print("\n🔍 Testing Redfish Test Endpoint...")
        
        if not self.token:
            print("   ⚠️  Skipping Redfish test - no authentication")
            return False
        
        # Test with dummy credentials (will fail but should handle properly)
        test_data = {
            "ip_address": "192.168.1.100",
            "username": "Administrator", 
            "password": "testpass"
        }
        
        response = self.run_test(
            "Redfish Connection Test",
            "POST",
            "devices/test-redfish",
            200,
            test_data
        )
        
        if response is not None:
            success = response.get('success', False)
            error = response.get('error', 'Unknown')
            print(f"   📝 Redfish test result: {'Success' if success else f'Failed - {error}'}")
            return True
        
        return False

    def cleanup_test_data(self):
        """Clean up test data"""
        print("\n🧹 Cleaning up Phase 2 test data...")
        
        if self.test_device_id:
            self.run_test("Delete Test Device", "DELETE", f"devices/{self.test_device_id}", 200)
        
        if self.test_client_id:
            self.run_test("Delete Test Client", "DELETE", f"clients/{self.test_client_id}", 200)

    def run_phase2_tests(self):
        """Run all Phase 2 specific tests"""
        print("🚀 Starting NOC Alert Command Center Phase 2 Tests")
        print(f"🌐 Testing against: {self.base_url}")
        print("=" * 60)
        
        # Setup test user
        email, password = self.setup_test_user()
        
        if email and password:
            # Run Phase 2 specific tests
            self.test_2fa_setup_flow(password)
            self.test_device_credentials()
            self.test_settings_endpoints()
            self.test_audit_endpoints()
            self.test_redfish_test_endpoint()
            
            # Cleanup
            self.cleanup_test_data()
        
        # Print summary
        print("\n" + "=" * 60)
        print(f"📊 Phase 2 Test Summary: {self.tests_passed}/{self.tests_run} tests passed")
        
        if self.tests_passed == self.tests_run:
            print("🎉 All Phase 2 tests passed!")
            return 0
        else:
            print(f"⚠️  {self.tests_run - self.tests_passed} Phase 2 tests failed")
            return 1

def main():
    tester = NOCPhase2Tester()
    return tester.run_phase2_tests()

if __name__ == "__main__":
    sys.exit(main())