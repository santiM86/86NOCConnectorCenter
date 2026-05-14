"""
Printer Management API Tests - Iteration 32
Tests for SNMP-based printer monitoring with toner, page counts, and status.
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestPrinterAPIs:
    """Printer Management endpoint tests"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup: Get auth token and client_id"""
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # Login to get token
        login_response = self.session.post(f"{BASE_URL}/api/auth/login", json={
            "email": "admin@86bit.it",
            "password": "password"
        })
        assert login_response.status_code == 200, f"Login failed: {login_response.text}"
        token = login_response.json().get("token")
        assert token, "No token received"
        self.session.headers.update({"Authorization": f"Bearer {token}"})
        
        # Get first client_id
        clients_response = self.session.get(f"{BASE_URL}/api/clients")
        assert clients_response.status_code == 200, f"Failed to get clients: {clients_response.text}"
        clients_data = clients_response.json()
        clients = clients_data.get("clients", clients_data) if isinstance(clients_data, dict) else clients_data
        assert len(clients) > 0, "No clients found"
        self.client_id = clients[0]["id"]
        print(f"Using client_id: {self.client_id}")
    
    # ==================== Dashboard API Tests ====================
    
    def test_printer_dashboard_returns_correct_structure(self):
        """GET /api/printers/dashboard/{client_id} - Returns dashboard with correct structure"""
        response = self.session.get(f"{BASE_URL}/api/printers/dashboard/{self.client_id}")
        assert response.status_code == 200, f"Dashboard failed: {response.text}"
        
        data = response.json()
        # Verify all required fields exist
        assert "total" in data, "Missing 'total' field"
        assert "online" in data, "Missing 'online' field"
        assert "offline" in data, "Missing 'offline' field"
        assert "low_toner_count" in data, "Missing 'low_toner_count' field"
        assert "total_pages" in data, "Missing 'total_pages' field"
        assert "printers" in data, "Missing 'printers' field"
        
        # Verify types
        assert isinstance(data["total"], int), "total should be int"
        assert isinstance(data["online"], int), "online should be int"
        assert isinstance(data["offline"], int), "offline should be int"
        assert isinstance(data["low_toner_count"], int), "low_toner_count should be int"
        assert isinstance(data["total_pages"], int), "total_pages should be int"
        assert isinstance(data["printers"], list), "printers should be list"
        
        print(f"Dashboard: {data['total']} printers, {data['online']} online, {data['offline']} offline")
        print(f"Low toner: {data['low_toner_count']}, Total pages: {data['total_pages']}")
    
    def test_printer_dashboard_has_demo_data(self):
        """Verify demo printer data exists (4 printers seeded)"""
        response = self.session.get(f"{BASE_URL}/api/printers/dashboard/{self.client_id}")
        assert response.status_code == 200
        
        data = response.json()
        # Demo data should have 4 printers
        if data["total"] == 0:
            # Seed demo data if not present
            seed_response = self.session.post(f"{BASE_URL}/api/printers/seed-demo/{self.client_id}")
            assert seed_response.status_code == 200, f"Seed failed: {seed_response.text}"
            
            # Re-fetch dashboard
            response = self.session.get(f"{BASE_URL}/api/printers/dashboard/{self.client_id}")
            data = response.json()
        
        assert data["total"] == 4, f"Expected 4 printers, got {data['total']}"
        assert data["online"] == 3, f"Expected 3 online, got {data['online']}"
        assert data["offline"] == 1, f"Expected 1 offline, got {data['offline']}"
        print(f"Demo data verified: {data['total']} printers")
    
    def test_printer_dashboard_low_toner_alerts(self):
        """Verify low toner alerts are returned correctly"""
        response = self.session.get(f"{BASE_URL}/api/printers/dashboard/{self.client_id}")
        assert response.status_code == 200
        
        data = response.json()
        low_toner = data.get("low_toner", [])
        
        # Demo data has printers with low toner (<=15%)
        # HP M479fdw has Magenta at 10%, Brother has Black at 5%, Ricoh has Cyan at 15%
        assert len(low_toner) >= 3, f"Expected at least 3 low toner alerts, got {len(low_toner)}"
        
        for alert in low_toner:
            assert "printer_name" in alert, "Missing printer_name in low toner alert"
            assert "supply_name" in alert, "Missing supply_name in low toner alert"
            assert "level_pct" in alert, "Missing level_pct in low toner alert"
            assert alert["level_pct"] <= 15, f"Level {alert['level_pct']}% should be <= 15%"
            print(f"Low toner: {alert['supply_name']} at {alert['level_pct']}% on {alert['printer_name']}")
    
    def test_printer_dashboard_total_pages(self):
        """Verify total pages calculation"""
        response = self.session.get(f"{BASE_URL}/api/printers/dashboard/{self.client_id}")
        assert response.status_code == 200
        
        data = response.json()
        # Demo data: 45230 + 28750 + 67100 + 124500 = 265580
        expected_pages = 265580
        assert data["total_pages"] == expected_pages, f"Expected {expected_pages} pages, got {data['total_pages']}"
        print(f"Total pages: {data['total_pages']}")
    
    # ==================== List Printers API Tests ====================
    
    def test_list_printers_returns_all(self):
        """GET /api/printers/{client_id} - Returns all printers for client"""
        response = self.session.get(f"{BASE_URL}/api/printers/{self.client_id}")
        assert response.status_code == 200, f"List printers failed: {response.text}"
        
        printers = response.json()
        assert isinstance(printers, list), "Response should be a list"
        assert len(printers) == 4, f"Expected 4 printers, got {len(printers)}"
        
        for printer in printers:
            assert "device_ip" in printer, "Missing device_ip"
            assert "device_name" in printer, "Missing device_name"
            assert "reachable" in printer, "Missing reachable"
            assert "supplies" in printer, "Missing supplies"
            print(f"Printer: {printer['device_name']} ({printer['device_ip']}) - {'Online' if printer['reachable'] else 'Offline'}")
    
    def test_list_printers_sorted_by_name(self):
        """Verify printers are sorted by device_name"""
        response = self.session.get(f"{BASE_URL}/api/printers/{self.client_id}")
        assert response.status_code == 200
        
        printers = response.json()
        names = [p["device_name"] for p in printers]
        assert names == sorted(names), f"Printers not sorted by name: {names}"
        print(f"Printers sorted: {names}")
    
    # ==================== Printer Detail API Tests ====================
    
    def test_get_printer_detail(self):
        """GET /api/printers/{client_id}/{device_ip} - Returns printer detail with history"""
        device_ip = "192.168.1.30"  # HP LaserJet Pro M404dn
        response = self.session.get(f"{BASE_URL}/api/printers/{self.client_id}/{device_ip}")
        assert response.status_code == 200, f"Get printer detail failed: {response.text}"
        
        data = response.json()
        assert "printer" in data, "Missing 'printer' field"
        assert "supply_history" in data, "Missing 'supply_history' field"
        
        printer = data["printer"]
        assert printer["device_ip"] == device_ip, f"Wrong device_ip: {printer['device_ip']}"
        assert printer["device_name"] == "HP LaserJet Pro M404dn - Reception"
        assert printer["model"] == "HP LaserJet Pro M404dn"
        assert printer["serial"] == "CNBJR8G05K"
        assert printer["reachable"] == True
        assert printer["page_count"] == 45230
        
        print(f"Printer detail: {printer['device_name']}, {printer['page_count']} pages")
    
    def test_get_printer_detail_supplies(self):
        """Verify printer supplies have correct color info"""
        device_ip = "192.168.1.31"  # HP Color LaserJet M479fdw (has color toners)
        response = self.session.get(f"{BASE_URL}/api/printers/{self.client_id}/{device_ip}")
        assert response.status_code == 200
        
        printer = response.json()["printer"]
        supplies = printer["supplies"]
        
        # Should have 4 toners: Black, Cyan, Magenta, Yellow
        assert len(supplies) == 4, f"Expected 4 supplies, got {len(supplies)}"
        
        colors_found = set()
        for supply in supplies:
            assert "color_name" in supply, "Missing color_name"
            assert "color_hex" in supply, "Missing color_hex"
            assert "level_pct" in supply, "Missing level_pct"
            colors_found.add(supply["color_name"])
            print(f"Supply: {supply['name']} - {supply['color_name']} at {supply['level_pct']}%")
        
        expected_colors = {"black", "cyan", "magenta", "yellow"}
        assert colors_found == expected_colors, f"Missing colors: {expected_colors - colors_found}"
    
    def test_get_printer_detail_not_found(self):
        """GET /api/printers/{client_id}/{device_ip} - Returns 404 for non-existent printer"""
        response = self.session.get(f"{BASE_URL}/api/printers/{self.client_id}/192.168.99.99")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("404 returned for non-existent printer")
    
    # ==================== Seed Demo API Tests ====================
    
    def test_seed_demo_printers(self):
        """POST /api/printers/seed-demo/{client_id} - Seeds demo printer data"""
        response = self.session.post(f"{BASE_URL}/api/printers/seed-demo/{self.client_id}")
        assert response.status_code == 200, f"Seed demo failed: {response.text}"
        
        data = response.json()
        assert data["status"] == "ok", f"Unexpected status: {data['status']}"
        assert data["seeded"] == 4, f"Expected 4 seeded, got {data['seeded']}"
        print(f"Seeded {data['seeded']} demo printers")
    
    # ==================== Process Poll API Tests (No Auth) ====================
    
    def test_process_poll_without_auth(self):
        """POST /api/printers/process-poll - Works without JWT auth"""
        # Use a new session without auth header
        no_auth_session = requests.Session()
        no_auth_session.headers.update({"Content-Type": "application/json"})
        
        poll_data = {
            "client_id": self.client_id,
            "device_ip": "192.168.1.99",
            "device_name": "Test Printer",
            "model": "Test Model",
            "serial": "TEST123",
            "reachable": True,
            "printer_status_code": 3,
            "printer_status": "Idle",
            "page_count": 1000,
            "color_page_count": 500,
            "duplex_count": 200,
            "supplies": [
                {"name": "Black Toner", "type": "toner", "max_capacity": 1000, "current_level": 800}
            ],
            "trays": [
                {"name": "Tray 1", "status": "ok", "capacity": 250, "level": 200}
            ],
            "alert_messages": []
        }
        
        response = no_auth_session.post(f"{BASE_URL}/api/printers/process-poll", json=poll_data)
        assert response.status_code == 200, f"Process poll failed: {response.text}"
        
        data = response.json()
        assert data["status"] == "ok", f"Unexpected status: {data['status']}"
        print("Process poll succeeded without JWT auth")
        
        # Verify the printer was created
        verify_response = self.session.get(f"{BASE_URL}/api/printers/{self.client_id}/192.168.1.99")
        assert verify_response.status_code == 200, "Printer not created"
        printer = verify_response.json()["printer"]
        assert printer["device_name"] == "Test Printer"
        assert printer["page_count"] == 1000
        print("Verified printer was created via process-poll")
        
        # Cleanup: Delete the test printer (if endpoint exists, otherwise leave it)
    
    def test_process_poll_calculates_level_pct(self):
        """Verify process-poll calculates level_pct correctly"""
        no_auth_session = requests.Session()
        no_auth_session.headers.update({"Content-Type": "application/json"})
        
        poll_data = {
            "client_id": self.client_id,
            "device_ip": "192.168.1.98",
            "device_name": "Level Test Printer",
            "reachable": True,
            "supplies": [
                {"name": "Black Toner", "type": "toner", "max_capacity": 1000, "current_level": 150}  # 15%
            ]
        }
        
        response = no_auth_session.post(f"{BASE_URL}/api/printers/process-poll", json=poll_data)
        assert response.status_code == 200
        
        # Verify level_pct was calculated
        verify_response = self.session.get(f"{BASE_URL}/api/printers/{self.client_id}/192.168.1.98")
        assert verify_response.status_code == 200
        printer = verify_response.json()["printer"]
        supply = printer["supplies"][0]
        assert supply["level_pct"] == 15.0, f"Expected 15.0%, got {supply['level_pct']}%"
        print(f"Level calculated correctly: {supply['level_pct']}%")
    
    def test_process_poll_detects_color(self):
        """Verify process-poll detects toner color from name"""
        no_auth_session = requests.Session()
        no_auth_session.headers.update({"Content-Type": "application/json"})
        
        poll_data = {
            "client_id": self.client_id,
            "device_ip": "192.168.1.97",
            "device_name": "Color Test Printer",
            "reachable": True,
            "supplies": [
                {"name": "Cyan Toner TN-123C", "type": "toner", "max_capacity": 1000, "current_level": 500}
            ]
        }
        
        response = no_auth_session.post(f"{BASE_URL}/api/printers/process-poll", json=poll_data)
        assert response.status_code == 200
        
        # Verify color was detected
        verify_response = self.session.get(f"{BASE_URL}/api/printers/{self.client_id}/192.168.1.97")
        assert verify_response.status_code == 200
        printer = verify_response.json()["printer"]
        supply = printer["supplies"][0]
        assert supply["color_name"] == "cyan", f"Expected 'cyan', got '{supply['color_name']}'"
        assert supply["color_hex"] == "#00bcd4", f"Expected '#00bcd4', got '{supply['color_hex']}'"
        print(f"Color detected: {supply['color_name']} ({supply['color_hex']})")
    
    def test_process_poll_requires_client_id_and_device_ip(self):
        """Verify process-poll returns 400 if client_id or device_ip missing"""
        no_auth_session = requests.Session()
        no_auth_session.headers.update({"Content-Type": "application/json"})
        
        # Missing client_id
        response = no_auth_session.post(f"{BASE_URL}/api/printers/process-poll", json={
            "device_ip": "192.168.1.1"
        })
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        
        # Missing device_ip
        response = no_auth_session.post(f"{BASE_URL}/api/printers/process-poll", json={
            "client_id": self.client_id
        })
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        
        print("400 returned for missing required fields")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
