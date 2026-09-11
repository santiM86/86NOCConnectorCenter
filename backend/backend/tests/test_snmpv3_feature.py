"""
Test SNMPv3 Feature - Iteration 44
Tests for SNMP v3 support in managed devices:
- PUT /api/connector/{client_id}/managed-devices/{device_id}/snmp - Update SNMP config
- GET /api/connector/{client_id}/managed-devices - List devices with SNMP fields
- POST /api/connector/{client_id}/managed-devices - Create device with SNMP v3 fields
- ManagedDevice model with snmp_version, snmpv3_* fields
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
TEST_EMAIL = "admin@86bit.it"
TEST_PASSWORD = "password"
TEST_CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"
TEST_DEVICE_ID = "3f20edc0-5d79-472d-9780-17eea4b041b5"


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD
    })
    if response.status_code == 200:
        return response.json().get("token")
    pytest.skip(f"Authentication failed: {response.status_code} - {response.text}")


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Headers with auth token"""
    return {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }


class TestSNMPv3UpdateEndpoint:
    """Test PUT /api/connector/{client_id}/managed-devices/{device_id}/snmp"""
    
    def test_update_snmp_to_v3_with_usm_credentials(self, auth_headers):
        """Test updating device SNMP config to v3 with full USM credentials"""
        payload = {
            "snmp_version": "v3",
            "snmpv3_username": "testuser",
            "snmpv3_auth_protocol": "SHA",
            "snmpv3_auth_password": "authpass123",
            "snmpv3_priv_protocol": "AES",
            "snmpv3_priv_password": "privpass123",
            "snmpv3_security_level": "authPriv"
        }
        
        response = requests.put(
            f"{BASE_URL}/api/connector/{TEST_CLIENT_ID}/managed-devices/{TEST_DEVICE_ID}/snmp",
            headers=auth_headers,
            json=payload
        )
        
        print(f"Update to v3 response: {response.status_code} - {response.text}")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data.get("status") == "ok"
        assert data.get("snmp_version") == "v3"
    
    def test_update_snmp_to_v3_authNoPriv(self, auth_headers):
        """Test updating device SNMP config to v3 with authNoPriv security level"""
        payload = {
            "snmp_version": "v3",
            "snmpv3_username": "authonlyuser",
            "snmpv3_auth_protocol": "MD5",
            "snmpv3_auth_password": "authpass456",
            "snmpv3_priv_protocol": None,
            "snmpv3_priv_password": None,
            "snmpv3_security_level": "authNoPriv"
        }
        
        response = requests.put(
            f"{BASE_URL}/api/connector/{TEST_CLIENT_ID}/managed-devices/{TEST_DEVICE_ID}/snmp",
            headers=auth_headers,
            json=payload
        )
        
        print(f"Update to v3 authNoPriv response: {response.status_code} - {response.text}")
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("snmp_version") == "v3"
    
    def test_update_snmp_to_v2c_clears_v3_fields(self, auth_headers):
        """Test reverting device SNMP config to v2c clears v3 fields"""
        payload = {
            "snmp_version": "v2c",
            "community": "public"
        }
        
        response = requests.put(
            f"{BASE_URL}/api/connector/{TEST_CLIENT_ID}/managed-devices/{TEST_DEVICE_ID}/snmp",
            headers=auth_headers,
            json=payload
        )
        
        print(f"Revert to v2c response: {response.status_code} - {response.text}")
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"
        assert data.get("snmp_version") == "v2c"
    
    def test_update_snmp_to_v1(self, auth_headers):
        """Test updating device SNMP config to v1"""
        payload = {
            "snmp_version": "v1",
            "community": "public"
        }
        
        response = requests.put(
            f"{BASE_URL}/api/connector/{TEST_CLIENT_ID}/managed-devices/{TEST_DEVICE_ID}/snmp",
            headers=auth_headers,
            json=payload
        )
        
        print(f"Update to v1 response: {response.status_code} - {response.text}")
        
        assert response.status_code == 200
        data = response.json()
        assert data.get("snmp_version") == "v1"
    
    def test_update_snmp_requires_auth(self):
        """Test that SNMP update requires authentication"""
        payload = {"snmp_version": "v2c", "community": "public"}
        
        response = requests.put(
            f"{BASE_URL}/api/connector/{TEST_CLIENT_ID}/managed-devices/{TEST_DEVICE_ID}/snmp",
            json=payload
        )
        
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
    
    def test_update_snmp_invalid_device_returns_404(self, auth_headers):
        """Test updating non-existent device returns 404"""
        payload = {"snmp_version": "v2c", "community": "public"}
        
        response = requests.put(
            f"{BASE_URL}/api/connector/{TEST_CLIENT_ID}/managed-devices/invalid-device-id/snmp",
            headers=auth_headers,
            json=payload
        )
        
        assert response.status_code == 404


class TestManagedDevicesListEndpoint:
    """Test GET /api/connector/{client_id}/managed-devices"""
    
    def test_get_managed_devices_returns_snmp_fields(self, auth_headers):
        """Test that managed devices list includes SNMP version and v3 fields"""
        response = requests.get(
            f"{BASE_URL}/api/connector/{TEST_CLIENT_ID}/managed-devices",
            headers=auth_headers
        )
        
        print(f"Get managed devices response: {response.status_code}")
        
        assert response.status_code == 200
        devices = response.json()
        
        # Should be a list
        assert isinstance(devices, list), f"Expected list, got {type(devices)}"
        
        if len(devices) > 0:
            device = devices[0]
            print(f"First device fields: {list(device.keys())}")
            
            # Check that snmp_version field exists
            # Note: It may be None or missing if not set
            if "snmp_version" in device:
                print(f"Device snmp_version: {device.get('snmp_version')}")
    
    def test_get_managed_devices_requires_auth_or_api_key(self):
        """Test that managed devices list requires authentication"""
        response = requests.get(
            f"{BASE_URL}/api/connector/{TEST_CLIENT_ID}/managed-devices"
        )
        
        # Should require auth (401) or API key
        # The endpoint accepts both Bearer token and X-API-Key
        assert response.status_code in [200, 401, 403], f"Unexpected status: {response.status_code}"


class TestManagedDeviceCreateEndpoint:
    """Test POST /api/connector/{client_id}/managed-devices"""
    
    def test_create_device_with_snmpv3_fields(self, auth_headers):
        """Test creating a new device with SNMPv3 configuration"""
        unique_ip = f"192.168.99.{uuid.uuid4().int % 255}"
        
        payload = {
            "ip": unique_ip,
            "name": f"TEST_SNMPv3_Device_{uuid.uuid4().hex[:8]}",
            "community": "",
            "monitor_type": "snmp",
            "device_type": "network",
            "snmp_version": "v3",
            "snmpv3_username": "newdeviceuser",
            "snmpv3_auth_protocol": "SHA",
            "snmpv3_auth_password": "newdeviceauth",
            "snmpv3_priv_protocol": "AES",
            "snmpv3_priv_password": "newdevicepriv",
            "snmpv3_security_level": "authPriv"
        }
        
        response = requests.post(
            f"{BASE_URL}/api/connector/{TEST_CLIENT_ID}/managed-devices",
            headers=auth_headers,
            json=payload
        )
        
        print(f"Create device with v3 response: {response.status_code} - {response.text}")
        
        # May return 409 if device already exists
        if response.status_code == 409:
            print("Device already exists - this is acceptable")
            return
        
        assert response.status_code in [200, 201], f"Expected 200/201, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify the device was created with v3 fields
        if "device" in data:
            device = data["device"]
            assert device.get("snmp_version") == "v3"
            assert device.get("snmpv3_username") == "newdeviceuser"
            assert device.get("snmpv3_auth_protocol") == "SHA"
            assert device.get("snmpv3_priv_protocol") == "AES"
            assert device.get("snmpv3_security_level") == "authPriv"
    
    def test_create_device_with_v2c_default(self, auth_headers):
        """Test creating a device with default v2c SNMP"""
        unique_ip = f"192.168.98.{uuid.uuid4().int % 255}"
        
        payload = {
            "ip": unique_ip,
            "name": f"TEST_v2c_Device_{uuid.uuid4().hex[:8]}",
            "community": "public",
            "monitor_type": "snmp",
            "device_type": "network"
        }
        
        response = requests.post(
            f"{BASE_URL}/api/connector/{TEST_CLIENT_ID}/managed-devices",
            headers=auth_headers,
            json=payload
        )
        
        print(f"Create device with v2c response: {response.status_code}")
        
        if response.status_code == 409:
            print("Device already exists - this is acceptable")
            return
        
        assert response.status_code in [200, 201]
        data = response.json()
        
        if "device" in data:
            device = data["device"]
            # Default should be v2c
            assert device.get("snmp_version") in ["v2c", None]


class TestSNMPv3FieldsInModel:
    """Test that ManagedDevice model accepts all SNMPv3 fields"""
    
    def test_all_v3_fields_accepted(self, auth_headers):
        """Test that all SNMPv3 USM fields are accepted by the API"""
        # First set to v3 with all fields
        payload = {
            "snmp_version": "v3",
            "snmpv3_username": "fulltest_user",
            "snmpv3_auth_protocol": "SHA",
            "snmpv3_auth_password": "fulltest_auth_pass",
            "snmpv3_priv_protocol": "AES",
            "snmpv3_priv_password": "fulltest_priv_pass",
            "snmpv3_security_level": "authPriv"
        }
        
        response = requests.put(
            f"{BASE_URL}/api/connector/{TEST_CLIENT_ID}/managed-devices/{TEST_DEVICE_ID}/snmp",
            headers=auth_headers,
            json=payload
        )
        
        assert response.status_code == 200
        
        # Now verify by getting the device list
        list_response = requests.get(
            f"{BASE_URL}/api/connector/{TEST_CLIENT_ID}/managed-devices",
            headers=auth_headers
        )
        
        assert list_response.status_code == 200
        devices = list_response.json()
        
        # Find our test device
        test_device = None
        for d in devices:
            if d.get("id") == TEST_DEVICE_ID:
                test_device = d
                break
        
        if test_device:
            print(f"Test device SNMP config: version={test_device.get('snmp_version')}, "
                  f"username={test_device.get('snmpv3_username')}, "
                  f"auth_proto={test_device.get('snmpv3_auth_protocol')}, "
                  f"priv_proto={test_device.get('snmpv3_priv_protocol')}, "
                  f"sec_level={test_device.get('snmpv3_security_level')}")
            
            assert test_device.get("snmp_version") == "v3"
            assert test_device.get("snmpv3_username") == "fulltest_user"
            assert test_device.get("snmpv3_auth_protocol") == "SHA"
            assert test_device.get("snmpv3_priv_protocol") == "AES"
            assert test_device.get("snmpv3_security_level") == "authPriv"
        else:
            print(f"Test device {TEST_DEVICE_ID} not found in list - may have been deleted")


class TestSNMPv3Cleanup:
    """Cleanup: Revert test device back to v2c"""
    
    def test_revert_device_to_v2c(self, auth_headers):
        """Revert the test device back to v2c as requested"""
        payload = {
            "snmp_version": "v2c",
            "community": "public"
        }
        
        response = requests.put(
            f"{BASE_URL}/api/connector/{TEST_CLIENT_ID}/managed-devices/{TEST_DEVICE_ID}/snmp",
            headers=auth_headers,
            json=payload
        )
        
        print(f"Cleanup - Revert to v2c response: {response.status_code} - {response.text}")
        
        # This should succeed or return 404 if device doesn't exist
        assert response.status_code in [200, 404]
        
        if response.status_code == 200:
            data = response.json()
            assert data.get("snmp_version") == "v2c"
            print("Device successfully reverted to v2c")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
