"""
Test discovered endpoints feature and 10G edge bug fix.
Iteration 28: Tests for discovered_endpoints in topology and 10G label bug fix.
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
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
    """Headers with auth token."""
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture(scope="module")
def topology_data(auth_headers):
    """Fetch topology data once for all tests."""
    response = requests.get(f"{BASE_URL}/api/network/topology/{CLIENT_ID}", headers=auth_headers)
    assert response.status_code == 200, f"Failed to get topology: {response.text}"
    return response.json()


class TestDiscoveredEndpointsCount:
    """Test that topology returns correct number of nodes including discovered endpoints."""
    
    def test_topology_returns_20_nodes(self, topology_data):
        """Topology should have 20 nodes: 9 managed (8 devices + internet) + 11 discovered endpoints."""
        nodes = topology_data.get("nodes", [])
        node_count = len(nodes)
        print(f"Total nodes: {node_count}")
        
        # List all nodes for debugging
        for n in nodes:
            print(f"  - {n.get('id')}: {n.get('name')} (role={n.get('role')}, type={n.get('type')}, layer={n.get('layer')})")
        
        assert node_count == 20, f"Expected 20 nodes, got {node_count}"
    
    def test_discovered_endpoints_count(self, topology_data):
        """Should have 11 discovered endpoints with role=discovered_endpoint."""
        nodes = topology_data.get("nodes", [])
        discovered = [n for n in nodes if n.get("role") == "discovered_endpoint"]
        print(f"Discovered endpoints: {len(discovered)}")
        for ep in discovered:
            print(f"  - {ep.get('name')}: mac={ep.get('mac')}, ip={ep.get('ip')}, switch_ip={ep.get('switch_ip')}, port={ep.get('switch_port')}")
        
        assert len(discovered) == 11, f"Expected 11 discovered endpoints, got {len(discovered)}"
    
    def test_discovered_endpoints_count_field(self, topology_data):
        """Topology response should include discovered_endpoints_count field."""
        count = topology_data.get("discovered_endpoints_count", 0)
        print(f"discovered_endpoints_count field: {count}")
        assert count == 11, f"Expected discovered_endpoints_count=11, got {count}"


class TestDiscoveredEndpointAttributes:
    """Test that discovered endpoints have required attributes."""
    
    def test_endpoints_have_required_fields(self, topology_data):
        """Each discovered endpoint must have: role, mac, ip, switch_ip, switch_port, layer=5."""
        nodes = topology_data.get("nodes", [])
        discovered = [n for n in nodes if n.get("role") == "discovered_endpoint"]
        
        required_fields = ["role", "mac", "switch_ip", "switch_port", "layer"]
        
        for ep in discovered:
            for field in required_fields:
                assert field in ep, f"Endpoint {ep.get('name')} missing field: {field}"
            
            # Layer must be 5
            assert ep.get("layer") == 5, f"Endpoint {ep.get('name')} has layer={ep.get('layer')}, expected 5"
            
            # Role must be discovered_endpoint
            assert ep.get("role") == "discovered_endpoint", f"Endpoint {ep.get('name')} has role={ep.get('role')}"
            
            print(f"✓ {ep.get('name')}: mac={ep.get('mac')}, layer={ep.get('layer')}, switch_port={ep.get('switch_port')}")


class TestEndpointsUnderSwitch4:
    """Test endpoints under switch .4 (192.168.1.4)."""
    
    def test_switch_4_has_correct_endpoints(self, topology_data):
        """Switch .4 should have: PC-RECEPTION, PC-ADMIN01, PRN-LASERJET-01."""
        nodes = topology_data.get("nodes", [])
        discovered = [n for n in nodes if n.get("role") == "discovered_endpoint"]
        
        switch_4_endpoints = [ep for ep in discovered if ep.get("switch_ip") == "192.168.1.4"]
        hostnames = [ep.get("hostname") or ep.get("name") for ep in switch_4_endpoints]
        
        print(f"Endpoints under switch .4: {hostnames}")
        
        expected = ["PC-RECEPTION", "PC-ADMIN01", "PRN-LASERJET-01"]
        for exp in expected:
            found = any(exp.lower() in (h or "").lower() for h in hostnames)
            assert found, f"Expected endpoint '{exp}' under switch .4, found: {hostnames}"


class TestEndpointsUnderSwitch5:
    """Test endpoints under switch .5 (192.168.1.5)."""
    
    def test_switch_5_has_correct_endpoints(self, topology_data):
        """Switch .5 should have: SRV-DC01, SRV-FILE01."""
        nodes = topology_data.get("nodes", [])
        discovered = [n for n in nodes if n.get("role") == "discovered_endpoint"]
        
        switch_5_endpoints = [ep for ep in discovered if ep.get("switch_ip") == "192.168.1.5"]
        hostnames = [ep.get("hostname") or ep.get("name") for ep in switch_5_endpoints]
        
        print(f"Endpoints under switch .5: {hostnames}")
        
        expected = ["SRV-DC01", "SRV-FILE01"]
        for exp in expected:
            found = any(exp.lower() in (h or "").lower() for h in hostnames)
            assert found, f"Expected endpoint '{exp}' under switch .5, found: {hostnames}"


class TestEndpointsUnderSwitch6:
    """Test endpoints under switch .6 (192.168.1.6)."""
    
    def test_switch_6_has_correct_endpoints(self, topology_data):
        """Switch .6 should have: PC-UFFICIO03, PC-UFFICIO04."""
        nodes = topology_data.get("nodes", [])
        discovered = [n for n in nodes if n.get("role") == "discovered_endpoint"]
        
        switch_6_endpoints = [ep for ep in discovered if ep.get("switch_ip") == "192.168.1.6"]
        hostnames = [ep.get("hostname") or ep.get("name") for ep in switch_6_endpoints]
        
        print(f"Endpoints under switch .6: {hostnames}")
        
        expected = ["PC-UFFICIO03", "PC-UFFICIO04"]
        for exp in expected:
            found = any(exp.lower() in (h or "").lower() for h in hostnames)
            assert found, f"Expected endpoint '{exp}' under switch .6, found: {hostnames}"


class TestEndpointsUnderSwitch7:
    """Test endpoints under switch .7 (192.168.1.7)."""
    
    def test_switch_7_has_correct_endpoints(self, topology_data):
        """Switch .7 should have: IPCAM-BOILER, NAS-BACKUP01."""
        nodes = topology_data.get("nodes", [])
        discovered = [n for n in nodes if n.get("role") == "discovered_endpoint"]
        
        switch_7_endpoints = [ep for ep in discovered if ep.get("switch_ip") == "192.168.1.7"]
        hostnames = [ep.get("hostname") or ep.get("name") for ep in switch_7_endpoints]
        
        print(f"Endpoints under switch .7: {hostnames}")
        
        expected = ["IPCAM-BOILER", "NAS-BACKUP01"]
        for exp in expected:
            found = any(exp.lower() in (h or "").lower() for h in hostnames)
            assert found, f"Expected endpoint '{exp}' under switch .7, found: {hostnames}"


class TestEndpointsUnderHPECore:
    """Test endpoint under HPE Core .2 (192.168.1.2)."""
    
    def test_hpe_core_has_esxi_endpoint(self, topology_data):
        """HPE Core .2 should have: SRV-ESXI01."""
        nodes = topology_data.get("nodes", [])
        discovered = [n for n in nodes if n.get("role") == "discovered_endpoint"]
        
        hpe_endpoints = [ep for ep in discovered if ep.get("switch_ip") == "192.168.1.2"]
        hostnames = [ep.get("hostname") or ep.get("name") for ep in hpe_endpoints]
        
        print(f"Endpoints under HPE Core .2: {hostnames}")
        
        found = any("SRV-ESXI01".lower() in (h or "").lower() for h in hostnames)
        assert found, f"Expected endpoint 'SRV-ESXI01' under HPE Core .2, found: {hostnames}"


class TestEndpointsUnderNetgearArmadio:
    """Test endpoint under Netgear Armadio .3 (192.168.1.3)."""
    
    def test_netgear_has_wifi_ap_endpoint(self, topology_data):
        """Netgear Armadio .3 should have: AP-WIFI-ARMADIO."""
        nodes = topology_data.get("nodes", [])
        discovered = [n for n in nodes if n.get("role") == "discovered_endpoint"]
        
        netgear_endpoints = [ep for ep in discovered if ep.get("switch_ip") == "192.168.1.3"]
        hostnames = [ep.get("hostname") or ep.get("name") for ep in netgear_endpoints]
        
        print(f"Endpoints under Netgear .3: {hostnames}")
        
        found = any("AP-WIFI-ARMADIO".lower() in (h or "").lower() for h in hostnames)
        assert found, f"Expected endpoint 'AP-WIFI-ARMADIO' under Netgear .3, found: {hostnames}"


class TestBugFix10GLabels:
    """Test bug fix: inferred edges to .6 and .7 should NOT have 10G labels."""
    
    def test_edges_to_switch_6_no_10g_label(self, topology_data):
        """Edges to switch .6 should NOT have '10G' in label - should be type 'access'."""
        edges = topology_data.get("edges", [])
        
        edges_to_6 = [e for e in edges if e.get("to") == "192.168.1.6"]
        print(f"Edges to switch .6: {edges_to_6}")
        
        for edge in edges_to_6:
            label = edge.get("label", "")
            edge_type = edge.get("type", "")
            source = edge.get("source", "inferred")
            
            # Only MAC table edges can have 10G
            if source != "mac_table":
                assert "10G" not in label, f"Edge to .6 has '10G' in label but source={source}: {edge}"
                assert edge_type == "access", f"Edge to .6 should be type='access', got '{edge_type}'"
            
            print(f"  ✓ Edge {edge.get('from')} -> .6: type={edge_type}, label='{label}', source={source}")
    
    def test_edges_to_switch_7_no_10g_label(self, topology_data):
        """Edges to switch .7 should NOT have '10G' in label - should be type 'access'."""
        edges = topology_data.get("edges", [])
        
        edges_to_7 = [e for e in edges if e.get("to") == "192.168.1.7"]
        print(f"Edges to switch .7: {edges_to_7}")
        
        for edge in edges_to_7:
            label = edge.get("label", "")
            edge_type = edge.get("type", "")
            source = edge.get("source", "inferred")
            
            # Only MAC table edges can have 10G
            if source != "mac_table":
                assert "10G" not in label, f"Edge to .7 has '10G' in label but source={source}: {edge}"
                assert edge_type == "access", f"Edge to .7 should be type='access', got '{edge_type}'"
            
            print(f"  ✓ Edge {edge.get('from')} -> .7: type={edge_type}, label='{label}', source={source}")
    
    def test_no_inferred_edges_with_10g_uplink(self, topology_data):
        """No inferred edges should have '10G Uplink' label - only MAC table edges can have 10G."""
        edges = topology_data.get("edges", [])
        
        for edge in edges:
            source = edge.get("source", "inferred")
            label = edge.get("label", "")
            
            if source == "inferred" or source is None:
                assert "10G" not in label, f"Inferred edge has '10G' in label: {edge}"
        
        print("✓ No inferred edges have '10G' labels")


class TestMACTableEdgesHave10G:
    """Test that MAC table edges to .4 and .5 DO have 10G labels."""
    
    def test_mac_edges_to_switch_4_have_10g(self, topology_data):
        """MAC table edges to switch .4 should have 10G label."""
        edges = topology_data.get("edges", [])
        
        mac_edges_to_4 = [e for e in edges if e.get("to") == "192.168.1.4" and e.get("source") == "mac_table"]
        print(f"MAC edges to switch .4: {mac_edges_to_4}")
        
        if mac_edges_to_4:
            for edge in mac_edges_to_4:
                label = edge.get("label", "")
                assert "10G" in label, f"MAC edge to .4 should have '10G' in label: {edge}"
                print(f"  ✓ MAC edge to .4: label='{label}'")
        else:
            print("  Note: No MAC table edges to .4 found (may be LLDP or inferred)")
    
    def test_mac_edges_to_switch_5_have_10g(self, topology_data):
        """MAC table edges to switch .5 should have 10G label."""
        edges = topology_data.get("edges", [])
        
        mac_edges_to_5 = [e for e in edges if e.get("to") == "192.168.1.5" and e.get("source") == "mac_table"]
        print(f"MAC edges to switch .5: {mac_edges_to_5}")
        
        if mac_edges_to_5:
            for edge in mac_edges_to_5:
                label = edge.get("label", "")
                assert "10G" in label, f"MAC edge to .5 should have '10G' in label: {edge}"
                print(f"  ✓ MAC edge to .5: label='{label}'")
        else:
            print("  Note: No MAC table edges to .5 found (may be LLDP or inferred)")


class TestMACDiscoveryEdges:
    """Test that mac_discovery edges have port number labels."""
    
    def test_mac_discovery_edges_have_port_labels(self, topology_data):
        """Edges with source=mac_discovery should have 'Port X' in label."""
        edges = topology_data.get("edges", [])
        
        mac_discovery_edges = [e for e in edges if e.get("source") == "mac_discovery"]
        print(f"MAC discovery edges count: {len(mac_discovery_edges)}")
        
        for edge in mac_discovery_edges:
            label = edge.get("label", "")
            assert "Port" in label, f"MAC discovery edge should have 'Port' in label: {edge}"
            print(f"  ✓ {edge.get('from')} -> {edge.get('to')}: label='{label}'")


class TestLayoutEndpoints:
    """Test that layout save/delete still work."""
    
    def test_save_layout_works(self, auth_headers, topology_data):
        """POST /api/network/topology/{client_id}/layout should work."""
        # Use existing nodes/edges
        payload = {
            "nodes": [{"id": n.get("id"), "position": {"x": 100, "y": 100}} for n in topology_data.get("nodes", [])[:3]],
            "edges": []
        }
        
        response = requests.post(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}/layout",
            headers=auth_headers,
            json=payload
        )
        
        print(f"Save layout response: {response.status_code} - {response.text}")
        assert response.status_code == 200
        assert response.json().get("status") == "ok"
    
    def test_delete_layout_works(self, auth_headers):
        """DELETE /api/network/topology/{client_id}/layout should work."""
        response = requests.delete(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}/layout",
            headers=auth_headers
        )
        
        print(f"Delete layout response: {response.status_code} - {response.text}")
        assert response.status_code == 200
        assert response.json().get("status") == "ok"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
