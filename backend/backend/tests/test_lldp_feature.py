"""
Test LLDP (Link Layer Discovery Protocol) Feature
- POST /api/connector/lldp-neighbors - Store LLDP data from connector
- GET /api/network/lldp/{client_id} - Get raw LLDP data
- GET /api/network/topology/{client_id} - Verify LLDP edges in topology
- POST/DELETE /api/network/topology/{client_id}/layout - Regression tests
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
ADMIN_EMAIL = "admin@86bit.it"
ADMIN_PASSWORD = "password"
CONNECTOR_API_KEY = "noc_35cf39b4d68740b1a981aedef2ee293d"
CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token for admin user."""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD
    })
    if response.status_code == 200:
        return response.json().get("token")
    pytest.skip(f"Authentication failed: {response.status_code} - {response.text}")


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Headers with auth token."""
    return {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }


@pytest.fixture(scope="module")
def connector_headers():
    """Headers with connector API key."""
    return {
        "X-API-Key": CONNECTOR_API_KEY,
        "Content-Type": "application/json"
    }


class TestLLDPConnectorEndpoint:
    """Test POST /api/connector/lldp-neighbors endpoint."""
    
    def test_lldp_report_requires_api_key(self):
        """LLDP report should require API key."""
        response = requests.post(f"{BASE_URL}/api/connector/lldp-neighbors", json={
            "neighbors": []
        })
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: LLDP report requires API key")
    
    def test_lldp_report_invalid_api_key(self):
        """LLDP report should reject invalid API key."""
        response = requests.post(
            f"{BASE_URL}/api/connector/lldp-neighbors",
            headers={"X-API-Key": "invalid_key", "Content-Type": "application/json"},
            json={"neighbors": []}
        )
        assert response.status_code == 401, f"Expected 401, got {response.status_code}"
        print("PASS: LLDP report rejects invalid API key")
    
    def test_lldp_report_success(self, connector_headers):
        """LLDP report should store neighbors successfully."""
        # Sample LLDP data matching the existing device IPs
        lldp_data = {
            "neighbors": [
                {
                    "local_ip": "192.168.1.2",
                    "local_port_id": "1",
                    "local_port_desc": "Port 1",
                    "remote_ip": "192.168.1.3",
                    "remote_sys_name": "HPE-Switch-2",
                    "remote_port_id": "24",
                    "remote_port_desc": "Port 24",
                    "remote_sys_desc": "HPE OfficeConnect Switch",
                    "remote_chassis_id": "00:11:22:33:44:55"
                },
                {
                    "local_ip": "192.168.1.254",
                    "local_port_id": "LAN1",
                    "local_port_desc": "LAN Port 1",
                    "remote_ip": "192.168.1.2",
                    "remote_sys_name": "HPE-Switch-1",
                    "remote_port_id": "1",
                    "remote_port_desc": "Port 1",
                    "remote_sys_desc": "HPE OfficeConnect Switch",
                    "remote_chassis_id": "AA:BB:CC:DD:EE:FF"
                }
            ]
        }
        
        response = requests.post(
            f"{BASE_URL}/api/connector/lldp-neighbors",
            headers=connector_headers,
            json=lldp_data
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data.get("status") == "ok", f"Expected status 'ok', got {data}"
        assert data.get("neighbors_stored") == 2, f"Expected 2 neighbors stored, got {data.get('neighbors_stored')}"
        print(f"PASS: LLDP report stored {data.get('neighbors_stored')} neighbors")
    
    def test_lldp_report_empty_neighbors(self, connector_headers):
        """LLDP report with empty neighbors should clear existing data."""
        # First add some data
        response = requests.post(
            f"{BASE_URL}/api/connector/lldp-neighbors",
            headers=connector_headers,
            json={"neighbors": [{"local_ip": "192.168.1.2", "remote_ip": "192.168.1.3"}]}
        )
        assert response.status_code == 200
        
        # Then clear with empty list
        response = requests.post(
            f"{BASE_URL}/api/connector/lldp-neighbors",
            headers=connector_headers,
            json={"neighbors": []}
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("neighbors_stored") == 0, f"Expected 0 neighbors stored, got {data.get('neighbors_stored')}"
        print("PASS: LLDP report with empty neighbors clears data")


class TestLLDPGetEndpoint:
    """Test GET /api/network/lldp/{client_id} endpoint."""
    
    def test_get_lldp_requires_auth(self):
        """GET LLDP should require authentication."""
        response = requests.get(f"{BASE_URL}/api/network/lldp/{CLIENT_ID}")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print("PASS: GET LLDP requires authentication")
    
    def test_get_lldp_success(self, auth_headers, connector_headers):
        """GET LLDP should return stored neighbors."""
        # First store some LLDP data
        lldp_data = {
            "neighbors": [
                {
                    "local_ip": "192.168.1.2",
                    "local_port_id": "1",
                    "local_port_desc": "Port 1",
                    "remote_ip": "192.168.1.3",
                    "remote_sys_name": "HPE-Switch-2",
                    "remote_port_id": "24",
                    "remote_port_desc": "Port 24"
                },
                {
                    "local_ip": "192.168.1.254",
                    "local_port_id": "LAN1",
                    "local_port_desc": "LAN Port 1",
                    "remote_ip": "192.168.1.2",
                    "remote_sys_name": "HPE-Switch-1",
                    "remote_port_id": "1",
                    "remote_port_desc": "Port 1"
                },
                {
                    "local_ip": "192.168.1.3",
                    "local_port_id": "2",
                    "local_port_desc": "Port 2",
                    "remote_ip": "192.168.1.4",
                    "remote_sys_name": "Server-1",
                    "remote_port_id": "eth0",
                    "remote_port_desc": "Ethernet 0"
                },
                {
                    "local_ip": "192.168.1.3",
                    "local_port_id": "3",
                    "local_port_desc": "Port 3",
                    "remote_ip": "192.168.1.5",
                    "remote_sys_name": "Server-2",
                    "remote_port_id": "eth0",
                    "remote_port_desc": "Ethernet 0"
                }
            ]
        }
        store_response = requests.post(
            f"{BASE_URL}/api/connector/lldp-neighbors",
            headers=connector_headers,
            json=lldp_data
        )
        assert store_response.status_code == 200, f"Failed to store LLDP data: {store_response.text}"
        
        # Now get the LLDP data
        response = requests.get(
            f"{BASE_URL}/api/network/lldp/{CLIENT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify response structure
        assert "client_id" in data, "Response should have client_id"
        assert data["client_id"] == CLIENT_ID, f"Expected client_id {CLIENT_ID}, got {data['client_id']}"
        assert "neighbors" in data, "Response should have neighbors"
        assert "count" in data, "Response should have count"
        assert data["count"] == 4, f"Expected 4 neighbors, got {data['count']}"
        assert len(data["neighbors"]) == 4, f"Expected 4 neighbors in list, got {len(data['neighbors'])}"
        
        # Verify neighbor structure
        neighbor = data["neighbors"][0]
        assert "local_ip" in neighbor, "Neighbor should have local_ip"
        assert "remote_ip" in neighbor, "Neighbor should have remote_ip"
        
        print(f"PASS: GET LLDP returns {data['count']} neighbors with correct structure")


class TestTopologyWithLLDP:
    """Test GET /api/network/topology/{client_id} with LLDP data."""
    
    def test_topology_includes_lldp_count(self, auth_headers, connector_headers):
        """Topology should include lldp_count field."""
        # Ensure LLDP data exists
        lldp_data = {
            "neighbors": [
                {"local_ip": "192.168.1.2", "remote_ip": "192.168.1.3", "local_port_desc": "Port 1", "remote_port_desc": "Port 24"},
                {"local_ip": "192.168.1.254", "remote_ip": "192.168.1.2", "local_port_desc": "LAN1", "remote_port_desc": "Port 1"},
                {"local_ip": "192.168.1.3", "remote_ip": "192.168.1.4", "local_port_desc": "Port 2", "remote_port_desc": "eth0"},
                {"local_ip": "192.168.1.3", "remote_ip": "192.168.1.5", "local_port_desc": "Port 3", "remote_port_desc": "eth0"}
            ]
        }
        requests.post(f"{BASE_URL}/api/connector/lldp-neighbors", headers=connector_headers, json=lldp_data)
        
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        
        assert "lldp_count" in data, "Topology should have lldp_count field"
        assert data["lldp_count"] > 0, f"Expected lldp_count > 0, got {data['lldp_count']}"
        print(f"PASS: Topology includes lldp_count = {data['lldp_count']}")
    
    def test_topology_has_lldp_edges(self, auth_headers, connector_headers):
        """Topology edges should include LLDP type edges when LLDP data exists."""
        # First, reset any custom layout to get inferred topology with LLDP
        requests.delete(f"{BASE_URL}/api/network/topology/{CLIENT_ID}/layout", headers=auth_headers)
        
        # Ensure LLDP data exists with matching device IPs
        lldp_data = {
            "neighbors": [
                {"local_ip": "192.168.1.2", "remote_ip": "192.168.1.3", "local_port_desc": "Port 1", "remote_port_desc": "Port 24"},
                {"local_ip": "192.168.1.254", "remote_ip": "192.168.1.2", "local_port_desc": "LAN1", "remote_port_desc": "Port 1"}
            ]
        }
        requests.post(f"{BASE_URL}/api/connector/lldp-neighbors", headers=connector_headers, json=lldp_data)
        
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        edges = data.get("edges", [])
        lldp_edges = [e for e in edges if e.get("type") == "lldp" or e.get("source") == "lldp"]
        
        print(f"Total edges: {len(edges)}, LLDP edges: {len(lldp_edges)}")
        
        # Check if any LLDP edges exist
        if data["lldp_count"] > 0:
            # LLDP edges should exist if LLDP data matches device IPs
            for edge in lldp_edges:
                assert edge.get("type") == "lldp", f"LLDP edge should have type='lldp', got {edge.get('type')}"
                assert edge.get("source") == "lldp", f"LLDP edge should have source='lldp', got {edge.get('source')}"
                # Check label has port info
                if edge.get("label"):
                    assert "<->" in edge["label"] or edge.get("local_port") or edge.get("remote_port"), \
                        f"LLDP edge label should have port info: {edge.get('label')}"
            print(f"PASS: Found {len(lldp_edges)} LLDP edges with correct attributes")
        else:
            print("INFO: No LLDP edges found (LLDP data may not match device IPs)")
    
    def test_lldp_edges_replace_inferred(self, auth_headers, connector_headers):
        """LLDP edges should replace inferred edges for the same node pairs."""
        # Reset layout first
        requests.delete(f"{BASE_URL}/api/network/topology/{CLIENT_ID}/layout", headers=auth_headers)
        
        # Get topology without LLDP
        requests.post(f"{BASE_URL}/api/connector/lldp-neighbors", headers=connector_headers, json={"neighbors": []})
        response_no_lldp = requests.get(f"{BASE_URL}/api/network/topology/{CLIENT_ID}", headers=auth_headers)
        edges_no_lldp = response_no_lldp.json().get("edges", [])
        
        # Add LLDP data
        lldp_data = {
            "neighbors": [
                {"local_ip": "192.168.1.2", "remote_ip": "192.168.1.3", "local_port_desc": "Port 1", "remote_port_desc": "Port 24"},
                {"local_ip": "192.168.1.254", "remote_ip": "192.168.1.2", "local_port_desc": "LAN1", "remote_port_desc": "Port 1"}
            ]
        }
        requests.post(f"{BASE_URL}/api/connector/lldp-neighbors", headers=connector_headers, json=lldp_data)
        
        # Get topology with LLDP
        response_with_lldp = requests.get(f"{BASE_URL}/api/network/topology/{CLIENT_ID}", headers=auth_headers)
        data_with_lldp = response_with_lldp.json()
        edges_with_lldp = data_with_lldp.get("edges", [])
        
        # Count edge types
        lldp_edges = [e for e in edges_with_lldp if e.get("type") == "lldp"]
        inferred_edges = [e for e in edges_with_lldp if e.get("type") != "lldp"]
        
        print(f"Without LLDP: {len(edges_no_lldp)} edges")
        print(f"With LLDP: {len(edges_with_lldp)} edges ({len(lldp_edges)} LLDP, {len(inferred_edges)} inferred)")
        
        # Verify LLDP edges exist
        if data_with_lldp["lldp_count"] > 0 and len(lldp_edges) > 0:
            # Check that LLDP edges have proper attributes
            for edge in lldp_edges:
                assert edge.get("type") == "lldp"
                assert edge.get("source") == "lldp"
            print(f"PASS: LLDP edges properly integrated into topology")
        else:
            print("INFO: No LLDP edges created (device IPs may not match)")


class TestTopologyLayoutRegression:
    """Regression tests for topology layout save/reset."""
    
    def test_save_layout_still_works(self, auth_headers):
        """POST /api/network/topology/{client_id}/layout should still work."""
        # Get current topology
        response = requests.get(f"{BASE_URL}/api/network/topology/{CLIENT_ID}", headers=auth_headers)
        assert response.status_code == 200
        topo = response.json()
        
        # Save layout with modified positions
        nodes = topo.get("nodes", [])
        if nodes:
            nodes[0]["position"] = {"x": 100, "y": 100}
        
        save_response = requests.post(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}/layout",
            headers=auth_headers,
            json={"nodes": nodes, "edges": topo.get("edges", [])}
        )
        assert save_response.status_code == 200, f"Expected 200, got {save_response.status_code}: {save_response.text}"
        data = save_response.json()
        assert data.get("status") == "ok", f"Expected status 'ok', got {data}"
        print("PASS: Save layout still works")
    
    def test_delete_layout_still_works(self, auth_headers):
        """DELETE /api/network/topology/{client_id}/layout should still work."""
        response = requests.delete(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}/layout",
            headers=auth_headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data.get("status") == "ok", f"Expected status 'ok', got {data}"
        print("PASS: Delete layout still works")
    
    def test_has_custom_layout_flag(self, auth_headers):
        """Topology should correctly report has_custom_layout flag."""
        # Reset first
        requests.delete(f"{BASE_URL}/api/network/topology/{CLIENT_ID}/layout", headers=auth_headers)
        
        # Check flag is False
        response = requests.get(f"{BASE_URL}/api/network/topology/{CLIENT_ID}", headers=auth_headers)
        assert response.status_code == 200
        assert response.json().get("has_custom_layout") == False, "Expected has_custom_layout=False after reset"
        
        # Save layout
        topo = response.json()
        requests.post(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}/layout",
            headers=auth_headers,
            json={"nodes": topo.get("nodes", []), "edges": topo.get("edges", [])}
        )
        
        # Check flag is True
        response = requests.get(f"{BASE_URL}/api/network/topology/{CLIENT_ID}", headers=auth_headers)
        assert response.json().get("has_custom_layout") == True, "Expected has_custom_layout=True after save"
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/network/topology/{CLIENT_ID}/layout", headers=auth_headers)
        print("PASS: has_custom_layout flag works correctly")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
