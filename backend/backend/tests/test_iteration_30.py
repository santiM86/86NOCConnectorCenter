"""
Iteration 30 - Testing new features:
- Netgear device names are abbreviated (e.g., 'NETGEAR GS110EMX - Under Counter 5m')
- Managed devices with known MAC have 'mac' field in topology
- POST /api/network/add-to-monitoring - adds discovered endpoint to monitoring
- POST /api/network/add-to-monitoring - duplicate IP returns 409
- GET /api/network/device-detail/{client_id}/{device_ip} - returns switch info, port_speeds, connected_endpoints, lldp
"""
import pytest
import requests
import os

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"

# Test credentials
TEST_EMAIL = "admin@86bit.it"
TEST_PASSWORD = "password"


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token."""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD
    })
    if response.status_code == 200:
        return response.json().get("token")
    pytest.skip(f"Authentication failed: {response.status_code} - {response.text}")


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Return headers with auth token."""
    return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}


class TestNetgearNameAbbreviation:
    """Test that Netgear device names are properly abbreviated."""

    def test_topology_has_abbreviated_netgear_names(self, auth_headers):
        """Netgear names should be shortened (e.g., 'NETGEAR GS110EMX - Under Counter 5m')."""
        response = requests.get(f"{BASE_URL}/api/network/topology/{CLIENT_ID}", headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        nodes = data.get("nodes", [])
        
        # Find Netgear nodes
        netgear_nodes = [n for n in nodes if "netgear" in (n.get("name", "") or "").lower()]
        assert len(netgear_nodes) > 0, "Expected at least one Netgear device in topology"
        
        for node in netgear_nodes:
            name = node.get("name", "")
            # Name should NOT contain the long description like "8-Port Gigabit Ethernet Smart Managed Plus Switch"
            assert "8-Port Gigabit Ethernet Smart Managed Plus Switch" not in name, \
                f"Netgear name should be abbreviated, got: {name}"
            # Name should be reasonably short (< 60 chars)
            assert len(name) < 60, f"Netgear name too long: {name}"
            print(f"Netgear node name (abbreviated): {name}")


class TestMacEnrichment:
    """Test that managed devices with known MAC have 'mac' field in topology."""

    def test_topology_nodes_have_mac_field(self, auth_headers):
        """Managed devices with known MAC should have 'mac' field populated."""
        response = requests.get(f"{BASE_URL}/api/network/topology/{CLIENT_ID}", headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        nodes = data.get("nodes", [])
        
        # Find nodes with MAC addresses (Netgear switches at .3, .4, .5 should have MACs)
        nodes_with_mac = [n for n in nodes if n.get("mac")]
        print(f"Nodes with MAC: {len(nodes_with_mac)}")
        
        for node in nodes_with_mac:
            mac = node.get("mac", "")
            ip = node.get("ip", "")
            name = node.get("name", "")
            print(f"  - {name} ({ip}): MAC = {mac}")
            # MAC should be in valid format (XX:XX:XX:XX:XX:XX)
            assert len(mac) >= 12, f"Invalid MAC format: {mac}"
        
        # At least some managed devices should have MAC
        # (Netgear switches at 192.168.1.3, .4, .5 should have MACs from device_macs)
        assert len(nodes_with_mac) >= 1, "Expected at least one node with MAC address"


class TestDeviceDetailEndpoint:
    """Test GET /api/network/device-detail/{client_id}/{device_ip}."""

    def test_device_detail_returns_switch_info(self, auth_headers):
        """Device detail should return device object with switch info."""
        # Use Netgear switch at 192.168.1.3
        device_ip = "192.168.1.3"
        response = requests.get(f"{BASE_URL}/api/network/device-detail/{CLIENT_ID}/{device_ip}", headers=auth_headers)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "device" in data, "Response should contain 'device' object"
        device = data["device"]
        assert device.get("device_ip") == device_ip, f"Expected device_ip={device_ip}"
        print(f"Device info: {device.get('device_name')}, reachable={device.get('reachable')}")

    def test_device_detail_returns_port_speeds(self, auth_headers):
        """Device detail should return port_speeds array."""
        device_ip = "192.168.1.3"
        response = requests.get(f"{BASE_URL}/api/network/device-detail/{CLIENT_ID}/{device_ip}", headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        port_speeds = data.get("port_speeds", [])
        print(f"Port speeds: {port_speeds}")
        # Netgear .3 should have 10G ports (port 9 and 10)
        assert isinstance(port_speeds, list), "port_speeds should be a list"

    def test_device_detail_returns_connected_endpoints(self, auth_headers):
        """Device detail should return connected_endpoints array."""
        device_ip = "192.168.1.3"
        response = requests.get(f"{BASE_URL}/api/network/device-detail/{CLIENT_ID}/{device_ip}", headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        connected = data.get("connected_endpoints", [])
        print(f"Connected endpoints: {len(connected)}")
        assert isinstance(connected, list), "connected_endpoints should be a list"

    def test_device_detail_returns_lldp_neighbors(self, auth_headers):
        """Device detail should return lldp_neighbors array."""
        device_ip = "192.168.1.3"
        response = requests.get(f"{BASE_URL}/api/network/device-detail/{CLIENT_ID}/{device_ip}", headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        lldp = data.get("lldp_neighbors", [])
        print(f"LLDP neighbors: {len(lldp)}")
        assert isinstance(lldp, list), "lldp_neighbors should be a list"

    def test_device_detail_404_for_unknown_device(self, auth_headers):
        """Device detail should return 404 for unknown device IP."""
        device_ip = "192.168.99.99"
        response = requests.get(f"{BASE_URL}/api/network/device-detail/{CLIENT_ID}/{device_ip}", headers=auth_headers)
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"


class TestAddToMonitoring:
    """Test POST /api/network/add-to-monitoring endpoint."""

    def test_add_to_monitoring_duplicate_returns_409(self, auth_headers):
        """Adding an already monitored IP should return 409."""
        # PC-RECEPTION (192.168.1.50) was already added in previous iterations
        response = requests.post(f"{BASE_URL}/api/network/add-to-monitoring", headers=auth_headers, json={
            "client_id": CLIENT_ID,
            "ip": "192.168.1.50",
            "name": "PC-RECEPTION",
            "mac": "",
            "monitor_type": "ping",
            "community": ""
        })
        assert response.status_code == 409, f"Expected 409 for duplicate, got {response.status_code}: {response.text}"
        print(f"Duplicate add correctly returned 409: {response.json()}")

    def test_add_to_monitoring_missing_fields_returns_400(self, auth_headers):
        """Adding without required fields should return 400."""
        response = requests.post(f"{BASE_URL}/api/network/add-to-monitoring", headers=auth_headers, json={
            "client_id": CLIENT_ID,
            # Missing 'ip' field
            "name": "Test Device",
            "monitor_type": "ping"
        })
        assert response.status_code == 400, f"Expected 400 for missing ip, got {response.status_code}"

    def test_add_new_endpoint_to_monitoring(self, auth_headers):
        """Adding a new endpoint should succeed and mark it as managed."""
        # Use SRV-DC01 (192.168.1.10) or PC-ADMIN01 (192.168.1.51) as suggested
        # First check if 192.168.1.10 is already monitored
        test_ip = "192.168.1.10"
        
        # Try to add - if already exists, we'll get 409 which is also valid
        response = requests.post(f"{BASE_URL}/api/network/add-to-monitoring", headers=auth_headers, json={
            "client_id": CLIENT_ID,
            "ip": test_ip,
            "name": "SRV-DC01",
            "mac": "00:11:22:33:44:55",
            "monitor_type": "ping",
            "community": ""
        })
        
        if response.status_code == 409:
            print(f"IP {test_ip} already monitored (409) - this is expected if previously added")
            # Try another IP
            test_ip = "192.168.1.51"
            response = requests.post(f"{BASE_URL}/api/network/add-to-monitoring", headers=auth_headers, json={
                "client_id": CLIENT_ID,
                "ip": test_ip,
                "name": "PC-ADMIN01",
                "mac": "00:11:22:33:44:56",
                "monitor_type": "ping",
                "community": ""
            })
            
            if response.status_code == 409:
                print(f"IP {test_ip} also already monitored - skipping add test")
                pytest.skip("All test IPs already monitored")
        
        if response.status_code == 200:
            data = response.json()
            assert data.get("status") == "ok", f"Expected status=ok, got {data}"
            assert "device" in data, "Response should contain 'device' object"
            print(f"Successfully added {test_ip} to monitoring: {data}")
            
            # Verify the device no longer appears as discovered_endpoint
            topo_response = requests.get(f"{BASE_URL}/api/network/topology/{CLIENT_ID}", headers=auth_headers)
            assert topo_response.status_code == 200
            topo_data = topo_response.json()
            
            # Check that the IP is not in discovered_endpoints anymore
            discovered_nodes = [n for n in topo_data.get("nodes", []) 
                              if n.get("role") == "discovered_endpoint" and n.get("ip") == test_ip]
            assert len(discovered_nodes) == 0, f"IP {test_ip} should not appear as discovered_endpoint after adding to monitoring"
            print(f"Verified: {test_ip} no longer appears as discovered_endpoint")


class TestTopologyDiscoveredEndpoints:
    """Test that discovered endpoints appear correctly in topology."""

    def test_topology_has_discovered_endpoints(self, auth_headers):
        """Topology should include discovered_endpoints with role='discovered_endpoint'."""
        response = requests.get(f"{BASE_URL}/api/network/topology/{CLIENT_ID}", headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        nodes = data.get("nodes", [])
        
        discovered = [n for n in nodes if n.get("role") == "discovered_endpoint"]
        print(f"Discovered endpoints in topology: {len(discovered)}")
        
        for ep in discovered[:5]:  # Print first 5
            print(f"  - {ep.get('name')} | IP: {ep.get('ip')} | MAC: {ep.get('mac')} | Port: {ep.get('switch_port')}")
        
        # Should have some discovered endpoints
        assert len(discovered) >= 1, "Expected at least one discovered endpoint in topology"

    def test_discovered_endpoints_have_required_fields(self, auth_headers):
        """Discovered endpoints should have hostname, IP, MAC, switch_port fields."""
        response = requests.get(f"{BASE_URL}/api/network/topology/{CLIENT_ID}", headers=auth_headers)
        assert response.status_code == 200
        
        data = response.json()
        nodes = data.get("nodes", [])
        
        discovered = [n for n in nodes if n.get("role") == "discovered_endpoint"]
        
        for ep in discovered:
            # Each endpoint should have at least some identifying info
            has_id = ep.get("ip") or ep.get("mac") or ep.get("hostname")
            assert has_id, f"Endpoint missing identification: {ep}"
            
            # Should have switch_port if connected to a switch
            if ep.get("switch_ip"):
                assert ep.get("switch_port") is not None, f"Endpoint connected to switch but missing switch_port: {ep}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
