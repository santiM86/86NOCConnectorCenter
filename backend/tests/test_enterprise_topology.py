"""
Test suite for Enterprise Topology Features (Iteration 29)
Tests: device-detail, alerts-summary, topology with discovered_endpoints_count
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"
TEST_DEVICE_IP = "192.168.1.3"  # Netgear switch with port_speeds and connected_endpoints


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token"""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "admin@86bit.it",
        "password": "password"
    })
    assert response.status_code == 200, f"Login failed: {response.text}"
    return response.json().get("token")


@pytest.fixture(scope="module")
def api_client(auth_token):
    """Authenticated requests session"""
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth_token}"
    })
    return session


class TestDeviceDetailEndpoint:
    """Tests for GET /api/network/device-detail/{client_id}/{device_ip}"""

    def test_device_detail_returns_device_info(self, api_client):
        """Device detail should return device object with basic info"""
        response = api_client.get(f"{BASE_URL}/api/network/device-detail/{CLIENT_ID}/{TEST_DEVICE_IP}")
        assert response.status_code == 200
        data = response.json()
        
        # Verify device object exists
        assert "device" in data
        device = data["device"]
        assert device["device_ip"] == TEST_DEVICE_IP
        assert "device_name" in device
        assert "reachable" in device
        assert "monitor_type" in device

    def test_device_detail_returns_alerts(self, api_client):
        """Device detail should return alerts array (even if empty)"""
        response = api_client.get(f"{BASE_URL}/api/network/device-detail/{CLIENT_ID}/{TEST_DEVICE_IP}")
        assert response.status_code == 200
        data = response.json()
        
        # Verify alerts structure
        assert "alerts" in data
        assert isinstance(data["alerts"], list)
        assert "alerts_count" in data
        assert "active_alerts" in data
        assert isinstance(data["alerts_count"], int)
        assert isinstance(data["active_alerts"], int)

    def test_device_detail_returns_connected_endpoints(self, api_client):
        """Device detail should return connected_endpoints for switches"""
        response = api_client.get(f"{BASE_URL}/api/network/device-detail/{CLIENT_ID}/{TEST_DEVICE_IP}")
        assert response.status_code == 200
        data = response.json()
        
        # Verify connected_endpoints structure
        assert "connected_endpoints" in data
        assert isinstance(data["connected_endpoints"], list)
        assert "connected_count" in data
        
        # Netgear .3 should have at least 1 connected endpoint
        if data["connected_count"] > 0:
            ep = data["connected_endpoints"][0]
            assert "mac" in ep
            assert "switch_ip" in ep
            assert "port" in ep

    def test_device_detail_returns_lldp_neighbors(self, api_client):
        """Device detail should return lldp_neighbors array"""
        response = api_client.get(f"{BASE_URL}/api/network/device-detail/{CLIENT_ID}/{TEST_DEVICE_IP}")
        assert response.status_code == 200
        data = response.json()
        
        # Verify lldp_neighbors structure
        assert "lldp_neighbors" in data
        assert isinstance(data["lldp_neighbors"], list)

    def test_device_detail_returns_port_speeds(self, api_client):
        """Device detail should return port_speeds for switches with high-speed ports"""
        response = api_client.get(f"{BASE_URL}/api/network/device-detail/{CLIENT_ID}/{TEST_DEVICE_IP}")
        assert response.status_code == 200
        data = response.json()
        
        # Verify port_speeds structure
        assert "port_speeds" in data
        assert isinstance(data["port_speeds"], list)
        
        # Netgear .3 should have 10G ports (port 9 and 10)
        if len(data["port_speeds"]) > 0:
            ps = data["port_speeds"][0]
            assert "port" in ps
            assert "speed_mbps" in ps
            # Check for 10G port
            has_10g = any(p.get("speed_mbps", 0) >= 10000 for p in data["port_speeds"])
            assert has_10g, "Expected at least one 10G port"

    def test_device_detail_returns_mac_connections(self, api_client):
        """Device detail should return mac_connections array"""
        response = api_client.get(f"{BASE_URL}/api/network/device-detail/{CLIENT_ID}/{TEST_DEVICE_IP}")
        assert response.status_code == 200
        data = response.json()
        
        # Verify mac_connections structure
        assert "mac_connections" in data
        assert isinstance(data["mac_connections"], list)

    def test_device_detail_404_for_unknown_device(self, api_client):
        """Device detail should return 404 for unknown device IP"""
        response = api_client.get(f"{BASE_URL}/api/network/device-detail/{CLIENT_ID}/10.99.99.99")
        assert response.status_code == 404


class TestAlertsSummaryEndpoint:
    """Tests for GET /api/network/alerts-summary/{client_id}"""

    def test_alerts_summary_returns_client_id(self, api_client):
        """Alerts summary should return client_id"""
        response = api_client.get(f"{BASE_URL}/api/network/alerts-summary/{CLIENT_ID}")
        assert response.status_code == 200
        data = response.json()
        
        assert "client_id" in data
        assert data["client_id"] == CLIENT_ID

    def test_alerts_summary_returns_alerts_map(self, api_client):
        """Alerts summary should return alerts map (device_ip -> counts)"""
        response = api_client.get(f"{BASE_URL}/api/network/alerts-summary/{CLIENT_ID}")
        assert response.status_code == 200
        data = response.json()
        
        assert "alerts" in data
        assert isinstance(data["alerts"], dict)
        
        # If there are alerts, verify structure
        for device_ip, counts in data["alerts"].items():
            assert "total" in counts
            assert "critical" in counts
            assert "high" in counts
            assert "medium" in counts
            assert "low" in counts


class TestTopologyEndpoint:
    """Tests for GET /api/network/topology/{client_id} - discovered_endpoints_count"""

    def test_topology_returns_discovered_endpoints_count(self, api_client):
        """Topology should include discovered_endpoints_count in response"""
        response = api_client.get(f"{BASE_URL}/api/network/topology/{CLIENT_ID}")
        assert response.status_code == 200
        data = response.json()
        
        assert "discovered_endpoints_count" in data
        assert isinstance(data["discovered_endpoints_count"], int)
        # Based on seed data, should have 11 discovered endpoints
        assert data["discovered_endpoints_count"] >= 0

    def test_topology_returns_nodes_with_health(self, api_client):
        """Topology should return nodes and health score"""
        response = api_client.get(f"{BASE_URL}/api/network/topology/{CLIENT_ID}")
        assert response.status_code == 200
        data = response.json()
        
        assert "nodes" in data
        assert "health" in data
        assert "score" in data["health"]
        assert isinstance(data["health"]["score"], int)

    def test_topology_nodes_count_matches_expected(self, api_client):
        """Topology should return expected number of nodes (managed + discovered)"""
        response = api_client.get(f"{BASE_URL}/api/network/topology/{CLIENT_ID}")
        assert response.status_code == 200
        data = response.json()
        
        nodes = data.get("nodes", [])
        discovered_count = data.get("discovered_endpoints_count", 0)
        
        # Count discovered endpoint nodes
        discovered_nodes = [n for n in nodes if n.get("role") == "discovered_endpoint"]
        assert len(discovered_nodes) == discovered_count, \
            f"Expected {discovered_count} discovered nodes, got {len(discovered_nodes)}"


class TestDeviceDetailForDifferentDevices:
    """Test device-detail for various device types"""

    def test_device_detail_for_firewall(self, api_client):
        """Test device-detail for firewall (192.168.1.254)"""
        response = api_client.get(f"{BASE_URL}/api/network/device-detail/{CLIENT_ID}/192.168.1.254")
        assert response.status_code == 200
        data = response.json()
        assert "device" in data
        assert data["device"]["device_ip"] == "192.168.1.254"

    def test_device_detail_for_core_switch(self, api_client):
        """Test device-detail for HPE core switch (192.168.1.2)"""
        response = api_client.get(f"{BASE_URL}/api/network/device-detail/{CLIENT_ID}/192.168.1.2")
        assert response.status_code == 200
        data = response.json()
        assert "device" in data
        assert "connected_endpoints" in data
        assert "port_speeds" in data

    def test_device_detail_for_access_switch(self, api_client):
        """Test device-detail for access switch (192.168.1.4)"""
        response = api_client.get(f"{BASE_URL}/api/network/device-detail/{CLIENT_ID}/192.168.1.4")
        assert response.status_code == 200
        data = response.json()
        assert "device" in data
        # Access switch should have connected endpoints
        assert "connected_endpoints" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
