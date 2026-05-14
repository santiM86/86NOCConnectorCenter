"""
Test cases for Network Topology Layout Save/Reset Feature
Tests:
- GET /api/network/topology/{client_id} - returns topology with has_custom_layout flag
- POST /api/network/topology/{client_id}/layout - saves custom layout
- DELETE /api/network/topology/{client_id}/layout - resets custom layout
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"  # 86BIT_Office client


class TestTopologyLayoutEndpoints:
    """Tests for topology layout save/reset endpoints"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup - get auth token"""
        # Login with provided credentials
        login_response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": "admin@86bit.it", "password": "password"}
        )
        if login_response.status_code != 200:
            # Try alternate password
            login_response = requests.post(
                f"{BASE_URL}/api/auth/login",
                json={"email": "admin@86bit.it", "password": "admin123"}
            )
        assert login_response.status_code == 200, f"Login failed: {login_response.text}"
        self.token = login_response.json()["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def test_get_topology_returns_200(self):
        """Test GET /api/network/topology/{client_id} returns 200"""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}",
            headers=self.headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"GET topology returned 200 OK")
    
    def test_get_topology_has_required_fields(self):
        """Test topology response has all required fields including has_custom_layout"""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}",
            headers=self.headers
        )
        data = response.json()
        
        # Check required fields
        assert "nodes" in data, "Missing 'nodes' field"
        assert "edges" in data, "Missing 'edges' field"
        assert "health" in data, "Missing 'health' field"
        assert "has_custom_layout" in data, "Missing 'has_custom_layout' field"
        assert "client_id" in data, "Missing 'client_id' field"
        assert "client_name" in data, "Missing 'client_name' field"
        
        print(f"Topology has all required fields")
        print(f"  - nodes: {len(data['nodes'])}")
        print(f"  - edges: {len(data['edges'])}")
        print(f"  - health score: {data['health'].get('score', 'N/A')}")
        print(f"  - has_custom_layout: {data['has_custom_layout']}")
    
    def test_get_topology_health_score(self):
        """Test health score is present and valid"""
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}",
            headers=self.headers
        )
        data = response.json()
        health = data.get("health", {})
        
        assert "score" in health, "Missing 'score' in health"
        assert 0 <= health["score"] <= 100, f"Score {health['score']} out of range"
        
        print(f"Health score: {health['score']}%")
        print(f"  - devices_total: {health.get('devices_total', 'N/A')}")
        print(f"  - devices_online: {health.get('devices_online', 'N/A')}")
    
    def test_save_layout_returns_200(self):
        """Test POST /api/network/topology/{client_id}/layout saves layout"""
        # First get current topology to get nodes/edges
        get_response = requests.get(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}",
            headers=self.headers
        )
        assert get_response.status_code == 200
        topo = get_response.json()
        
        # Prepare layout payload with positions
        nodes_with_positions = []
        for i, node in enumerate(topo.get("nodes", [])):
            nodes_with_positions.append({
                "id": node.get("id"),
                "position": {"x": 100 + (i * 150), "y": 100 + (i % 3) * 120},
                "name": node.get("name"),
                "ip": node.get("ip"),
                "type": node.get("type"),
                "reachable": node.get("reachable"),
                "virtual": node.get("virtual"),
                "role": node.get("role"),
            })
        
        edges_payload = []
        for edge in topo.get("edges", []):
            edges_payload.append({
                "id": edge.get("id") or f"e-{edge.get('from')}-{edge.get('to')}",
                "from": edge.get("from"),
                "to": edge.get("to"),
                "type": edge.get("type", "custom"),
                "label": edge.get("label", ""),
            })
        
        payload = {
            "nodes": nodes_with_positions,
            "edges": edges_payload,
            "layers": topo.get("layers", [])
        }
        
        # Save layout
        response = requests.post(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}/layout",
            headers=self.headers,
            json=payload
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("status") == "ok", f"Expected status 'ok', got {data.get('status')}"
        print(f"Layout saved successfully: {data.get('message')}")
    
    def test_after_save_has_custom_layout_true(self):
        """Test that after saving, GET returns has_custom_layout=True"""
        # First save a layout
        get_response = requests.get(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}",
            headers=self.headers
        )
        topo = get_response.json()
        
        nodes_with_positions = []
        for i, node in enumerate(topo.get("nodes", [])):
            nodes_with_positions.append({
                "id": node.get("id"),
                "position": {"x": 200 + (i * 100), "y": 150 + (i % 4) * 100},
                "name": node.get("name"),
                "ip": node.get("ip"),
                "type": node.get("type"),
            })
        
        payload = {
            "nodes": nodes_with_positions,
            "edges": topo.get("edges", []),
        }
        
        save_response = requests.post(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}/layout",
            headers=self.headers,
            json=payload
        )
        assert save_response.status_code == 200
        
        # Now GET and verify has_custom_layout is True
        verify_response = requests.get(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}",
            headers=self.headers
        )
        assert verify_response.status_code == 200
        data = verify_response.json()
        
        assert data.get("has_custom_layout") == True, f"Expected has_custom_layout=True, got {data.get('has_custom_layout')}"
        print(f"Verified has_custom_layout=True after save")
    
    def test_reset_layout_returns_200(self):
        """Test DELETE /api/network/topology/{client_id}/layout resets layout"""
        response = requests.delete(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}/layout",
            headers=self.headers
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("status") == "ok", f"Expected status 'ok', got {data.get('status')}"
        print(f"Layout reset successfully: {data.get('message')}")
    
    def test_after_reset_has_custom_layout_false(self):
        """Test that after reset, GET returns has_custom_layout=False"""
        # First reset the layout
        reset_response = requests.delete(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}/layout",
            headers=self.headers
        )
        assert reset_response.status_code == 200
        
        # Now GET and verify has_custom_layout is False
        verify_response = requests.get(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}",
            headers=self.headers
        )
        assert verify_response.status_code == 200
        data = verify_response.json()
        
        assert data.get("has_custom_layout") == False, f"Expected has_custom_layout=False, got {data.get('has_custom_layout')}"
        print(f"Verified has_custom_layout=False after reset")
    
    def test_topology_requires_auth(self):
        """Test that topology endpoints require authentication"""
        # GET without auth
        response = requests.get(f"{BASE_URL}/api/network/topology/{CLIENT_ID}")
        assert response.status_code in [401, 403], f"GET: Expected 401/403, got {response.status_code}"
        
        # POST without auth
        response = requests.post(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}/layout",
            json={"nodes": [], "edges": []}
        )
        assert response.status_code in [401, 403], f"POST: Expected 401/403, got {response.status_code}"
        
        # DELETE without auth
        response = requests.delete(f"{BASE_URL}/api/network/topology/{CLIENT_ID}/layout")
        assert response.status_code in [401, 403], f"DELETE: Expected 401/403, got {response.status_code}"
        
        print("All endpoints correctly require authentication")
    
    def test_full_save_reset_cycle(self):
        """Test complete save -> verify -> reset -> verify cycle"""
        # Step 1: Reset to ensure clean state
        requests.delete(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}/layout",
            headers=self.headers
        )
        
        # Step 2: Verify has_custom_layout is False
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}",
            headers=self.headers
        )
        data = response.json()
        assert data.get("has_custom_layout") == False, "Initial state should be has_custom_layout=False"
        print("Step 1: Initial state has_custom_layout=False ✓")
        
        # Step 3: Save a custom layout
        nodes_payload = []
        for i, node in enumerate(data.get("nodes", [])):
            nodes_payload.append({
                "id": node.get("id"),
                "position": {"x": 50 + (i * 180), "y": 80 + (i % 5) * 140},
                "name": node.get("name"),
                "ip": node.get("ip"),
                "type": node.get("type"),
            })
        
        save_response = requests.post(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}/layout",
            headers=self.headers,
            json={"nodes": nodes_payload, "edges": data.get("edges", [])}
        )
        assert save_response.status_code == 200
        print("Step 2: Layout saved ✓")
        
        # Step 4: Verify has_custom_layout is True
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}",
            headers=self.headers
        )
        data = response.json()
        assert data.get("has_custom_layout") == True, "After save should be has_custom_layout=True"
        print("Step 3: Verified has_custom_layout=True ✓")
        
        # Step 5: Reset layout
        reset_response = requests.delete(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}/layout",
            headers=self.headers
        )
        assert reset_response.status_code == 200
        print("Step 4: Layout reset ✓")
        
        # Step 6: Verify has_custom_layout is False again
        response = requests.get(
            f"{BASE_URL}/api/network/topology/{CLIENT_ID}",
            headers=self.headers
        )
        data = response.json()
        assert data.get("has_custom_layout") == False, "After reset should be has_custom_layout=False"
        print("Step 5: Verified has_custom_layout=False after reset ✓")
        
        print("\nFull save/reset cycle completed successfully!")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
