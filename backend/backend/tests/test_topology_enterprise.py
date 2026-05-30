"""
Test suite for Enterprise Network Topology with LLDP and MAC Table integration.
Tests the topology inference engine, LLDP edges, MAC edges with 10G labels, and layout management.
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token for API calls."""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "admin@86bit.it",
        "password": "password"
    })
    if response.status_code == 200:
        return response.json().get("token")
    pytest.skip("Authentication failed - skipping tests")


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Return headers with auth token."""
    return {
        "Authorization": f"Bearer {auth_token}",
        "Content-Type": "application/json"
    }


class TestTopologyHierarchy:
    """Test topology hierarchy: Internet -> Firewall -> Core -> Distribution -> Access -> iLO"""
    
    def test_topology_returns_correct_layers(self, auth_headers):
        """Verify topology has correct 6-layer hierarchy."""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        # Verify layers exist
        assert "layers" in data
        layers = data["layers"]
        assert len(layers) == 6, f"Expected 6 layers, got {len(layers)}"
        
        # Verify layer names
        layer_names = [l["name"] for l in layers]
        assert "WAN" in layer_names
        assert "Firewall / Router" in layer_names
        assert "Core Switch" in layer_names
        assert "Distribuzione" in layer_names
        assert "Accesso / Server" in layer_names
        assert "Management" in layer_names
    
    def test_internet_node_at_layer_0(self, auth_headers):
        """Verify Internet virtual node at layer 0."""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}",
            headers=auth_headers
        )
        data = response.json()
        
        internet_node = next((n for n in data["nodes"] if n["id"] == "internet"), None)
        assert internet_node is not None
        assert internet_node["layer"] == 0
        assert internet_node["virtual"] == True
        assert internet_node["type"] == "internet"
    
    def test_zyxel_firewall_at_layer_1(self, auth_headers):
        """Verify Zyxel Firewall at layer 1 (gateway)."""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}",
            headers=auth_headers
        )
        data = response.json()
        
        firewall = next((n for n in data["nodes"] if n.get("ip") == "192.168.1.254"), None)
        assert firewall is not None
        assert firewall["layer"] == 1
        assert firewall["role"] == "gateway"
        assert firewall["type"] == "firewall"
        assert "Zyxel" in firewall["name"]
    
    def test_hpe_core_switch_at_layer_2(self, auth_headers):
        """Verify HPE Core Switch at layer 2."""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}",
            headers=auth_headers
        )
        data = response.json()
        
        core = next((n for n in data["nodes"] if n.get("ip") == "192.168.1.2"), None)
        assert core is not None
        assert core["layer"] == 2
        assert core["role"] == "core_switch"
        assert "HPE" in core["name"]
        assert "Armadio" in core["name"]
    
    def test_netgear_distribution_at_layer_3(self, auth_headers):
        """Verify Netgear Distribution Switch at layer 3."""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}",
            headers=auth_headers
        )
        data = response.json()
        
        distrib = next((n for n in data["nodes"] if n.get("ip") == "192.168.1.3"), None)
        assert distrib is not None
        assert distrib["layer"] == 3
        assert distrib["role"] == "distribution_switch"
        assert "NETGEAR" in distrib["name"]
        assert "Armadio" in distrib["name"]
    
    def test_access_switches_at_layer_4(self, auth_headers):
        """Verify 4 Access Switches at layer 4."""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}",
            headers=auth_headers
        )
        data = response.json()
        
        access_switches = [n for n in data["nodes"] if n.get("role") == "access_switch"]
        assert len(access_switches) == 4, f"Expected 4 access switches, got {len(access_switches)}"
        
        # Verify all are at layer 4
        for sw in access_switches:
            assert sw["layer"] == 4
            assert "NETGEAR" in sw["name"]
    
    def test_ilo_management_at_layer_5(self, auth_headers):
        """Verify iLO Management at layer 5."""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}",
            headers=auth_headers
        )
        data = response.json()
        
        ilo = next((n for n in data["nodes"] if n.get("ip") == "192.168.1.8"), None)
        assert ilo is not None
        assert ilo["layer"] == 5
        assert ilo["role"] == "management"
        assert ilo["type"] == "ilo"


class TestLLDPEdges:
    """Test LLDP-based edges (real physical connections)."""
    
    def test_lldp_count_in_topology(self, auth_headers):
        """Verify lldp_count field in topology response."""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}",
            headers=auth_headers
        )
        data = response.json()
        
        assert "lldp_count" in data
        assert data["lldp_count"] == 2
    
    def test_lldp_edge_zyxel_to_hpe(self, auth_headers):
        """Verify LLDP edge from Zyxel Firewall to HPE Core."""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}",
            headers=auth_headers
        )
        data = response.json()
        
        # Find edge from 192.168.1.254 to 192.168.1.2
        lldp_edge = next((e for e in data["edges"] 
                         if e.get("source") == "lldp" 
                         and "192.168.1.254" in [e["from"], e["to"]]
                         and "192.168.1.2" in [e["from"], e["to"]]), None)
        
        assert lldp_edge is not None, "LLDP edge Zyxel->HPE not found"
        assert lldp_edge["type"] == "lldp"
        assert "LAN1" in lldp_edge["label"]
        assert "Port 1" in lldp_edge["label"]
    
    def test_lldp_edge_hpe_to_netgear_armadio(self, auth_headers):
        """Verify LLDP edge from HPE Core to Netgear Distribution."""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}",
            headers=auth_headers
        )
        data = response.json()
        
        # Find edge from 192.168.1.2 to 192.168.1.3
        lldp_edge = next((e for e in data["edges"] 
                         if e.get("source") == "lldp" 
                         and "192.168.1.2" in [e["from"], e["to"]]
                         and "192.168.1.3" in [e["from"], e["to"]]), None)
        
        assert lldp_edge is not None, "LLDP edge HPE->Netgear Armadio not found"
        assert lldp_edge["type"] == "lldp"
        assert "Port 1" in lldp_edge["label"]
        assert "Port 24" in lldp_edge["label"]
    
    def test_get_lldp_raw_data(self, auth_headers):
        """Test GET /api/network/lldp/{client_id} returns raw LLDP data."""
        response = requests.get(
            f"{BASE_URL}/api/network/lldp/{CLIENT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        
        assert data["client_id"] == CLIENT_ID
        assert data["count"] == 2
        assert len(data["neighbors"]) == 2


class TestMACEdges:
    """Test MAC table-based edges with 10G speed labels."""
    
    def test_mac_connections_count_in_topology(self, auth_headers):
        """Verify mac_connections_count field in topology response."""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}",
            headers=auth_headers
        )
        data = response.json()
        
        assert "mac_connections_count" in data
        assert data["mac_connections_count"] == 2
    
    def test_mac_edge_port_9_10g(self, auth_headers):
        """Verify MAC edge on Port 9 with 10G label."""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}",
            headers=auth_headers
        )
        data = response.json()
        
        # Find MAC edge with Port 9
        mac_edge = next((e for e in data["edges"] 
                        if e.get("source") == "mac_table" 
                        and "Port 9" in e.get("label", "")), None)
        
        assert mac_edge is not None, "MAC edge Port 9 not found"
        assert mac_edge["from"] == "192.168.1.3"  # Distribution switch
        assert mac_edge["to"] == "192.168.1.4"    # Access switch
        assert "10G" in mac_edge["label"]
        assert mac_edge["type"] == "trunk"
    
    def test_mac_edge_port_10_10g(self, auth_headers):
        """Verify MAC edge on Port 10 with 10G label."""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}",
            headers=auth_headers
        )
        data = response.json()
        
        # Find MAC edge with Port 10
        mac_edge = next((e for e in data["edges"] 
                        if e.get("source") == "mac_table" 
                        and "Port 10" in e.get("label", "")), None)
        
        assert mac_edge is not None, "MAC edge Port 10 not found"
        assert mac_edge["from"] == "192.168.1.3"  # Distribution switch
        assert mac_edge["to"] == "192.168.1.5"    # Access switch
        assert "10G" in mac_edge["label"]
        assert mac_edge["type"] == "trunk"


class TestInferredEdges:
    """Test inferred edges for devices without LLDP/MAC data."""
    
    def test_inferred_edge_for_192_168_1_6(self, auth_headers):
        """Verify inferred edge for .6 access switch has 10G Uplink label."""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}",
            headers=auth_headers
        )
        data = response.json()
        
        # Find edge to 192.168.1.6
        edge = next((e for e in data["edges"] 
                    if e["to"] == "192.168.1.6"), None)
        
        assert edge is not None, "Edge to 192.168.1.6 not found"
        assert edge["from"] == "192.168.1.3"  # Should connect to distribution
        assert edge["label"] == "10G Uplink"
        assert edge["type"] == "trunk"
    
    def test_inferred_edge_for_192_168_1_7(self, auth_headers):
        """Verify inferred edge for .7 access switch has 10G Uplink label."""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}",
            headers=auth_headers
        )
        data = response.json()
        
        # Find edge to 192.168.1.7
        edge = next((e for e in data["edges"] 
                    if e["to"] == "192.168.1.7"), None)
        
        assert edge is not None, "Edge to 192.168.1.7 not found"
        assert edge["from"] == "192.168.1.3"  # Should connect to distribution
        assert edge["label"] == "10G Uplink"
        assert edge["type"] == "trunk"


class TestLayoutManagement:
    """Test layout save/reset functionality."""
    
    def test_save_layout(self, auth_headers):
        """Test POST /api/network/topology/{client_id}/layout saves layout."""
        payload = {
            "nodes": [
                {"id": "internet", "position": {"x": 500, "y": 50}, "name": "Internet / WAN", "type": "internet"},
                {"id": "192.168.1.254", "position": {"x": 500, "y": 150}, "name": "Zyxel", "type": "firewall"}
            ],
            "edges": [
                {"id": "e-internet-254", "from": "internet", "to": "192.168.1.254", "type": "wan"}
            ]
        }
        
        response = requests.post(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}/layout",
            headers=auth_headers,
            json=payload
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "salvato" in data["message"].lower()
    
    def test_topology_has_custom_layout_after_save(self, auth_headers):
        """Verify has_custom_layout is True after saving."""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}",
            headers=auth_headers
        )
        data = response.json()
        assert data["has_custom_layout"] == True
    
    def test_reset_layout(self, auth_headers):
        """Test DELETE /api/network/topology/{client_id}/layout resets layout."""
        response = requests.delete(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}/layout",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "resettato" in data["message"].lower()
    
    def test_topology_no_custom_layout_after_reset(self, auth_headers):
        """Verify has_custom_layout is False after reset."""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}",
            headers=auth_headers
        )
        data = response.json()
        assert data["has_custom_layout"] == False


class TestHealthScore:
    """Test health score calculation."""
    
    def test_health_score_present(self, auth_headers):
        """Verify health score is present in topology response."""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}",
            headers=auth_headers
        )
        data = response.json()
        
        assert "health" in data
        health = data["health"]
        assert "score" in health
        assert "devices_total" in health
        assert "devices_online" in health
        assert health["devices_total"] == 8
        assert health["devices_online"] == 8
        assert health["score"] >= 0 and health["score"] <= 100
