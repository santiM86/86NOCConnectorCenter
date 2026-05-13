import requests
import sys
import json
from datetime import datetime
import uuid

class NOCAPITester:
    def __init__(self, base_url="https://device-poller-ws.preview.emergentagent.com"):
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
        self.test_alert_id = None

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

    def test_health_check(self):
        """Test basic health endpoints"""
        print("\n🔍 Testing Health Endpoints...")
        self.run_test("Health Check", "GET", "health", 200)
        self.run_test("Root Endpoint", "GET", "", 200)

    def test_user_registration(self):
        """Test user registration"""
        print("\n🔍 Testing User Registration...")
        
        # Generate unique test user
        timestamp = datetime.now().strftime("%H%M%S")
        test_email = f"test_user_{timestamp}@noctest.com"
        test_password = "TestPass123!"
        test_name = f"Test User {timestamp}"
        
        response = self.run_test(
            "User Registration",
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
            return True
        return False

    def test_user_login(self):
        """Test user login with existing credentials"""
        print("\n🔍 Testing User Login...")
        
        if not self.token:
            print("   ⚠️  Skipping login test - no token from registration")
            return False
            
        # Test getting current user info
        response = self.run_test("Get Current User", "GET", "auth/me", 200)
        
        if response:
            print(f"   📝 Current user: {response.get('email', 'Unknown')}")
            return True
        return False

    def test_client_management(self):
        """Test client CRUD operations"""
        print("\n🔍 Testing Client Management...")
        
        if not self.token:
            print("   ⚠️  Skipping client tests - no authentication")
            return False
        
        # Create client
        client_data = {
            "name": f"Test Client {datetime.now().strftime('%H%M%S')}",
            "description": "Test client for NOC system testing",
            "contact_email": "admin@testclient.com"
        }
        
        response = self.run_test("Create Client", "POST", "clients", 200, client_data)
        
        if response and 'id' in response:
            self.test_client_id = response['id']
            print(f"   📝 Created client: {response['name']} (ID: {self.test_client_id[:8]})")
            
            # Get clients list
            clients_response = self.run_test("Get Clients List", "GET", "clients", 200)
            
            if clients_response:
                print(f"   📝 Found {len(clients_response)} clients")
            
            # Get specific client
            self.run_test("Get Specific Client", "GET", f"clients/{self.test_client_id}", 200)
            
            return True
        return False

    def test_device_management(self):
        """Test device CRUD operations"""
        print("\n🔍 Testing Device Management...")
        
        if not self.token or not self.test_client_id:
            print("   ⚠️  Skipping device tests - missing client or authentication")
            return False
        
        # Create device
        device_data = {
            "client_id": self.test_client_id,
            "name": f"TEST-SW-{datetime.now().strftime('%H%M%S')}",
            "device_type": "switch",
            "ip_address": "192.168.1.100",
            "hostname": "test-switch.local",
            "location": "Test Rack A1"
        }
        
        response = self.run_test("Create Device", "POST", "devices", 200, device_data)
        
        if response and 'id' in response:
            self.test_device_id = response['id']
            print(f"   📝 Created device: {response['name']} (ID: {self.test_device_id[:8]})")
            
            # Get devices list
            devices_response = self.run_test("Get Devices List", "GET", "devices", 200)
            
            if devices_response:
                print(f"   📝 Found {len(devices_response)} devices")
            
            # Get specific device
            self.run_test("Get Specific Device", "GET", f"devices/{self.test_device_id}", 200)
            
            return True
        return False

    def test_alert_management(self):
        """Test alert CRUD operations"""
        print("\n🔍 Testing Alert Management...")
        
        if not self.token or not self.test_client_id or not self.test_device_id:
            print("   ⚠️  Skipping alert tests - missing dependencies")
            return False
        
        # Create alert
        alert_data = {
            "client_id": self.test_client_id,
            "device_id": self.test_device_id,
            "severity": "high",
            "source_type": "api",
            "title": "Test Alert - High Priority",
            "message": "This is a test alert generated by automated testing",
            "raw_data": json.dumps({"test": True, "timestamp": datetime.now().isoformat()})
        }
        
        response = self.run_test("Create Alert", "POST", "alerts", 200, alert_data)
        
        if response and 'id' in response:
            self.test_alert_id = response['id']
            print(f"   📝 Created alert: {response['title']} (ID: {self.test_alert_id[:8]})")
            
            # Get alerts list
            alerts_response = self.run_test("Get Alerts List", "GET", "alerts", 200)
            
            if alerts_response:
                print(f"   📝 Found {len(alerts_response)} alerts")
            
            # Get specific alert
            self.run_test("Get Specific Alert", "GET", f"alerts/{self.test_alert_id}", 200)
            
            # Test alert filtering
            self.run_test("Filter Alerts by Severity", "GET", "alerts?severity=high", 200)
            self.run_test("Filter Alerts by Status", "GET", "alerts?status=active", 200)
            self.run_test("Filter Alerts by Client", "GET", f"alerts?client_id={self.test_client_id}", 200)
            
            # Test alert acknowledgment
            ack_response = self.run_test(
                "Acknowledge Alert", 
                "PATCH", 
                f"alerts/{self.test_alert_id}", 
                200,
                {"status": "acknowledged"}
            )
            
            # Test alert resolution
            resolve_response = self.run_test(
                "Resolve Alert", 
                "PATCH", 
                f"alerts/{self.test_alert_id}", 
                200,
                {"status": "resolved"}
            )
            
            return True
        return False

    def test_stats_endpoints(self):
        """Test statistics endpoints"""
        print("\n🔍 Testing Statistics Endpoints...")
        
        if not self.token:
            print("   ⚠️  Skipping stats tests - no authentication")
            return False
        
        # Test summary stats
        summary_response = self.run_test("Get Stats Summary", "GET", "stats/summary", 200)
        
        if summary_response:
            print(f"   📊 Active alerts: {summary_response.get('total_active', 0)}")
            print(f"   📊 Total clients: {summary_response.get('total_clients', 0)}")
            print(f"   📊 Total devices: {summary_response.get('total_devices', 0)}")
        
        # Test trends
        trends_response = self.run_test("Get Alert Trends", "GET", "stats/trends?hours=24", 200)
        
        if trends_response:
            print(f"   📈 Trend data points: {len(trends_response)}")
        
        return True

    def test_ingestion_endpoints(self):
        """Test SNMP and Syslog ingestion endpoints"""
        print("\n🔍 Testing Ingestion Endpoints...")
        
        if not self.test_client_id:
            print("   ⚠️  Skipping ingestion tests - no test client")
            return False
        
        # Test Syslog ingestion
        syslog_data = {
            "client_id": self.test_client_id,
            "device_ip": "192.168.1.200",
            "facility": 16,
            "severity_level": 3,
            "message": "Test syslog message from automated testing",
            "timestamp": datetime.now().isoformat()
        }
        
        syslog_response = self.run_test("Syslog Ingestion", "POST", "ingest/syslog", 200, syslog_data)
        
        if syslog_response:
            print(f"   📝 Syslog alert created: {syslog_response.get('alert_id', 'Unknown')[:8]}")
        
        # Test SNMP ingestion
        snmp_data = {
            "client_id": self.test_client_id,
            "device_ip": "192.168.1.201",
            "oid": "1.3.6.1.2.1.2.2.1.8.1",
            "value": "down",
            "trap_type": "linkDown"
        }
        
        snmp_response = self.run_test("SNMP Ingestion", "POST", "ingest/snmp", 200, snmp_data)
        
        if snmp_response:
            print(f"   📝 SNMP alert created: {snmp_response.get('alert_id', 'Unknown')[:8]}")
        
        return True

    def cleanup_test_data(self):
        """Clean up test data"""
        print("\n🧹 Cleaning up test data...")
        
        if self.test_client_id:
            self.run_test("Delete Test Client", "DELETE", f"clients/{self.test_client_id}", 200)
        
        if self.test_device_id:
            self.run_test("Delete Test Device", "DELETE", f"devices/{self.test_device_id}", 200)

    def run_all_tests(self):
        """Run all backend tests"""
        print("🚀 Starting NOC Alert Command Center Backend Tests")
        print(f"🌐 Testing against: {self.base_url}")
        print("=" * 60)
        
        # Run tests in sequence
        self.test_health_check()
        
        if self.test_user_registration():
            self.test_user_login()
            
            if self.test_client_management():
                if self.test_device_management():
                    self.test_alert_management()
                    self.test_ingestion_endpoints()
            
            self.test_stats_endpoints()
            
            # Cleanup
            self.cleanup_test_data()
        
        # Print summary
        print("\n" + "=" * 60)
        print(f"📊 Test Summary: {self.tests_passed}/{self.tests_run} tests passed")
        
        if self.tests_passed == self.tests_run:
            print("🎉 All backend tests passed!")
            return 0
        else:
            print(f"⚠️  {self.tests_run - self.tests_passed} tests failed")
            return 1

def main():
    tester = NOCAPITester()
    return tester.run_all_tests()

if __name__ == "__main__":
    sys.exit(main())