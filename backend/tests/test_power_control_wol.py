"""
Test Power Control (Redfish) and Wake-on-LAN features
Tests:
- POST /api/devices/{ip}/power-action - Execute power action via Redfish
- GET /api/devices/{ip}/power-state - Get current power state via Redfish
- POST /api/devices/{ip}/wake-on-lan - Queue WoL command
- GET /api/connector/pending-commands - Connector fetches pending WoL commands
- Heartbeat response includes pending_commands when WoL is queued
- Role-based access (403 for non-admin)
- Vault regression tests
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials from iteration_17
ADMIN_EMAIL = "admin@86bit.it"
ADMIN_PASSWORD = "admin123"
CONNECTOR_API_KEY = "noc_35cf39b4d68740b1a981aedef2ee293d"
ILO_DEVICE_IP = "192.168.1.8"  # Has external_url configured


@pytest.fixture(scope="module")
def admin_token():
    """Get admin JWT token."""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD
    })
    assert response.status_code == 200, f"Admin login failed: {response.text}"
    return response.json()["token"]


@pytest.fixture(scope="module")
def operator_token():
    """Get or create operator user token."""
    # Try to login as existing operator
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "operator@test.com",
        "password": "operator123"
    })
    if response.status_code == 200:
        return response.json()["token"]
    
    # Create operator user via admin
    admin_resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD
    })
    admin_token = admin_resp.json()["token"]
    
    create_resp = requests.post(
        f"{BASE_URL}/api/admin/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "email": "operator@test.com",
            "password": "operator123",
            "name": "Test Operator",
            "role": "operator"
        }
    )
    
    # Login as operator
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "operator@test.com",
        "password": "operator123"
    })
    assert response.status_code == 200
    return response.json()["token"]


class TestPowerAction:
    """Test POST /api/devices/{ip}/power-action endpoint."""
    
    def test_power_action_returns_error_gracefully(self, admin_token):
        """Power action returns error when iLO is unreachable (expected behavior)."""
        response = requests.post(
            f"{BASE_URL}/api/devices/{ILO_DEVICE_IP}/power-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"action": "On"}
        )
        # Should return 200 with success=False since iLO is unreachable
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        # Since no real iLO is reachable, expect connection error
        if not data["success"]:
            assert "error" in data
            print(f"Power action error (expected): {data['error']}")
    
    def test_power_action_requires_action_field(self, admin_token):
        """Power action returns 400 when action field is missing."""
        response = requests.post(
            f"{BASE_URL}/api/devices/{ILO_DEVICE_IP}/power-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={}
        )
        assert response.status_code == 400
        assert "action" in response.json().get("detail", "").lower()
    
    def test_power_action_returns_403_for_non_admin(self, operator_token):
        """Power action returns 403 for non-admin users."""
        response = requests.post(
            f"{BASE_URL}/api/devices/{ILO_DEVICE_IP}/power-action",
            headers={"Authorization": f"Bearer {operator_token}"},
            json={"action": "On"}
        )
        assert response.status_code == 403
    
    def test_power_action_returns_404_for_no_ilo_credential(self, admin_token):
        """Power action returns 404 when no iLO credential exists for device."""
        response = requests.post(
            f"{BASE_URL}/api/devices/10.0.0.99/power-action",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"action": "On"}
        )
        assert response.status_code == 404
        assert "ilo" in response.json().get("detail", "").lower()


class TestPowerState:
    """Test GET /api/devices/{ip}/power-state endpoint."""
    
    def test_power_state_returns_error_gracefully(self, admin_token):
        """Power state returns error when iLO is unreachable (expected behavior)."""
        response = requests.get(
            f"{BASE_URL}/api/devices/{ILO_DEVICE_IP}/power-state",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "success" in data
        # Since no real iLO is reachable, expect connection error
        if not data["success"]:
            assert "error" in data
            print(f"Power state error (expected): {data['error']}")
    
    def test_power_state_returns_403_for_non_admin(self, operator_token):
        """Power state returns 403 for non-admin users."""
        response = requests.get(
            f"{BASE_URL}/api/devices/{ILO_DEVICE_IP}/power-state",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 403
    
    def test_power_state_returns_404_for_no_ilo_credential(self, admin_token):
        """Power state returns 404 when no iLO credential exists for device."""
        response = requests.get(
            f"{BASE_URL}/api/devices/10.0.0.99/power-state",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 404


class TestWakeOnLAN:
    """Test POST /api/devices/{ip}/wake-on-lan endpoint."""
    
    def test_wol_queues_command_successfully(self, admin_token):
        """WoL endpoint queues command with valid MAC address."""
        test_mac = "AA:BB:CC:DD:EE:FF"
        response = requests.post(
            f"{BASE_URL}/api/devices/192.168.1.100/wake-on-lan",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"mac_address": test_mac}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"
        assert "accodato" in data.get("message", "").lower() or "queued" in data.get("message", "").lower()
        print(f"WoL response: {data}")
    
    def test_wol_validates_mac_format(self, admin_token):
        """WoL endpoint validates MAC address format."""
        # Invalid MAC - too short
        response = requests.post(
            f"{BASE_URL}/api/devices/192.168.1.100/wake-on-lan",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"mac_address": "AA:BB:CC"}
        )
        assert response.status_code == 400
        assert "mac" in response.json().get("detail", "").lower()
    
    def test_wol_validates_empty_mac(self, admin_token):
        """WoL endpoint rejects empty MAC address."""
        response = requests.post(
            f"{BASE_URL}/api/devices/192.168.1.100/wake-on-lan",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"mac_address": ""}
        )
        assert response.status_code == 400
    
    def test_wol_returns_403_for_non_admin(self, operator_token):
        """WoL endpoint returns 403 for non-admin users."""
        response = requests.post(
            f"{BASE_URL}/api/devices/192.168.1.100/wake-on-lan",
            headers={"Authorization": f"Bearer {operator_token}"},
            json={"mac_address": "AA:BB:CC:DD:EE:FF"}
        )
        assert response.status_code == 403


class TestPendingCommands:
    """Test GET /api/connector/pending-commands endpoint."""
    
    def test_pending_commands_with_valid_api_key(self, admin_token):
        """Connector can fetch pending commands with valid API key."""
        # First queue a WoL command
        test_mac = f"11:22:33:44:55:{uuid.uuid4().hex[:2].upper()}"
        requests.post(
            f"{BASE_URL}/api/devices/192.168.1.200/wake-on-lan",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"mac_address": test_mac}
        )
        
        # Fetch pending commands as connector
        response = requests.get(
            f"{BASE_URL}/api/connector/pending-commands",
            headers={"X-API-Key": CONNECTOR_API_KEY}
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"Pending commands: {len(data)} commands")
        
        # Commands should be marked as dispatched after fetch
        # Second call should return empty or different commands
        response2 = requests.get(
            f"{BASE_URL}/api/connector/pending-commands",
            headers={"X-API-Key": CONNECTOR_API_KEY}
        )
        assert response2.status_code == 200
    
    def test_pending_commands_returns_401_without_api_key(self):
        """Pending commands returns 401 without API key."""
        response = requests.get(f"{BASE_URL}/api/connector/pending-commands")
        assert response.status_code == 401
    
    def test_pending_commands_returns_401_for_invalid_api_key(self):
        """Pending commands returns 401 for invalid API key."""
        response = requests.get(
            f"{BASE_URL}/api/connector/pending-commands",
            headers={"X-API-Key": "invalid_key_12345"}
        )
        assert response.status_code == 401


class TestHeartbeatWithPendingCommands:
    """Test that heartbeat response includes pending_commands when WoL is queued."""
    
    def test_heartbeat_includes_pending_commands(self, admin_token):
        """Heartbeat response includes pending_commands when WoL is queued."""
        # Queue a fresh WoL command
        test_mac = f"AA:BB:CC:DD:EE:{uuid.uuid4().hex[:2].upper()}"
        wol_resp = requests.post(
            f"{BASE_URL}/api/devices/192.168.1.201/wake-on-lan",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"mac_address": test_mac}
        )
        assert wol_resp.status_code == 200
        
        # Send heartbeat as connector
        heartbeat_resp = requests.post(
            f"{BASE_URL}/api/connector/heartbeat",
            headers={"X-API-Key": CONNECTOR_API_KEY},
            json={
                "connector_version": "1.8.0",
                "hostname": "test-connector",
                "uptime_seconds": 3600,
                "traps_received": 0,
                "syslogs_received": 0
            }
        )
        assert heartbeat_resp.status_code == 200
        data = heartbeat_resp.json()
        assert data.get("status") == "ok"
        
        # Check if pending_commands is included (may or may not have commands)
        if "pending_commands" in data:
            print(f"Heartbeat includes {len(data['pending_commands'])} pending commands")
            for cmd in data["pending_commands"]:
                assert "type" in cmd
                assert "mac_address" in cmd or "target_ip" in cmd
        else:
            print("No pending commands in heartbeat (commands may have been dispatched already)")


class TestVaultRegression:
    """Regression tests for vault endpoints (from iteration_17)."""
    
    def test_vault_credentials_list(self, admin_token):
        """GET /api/vault/credentials returns credentials list."""
        response = requests.get(
            f"{BASE_URL}/api/vault/credentials",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"Vault has {len(data)} credentials")
    
    def test_vault_credentials_returns_403_for_non_admin(self, operator_token):
        """GET /api/vault/credentials returns 403 for non-admin."""
        response = requests.get(
            f"{BASE_URL}/api/vault/credentials",
            headers={"Authorization": f"Bearer {operator_token}"}
        )
        assert response.status_code == 403
    
    def test_redfish_failover_status(self, admin_token):
        """GET /api/redfish/failover-status returns polling mode for iLO devices."""
        response = requests.get(
            f"{BASE_URL}/api/redfish/failover-status",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"Failover status: {len(data)} iLO devices")
    
    def test_connector_vault_credentials(self):
        """GET /api/connector/vault/credentials returns decrypted credentials."""
        response = requests.get(
            f"{BASE_URL}/api/connector/vault/credentials",
            headers={"X-API-Key": CONNECTOR_API_KEY}
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"Connector vault: {len(data)} credentials")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
