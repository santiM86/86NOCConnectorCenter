"""
Test cases for Network Topology Inference Engine
Tests GET /api/network/topology/{client_id} endpoint
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestTopologyEndpoint:
    """Tests for the network topology inference endpoint"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup - get auth token and client ID"""
        # Login to get token
        login_response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "admin@86bit.it", "password": "admin123"}
        )
        assert login_response.status_code == 200, f"Login failed: {login_response.text}"
        self.token = login_response.json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
        
        # Get client ID
        clients_response = requests.get(f"{BASE_URL}/api/clients", headers=self.headers)
        assert clients_response.status_code == 200
        clients = clients_response.json()
        assert len(clients) > 0, "No clients found"
        self.client_id = clients[0]["id"]
        self.client_name = clients[0]["name"]
    
    def test_topology_endpoint_returns_200(self):
        """Test that topology endpoint returns 200 OK"""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{self.client_id}",
            headers=self.headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    
    def test_topology_has_required_fields(self):
        """Test that topology response has all required fields"""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{self.client_id}",
            headers=self.headers
        )
        data = response.json()
        
        # Check required top-level fields
        assert "nodes" in data, "Missing 'nodes' field"
        assert "edges" in data, "Missing 'edges' field"
        assert "layers" in data, "Missing 'layers' field"
        assert "health" in data, "Missing 'health' field"
        assert "client_id" in data, "Missing 'client_id' field"
        assert "client_name" in data, "Missing 'client_name' field"
    
    def test_topology_has_9_nodes(self):
        """Test that topology has 9 nodes (1 internet + 8 devices)"""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{self.client_id}",
            headers=self.headers
        )
        data = response.json()
        
        nodes = data["nodes"]
        assert len(nodes) == 9, f"Expected 9 nodes, got {len(nodes)}"
        
        # Verify internet node exists
        internet_nodes = [n for n in nodes if n.get("id") == "internet"]
        assert len(internet_nodes) == 1, "Missing internet node"
        assert internet_nodes[0]["virtual"] == True
        assert internet_nodes[0]["type"] == "internet"
    
    def test_topology_has_8_edges(self):
        """Test that topology has 8 edges"""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{self.client_id}",
            headers=self.headers
        )
        data = response.json()
        
        edges = data["edges"]
        assert len(edges) == 8, f"Expected 8 edges, got {len(edges)}"
    
    def test_topology_has_4_layers(self):
        """Test that topology has 4 hierarchical layers"""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{self.client_id}",
            headers=self.headers
        )
        data = response.json()
        
        layers = data["layers"]
        assert len(layers) == 4, f"Expected 4 layers, got {len(layers)}"
        
        # Verify layer names
        layer_names = [l["name"] for l in layers]
        assert "WAN" in layer_names, "Missing WAN layer"
        assert "Firewall / Router" in layer_names, "Missing Firewall/Router layer"
        assert "Switch Core / Distribuzione" in layer_names, "Missing Switch Core layer"
        assert "Accesso / Server / Mgmt" in layer_names, "Missing Access layer"
    
    def test_topology_health_score(self):
        """Test that health score is calculated correctly"""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{self.client_id}",
            headers=self.headers
        )
        data = response.json()
        
        health = data["health"]
        
        # Check health fields
        assert "score" in health, "Missing 'score' in health"
        assert "reachability" in health, "Missing 'reachability' in health"
        assert "latency_score" in health, "Missing 'latency_score' in health"
        assert "port_health" in health, "Missing 'port_health' in health"
        assert "devices_total" in health, "Missing 'devices_total' in health"
        assert "devices_online" in health, "Missing 'devices_online' in health"
        
        # Verify score is in valid range
        assert 0 <= health["score"] <= 100, f"Score {health['score']} out of range"
        
        # Verify expected values (based on current data)
        assert health["score"] == 88, f"Expected score 88, got {health['score']}"
        assert health["reachability"] == 100, f"Expected reachability 100, got {health['reachability']}"
        assert health["devices_total"] == 8, f"Expected 8 devices, got {health['devices_total']}"
        assert health["devices_online"] == 8, f"Expected 8 online, got {health['devices_online']}"
    
    def test_topology_device_types(self):
        """Test that devices are classified correctly"""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{self.client_id}",
            headers=self.headers
        )
        data = response.json()
        
        nodes = data["nodes"]
        
        # Count device types (excluding internet)
        device_nodes = [n for n in nodes if n.get("id") != "internet"]
        types = [n.get("type") for n in device_nodes]
        
        # Verify we have expected types
        assert "firewall" in types, "Missing firewall device"
        assert "switch" in types, "Missing switch devices"
        assert "ilo" in types, "Missing iLO device"
        
        # Count switches
        switch_count = types.count("switch")
        assert switch_count == 6, f"Expected 6 switches, got {switch_count}"
    
    def test_topology_edge_types(self):
        """Test that edge types are correct"""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{self.client_id}",
            headers=self.headers
        )
        data = response.json()
        
        edges = data["edges"]
        edge_types = [e.get("type") for e in edges]
        
        # Verify edge types
        assert "wan" in edge_types, "Missing WAN edge"
        assert "trunk" in edge_types, "Missing trunk edges"
        assert "access" in edge_types, "Missing access edges"
        assert "mgmt" in edge_types, "Missing management edge"
        
        # Count edge types
        wan_count = edge_types.count("wan")
        trunk_count = edge_types.count("trunk")
        access_count = edge_types.count("access")
        mgmt_count = edge_types.count("mgmt")
        
        assert wan_count == 1, f"Expected 1 WAN edge, got {wan_count}"
        assert trunk_count == 2, f"Expected 2 trunk edges, got {trunk_count}"
        assert access_count == 4, f"Expected 4 access edges, got {access_count}"
        assert mgmt_count == 1, f"Expected 1 mgmt edge, got {mgmt_count}"
    
    def test_topology_node_roles(self):
        """Test that nodes have correct roles assigned"""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{self.client_id}",
            headers=self.headers
        )
        data = response.json()
        
        nodes = data["nodes"]
        device_nodes = [n for n in nodes if n.get("id") != "internet"]
        
        roles = [n.get("role") for n in device_nodes]
        
        # Verify roles
        assert "gateway" in roles, "Missing gateway role"
        assert "core_switch" in roles, "Missing core_switch role"
        assert "access_switch" in roles, "Missing access_switch role"
        assert "management" in roles, "Missing management role"
    
    def test_topology_all_devices_reachable(self):
        """Test that all devices show as reachable"""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{self.client_id}",
            headers=self.headers
        )
        data = response.json()
        
        nodes = data["nodes"]
        device_nodes = [n for n in nodes if n.get("id") != "internet"]
        
        for node in device_nodes:
            assert node.get("reachable") == True, f"Device {node.get('id')} not reachable"
    
    def test_topology_requires_auth(self):
        """Test that topology endpoint requires authentication"""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{self.client_id}"
        )
        # API returns 403 Forbidden for unauthenticated requests
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
    
    def test_topology_invalid_client_returns_empty(self):
        """Test that invalid client ID returns empty topology"""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/invalid-client-id",
            headers=self.headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["nodes"] == [], "Expected empty nodes for invalid client"
        assert data["edges"] == [], "Expected empty edges for invalid client"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
