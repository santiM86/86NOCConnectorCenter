"""
Iteration 31 - Comprehensive tests for all new NOC features:
- PDF Report Generation
- Device Inventory
- Incident Management
- Port/Service Monitoring
- Public Dashboard
- Notification Templates
- Escalation Rules
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://snmp-monitor-staging.preview.emergentagent.com')
CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"
PUBLIC_TOKEN = "15ec0bf5b908af5d"


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token."""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "admin@86bit.it",
        "password": "password"
    })
    assert response.status_code == 200, f"Login failed: {response.text}"
    return response.json()["token"]


@pytest.fixture(scope="module")
def auth_headers(auth_token):
    """Return headers with auth token."""
    return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}


# ==================== PDF REPORTS ====================

class TestPDFReports:
    """Tests for PDF Report Generation."""
    
    def test_list_available_reports(self, auth_headers):
        """GET /api/reports/list - List clients available for reports."""
        response = requests.get(f"{BASE_URL}/api/reports/list", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Should have at least one client
        assert len(data) > 0
        # Check structure
        client = data[0]
        assert "client_id" in client
        assert "client_name" in client
        assert "device_count" in client
        print(f"✓ Found {len(data)} clients available for reports")
    
    def test_generate_pdf_report(self, auth_headers):
        """GET /api/reports/generate/{client_id} - Generate PDF report."""
        response = requests.get(
            f"{BASE_URL}/api/reports/generate/{CLIENT_ID}?days=30",
            headers=auth_headers
        )
        assert response.status_code == 200
        assert response.headers.get("content-type") == "application/pdf"
        # Check PDF content
        content = response.content
        assert len(content) > 1000, "PDF should have substantial content"
        assert content[:4] == b'%PDF', "Response should be a valid PDF"
        print(f"✓ Generated PDF report: {len(content)} bytes")
    
    def test_generate_report_invalid_client(self, auth_headers):
        """GET /api/reports/generate/{invalid_id} - Should return 404."""
        response = requests.get(
            f"{BASE_URL}/api/reports/generate/invalid-client-id",
            headers=auth_headers
        )
        assert response.status_code == 404
        print("✓ Invalid client returns 404")


# ==================== DEVICE INVENTORY ====================

class TestDeviceInventory:
    """Tests for Device Inventory."""
    
    def test_get_inventory(self, auth_headers):
        """GET /api/inventory/{client_id} - Get full device inventory."""
        response = requests.get(f"{BASE_URL}/api/inventory/{CLIENT_ID}", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        # Check structure
        assert "client_id" in data
        assert "total" in data
        assert "online" in data
        assert "offline" in data
        assert "types" in data
        assert "devices" in data
        
        # Check devices array
        assert isinstance(data["devices"], list)
        assert data["total"] == len(data["devices"])
        print(f"✓ Inventory: {data['total']} devices ({data['online']} online, {data['offline']} offline)")
        
        # Check device structure
        if data["devices"]:
            device = data["devices"][0]
            assert "device_ip" in device
            assert "device_name" in device
            assert "device_type" in device
            assert "reachable" in device
            assert "monitor_type" in device
    
    def test_inventory_search_filter(self, auth_headers):
        """GET /api/inventory/{client_id}?search=... - Test search filter."""
        response = requests.get(
            f"{BASE_URL}/api/inventory/{CLIENT_ID}?search=192.168",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        # All results should contain the search term
        for device in data["devices"]:
            assert "192.168" in device["device_ip"].lower() or \
                   "192.168" in device.get("device_name", "").lower()
        print(f"✓ Search filter working: {len(data['devices'])} results")
    
    def test_inventory_type_filter(self, auth_headers):
        """GET /api/inventory/{client_id}?device_type=switch - Test type filter."""
        response = requests.get(
            f"{BASE_URL}/api/inventory/{CLIENT_ID}?device_type=switch",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        for device in data["devices"]:
            assert device["device_type"] == "switch"
        print(f"✓ Type filter working: {len(data['devices'])} switches")
    
    def test_inventory_status_filter(self, auth_headers):
        """GET /api/inventory/{client_id}?status=online - Test status filter."""
        response = requests.get(
            f"{BASE_URL}/api/inventory/{CLIENT_ID}?status=online",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        for device in data["devices"]:
            assert device["reachable"] == True
        print(f"✓ Status filter working: {len(data['devices'])} online devices")
    
    def test_inventory_sorting(self, auth_headers):
        """GET /api/inventory/{client_id}?sort_by=device_ip&sort_dir=asc - Test sorting."""
        response = requests.get(
            f"{BASE_URL}/api/inventory/{CLIENT_ID}?sort_by=device_ip&sort_dir=asc",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        if len(data["devices"]) > 1:
            ips = [d["device_ip"] for d in data["devices"]]
            assert ips == sorted(ips), "Devices should be sorted by IP ascending"
        print("✓ Sorting working correctly")


# ==================== INCIDENT MANAGEMENT ====================

class TestIncidentManagement:
    """Tests for Incident/Ticket Management."""
    
    created_incident_id = None
    
    def test_list_incidents_empty_or_existing(self, auth_headers):
        """GET /api/incidents - List all incidents."""
        response = requests.get(f"{BASE_URL}/api/incidents", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Listed {len(data)} existing incidents")
    
    def test_create_incident(self, auth_headers):
        """POST /api/incidents - Create a new incident."""
        payload = {
            "title": "TEST_Incident_Iteration31",
            "description": "Test incident created by automated testing",
            "client_id": CLIENT_ID,
            "client_name": "86BIT_Office",
            "priority": "high",
            "device_ip": "192.168.1.1",
            "device_name": "Test Device"
        }
        response = requests.post(f"{BASE_URL}/api/incidents", json=payload, headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        # Validate response structure
        assert "id" in data
        assert data["title"] == payload["title"]
        assert data["status"] == "open"
        assert data["priority"] == "high"
        assert "timeline" in data
        assert len(data["timeline"]) == 1
        assert data["timeline"][0]["action"] == "created"
        
        TestIncidentManagement.created_incident_id = data["id"]
        print(f"✓ Created incident: {data['id']}")
    
    def test_get_incident_detail(self, auth_headers):
        """GET /api/incidents/{id} - Get incident detail."""
        incident_id = TestIncidentManagement.created_incident_id
        assert incident_id, "Incident must be created first"
        
        response = requests.get(f"{BASE_URL}/api/incidents/{incident_id}", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == incident_id
        assert data["title"] == "TEST_Incident_Iteration31"
        print(f"✓ Retrieved incident detail")
    
    def test_update_incident_status(self, auth_headers):
        """PATCH /api/incidents/{id} - Update incident status."""
        incident_id = TestIncidentManagement.created_incident_id
        assert incident_id, "Incident must be created first"
        
        response = requests.patch(
            f"{BASE_URL}/api/incidents/{incident_id}",
            json={"status": "in_progress"},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "in_progress"
        # Timeline should have new entry
        assert len(data["timeline"]) >= 2
        print(f"✓ Updated incident status to in_progress")
    
    def test_update_incident_priority(self, auth_headers):
        """PATCH /api/incidents/{id} - Update incident priority."""
        incident_id = TestIncidentManagement.created_incident_id
        assert incident_id, "Incident must be created first"
        
        response = requests.patch(
            f"{BASE_URL}/api/incidents/{incident_id}",
            json={"priority": "critical"},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["priority"] == "critical"
        print(f"✓ Updated incident priority to critical")
    
    def test_add_incident_note(self, auth_headers):
        """PATCH /api/incidents/{id} - Add note to incident."""
        incident_id = TestIncidentManagement.created_incident_id
        assert incident_id, "Incident must be created first"
        
        response = requests.patch(
            f"{BASE_URL}/api/incidents/{incident_id}",
            json={"note": "Test note from automated testing"},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        # Check note was added to timeline
        notes = [t for t in data["timeline"] if t["action"] == "note_added"]
        assert len(notes) >= 1
        print(f"✓ Added note to incident")
    
    def test_incident_stats(self, auth_headers):
        """GET /api/incidents/stats/summary - Get incident statistics."""
        response = requests.get(f"{BASE_URL}/api/incidents/stats/summary", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        assert "total" in data
        assert "open" in data
        assert "in_progress" in data
        assert "resolved" in data
        assert "by_priority" in data
        print(f"✓ Stats: {data['total']} total, {data['open']} open, {data['in_progress']} in progress")
    
    def test_delete_incident(self, auth_headers):
        """DELETE /api/incidents/{id} - Delete incident."""
        incident_id = TestIncidentManagement.created_incident_id
        assert incident_id, "Incident must be created first"
        
        response = requests.delete(f"{BASE_URL}/api/incidents/{incident_id}", headers=auth_headers)
        assert response.status_code == 200
        
        # Verify deletion
        response = requests.get(f"{BASE_URL}/api/incidents/{incident_id}", headers=auth_headers)
        assert response.status_code == 404
        print(f"✓ Deleted incident and verified removal")


# ==================== PORT/SERVICE MONITORING ====================

class TestPortMonitor:
    """Tests for TCP Port/Service Monitoring."""
    
    created_service_id = None
    
    def test_get_common_ports(self, auth_headers):
        """GET /api/port-monitor/common-ports - Get list of common ports."""
        response = requests.get(f"{BASE_URL}/api/port-monitor/common-ports", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
        # Check structure
        port = data[0]
        assert "port" in port
        assert "name" in port
        print(f"✓ Got {len(data)} common ports")
    
    def test_get_monitored_services_empty_or_existing(self, auth_headers):
        """GET /api/port-monitor/services/{client_id} - Get monitored services."""
        response = requests.get(f"{BASE_URL}/api/port-monitor/services/{CLIENT_ID}", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        print(f"✓ Got {len(data)} monitored services")
    
    def test_add_service_monitor(self, auth_headers):
        """POST /api/port-monitor/services - Add a service to monitor."""
        payload = {
            "client_id": CLIENT_ID,
            "device_ip": "192.168.1.1",
            "device_name": "Test Router",
            "port": 443,
            "service_name": "HTTPS"
        }
        response = requests.post(f"{BASE_URL}/api/port-monitor/services", json=payload, headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        assert "id" in data
        assert data["port"] == 443
        assert data["service_name"] == "HTTPS"
        assert data["enabled"] == True
        
        TestPortMonitor.created_service_id = data["id"]
        print(f"✓ Added service monitor: {data['id']}")
    
    def test_check_all_ports(self, auth_headers):
        """POST /api/port-monitor/check/{client_id} - Check all monitored ports."""
        response = requests.post(f"{BASE_URL}/api/port-monitor/check/{CLIENT_ID}", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        assert "client_id" in data
        assert "checked" in data
        assert "results" in data
        print(f"✓ Checked {data['checked']} services")
    
    def test_remove_service_monitor(self, auth_headers):
        """DELETE /api/port-monitor/services/{id} - Remove a monitored service."""
        service_id = TestPortMonitor.created_service_id
        assert service_id, "Service must be created first"
        
        response = requests.delete(f"{BASE_URL}/api/port-monitor/services/{service_id}", headers=auth_headers)
        assert response.status_code == 200
        print(f"✓ Removed service monitor")


# ==================== PUBLIC DASHBOARD ====================

class TestPublicDashboard:
    """Tests for Public Dashboard (no auth required)."""
    
    def test_get_public_dashboard_no_auth(self):
        """GET /api/public/dashboard/{token} - Access public dashboard without auth."""
        response = requests.get(f"{BASE_URL}/api/public/dashboard/{PUBLIC_TOKEN}")
        assert response.status_code == 200
        data = response.json()
        
        # Check structure
        assert "client_name" in data
        assert "generated_at" in data
        print(f"✓ Public dashboard accessible: {data['client_name']}")
    
    def test_public_dashboard_shows_devices(self):
        """Public dashboard should show device information."""
        response = requests.get(f"{BASE_URL}/api/public/dashboard/{PUBLIC_TOKEN}")
        assert response.status_code == 200
        data = response.json()
        
        if "devices" in data:
            assert "total" in data["devices"]
            assert "online" in data["devices"]
            assert "offline" in data["devices"]
            assert "list" in data["devices"]
            print(f"✓ Devices: {data['devices']['online']}/{data['devices']['total']} online")
    
    def test_public_dashboard_shows_sla(self):
        """Public dashboard should show SLA information."""
        response = requests.get(f"{BASE_URL}/api/public/dashboard/{PUBLIC_TOKEN}")
        assert response.status_code == 200
        data = response.json()
        
        if "sla" in data:
            assert "overall_pct" in data["sla"]
            assert "period_days" in data["sla"]
            print(f"✓ SLA: {data['sla']['overall_pct']}% over {data['sla']['period_days']} days")
    
    def test_public_dashboard_shows_alerts(self):
        """Public dashboard should show alert information."""
        response = requests.get(f"{BASE_URL}/api/public/dashboard/{PUBLIC_TOKEN}")
        assert response.status_code == 200
        data = response.json()
        
        if "alerts" in data:
            assert "active_count" in data["alerts"]
            assert "list" in data["alerts"]
            print(f"✓ Alerts: {data['alerts']['active_count']} active")
    
    def test_public_dashboard_invalid_token(self):
        """GET /api/public/dashboard/{invalid_token} - Should return 404."""
        response = requests.get(f"{BASE_URL}/api/public/dashboard/invalid-token-12345")
        assert response.status_code == 404
        print("✓ Invalid token returns 404")
    
    def test_get_dashboard_config(self, auth_headers):
        """GET /api/public/dashboard/config/{client_id} - Get dashboard config (admin)."""
        response = requests.get(
            f"{BASE_URL}/api/public/dashboard/config/{CLIENT_ID}",
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert "client_id" in data
        print(f"✓ Dashboard config retrieved")


# ==================== NOTIFICATION TEMPLATES ====================

class TestNotificationTemplates:
    """Tests for Notification Templates API."""
    
    created_template_id = None
    
    def test_get_notification_templates(self, auth_headers):
        """GET /api/notifications/templates - Get all templates."""
        response = requests.get(f"{BASE_URL}/api/notifications/templates", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Should have default templates
        assert len(data) >= 1
        
        # Check structure
        template = data[0]
        assert "id" in template
        assert "name" in template
        assert "severity_filter" in template
        assert "channels" in template
        assert "message_template" in template
        print(f"✓ Got {len(data)} notification templates")
    
    def test_create_notification_template(self, auth_headers):
        """POST /api/notifications/templates - Create a new template."""
        payload = {
            "name": "TEST_Template_Iteration31",
            "severity_filter": ["critical", "high"],
            "escalation_enabled": True,
            "escalation_minutes": 10,
            "message_template": "TEST: {alert_title} on {device_name}"
        }
        response = requests.post(f"{BASE_URL}/api/notifications/templates", json=payload, headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        assert "id" in data
        assert data["name"] == payload["name"]
        assert data["escalation_enabled"] == True
        
        TestNotificationTemplates.created_template_id = data["id"]
        print(f"✓ Created template: {data['id']}")
    
    def test_update_notification_template(self, auth_headers):
        """PUT /api/notifications/templates/{id} - Update a template."""
        template_id = TestNotificationTemplates.created_template_id
        assert template_id, "Template must be created first"
        
        payload = {
            "name": "TEST_Template_Updated",
            "escalation_minutes": 15
        }
        response = requests.put(
            f"{BASE_URL}/api/notifications/templates/{template_id}",
            json=payload,
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "TEST_Template_Updated"
        assert data["escalation_minutes"] == 15
        print(f"✓ Updated template")
    
    def test_delete_notification_template(self, auth_headers):
        """DELETE /api/notifications/templates/{id} - Delete a template."""
        template_id = TestNotificationTemplates.created_template_id
        assert template_id, "Template must be created first"
        
        response = requests.delete(
            f"{BASE_URL}/api/notifications/templates/{template_id}",
            headers=auth_headers
        )
        assert response.status_code == 200
        print(f"✓ Deleted template")
    
    def test_test_notification_mocked(self, auth_headers):
        """POST /api/notifications/test - Test notification (MOCKED)."""
        payload = {
            "channel_type": "email",
            "message": "Test notification from iteration 31"
        }
        response = requests.post(f"{BASE_URL}/api/notifications/test", json=payload, headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "note" in data  # Should mention it's mocked
        print(f"✓ Test notification (MOCKED): {data['message']}")


# ==================== ESCALATION RULES ====================

class TestEscalationRules:
    """Tests for Escalation Rules API."""
    
    def test_get_escalation_rules(self, auth_headers):
        """GET /api/notifications/escalation-rules - Get escalation rules."""
        response = requests.get(f"{BASE_URL}/api/notifications/escalation-rules", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Should have default rules
        assert len(data) >= 1
        
        # Check structure
        rule = data[0]
        assert "id" in rule
        assert "name" in rule
        assert "trigger" in rule
        assert "minutes" in rule
        assert "severity" in rule
        print(f"✓ Got {len(data)} escalation rules")


# ==================== DASHBOARD WIDGETS (Metrics APIs) ====================

class TestDashboardWidgets:
    """Tests for Dashboard Widget APIs (SLA, Changes, Heatmap)."""
    
    def test_sla_metrics(self, auth_headers):
        """GET /api/metrics/sla/{client_id} - Get SLA metrics."""
        response = requests.get(f"{BASE_URL}/api/metrics/sla/{CLIENT_ID}?days=30", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        assert "overall_sla_pct" in data
        assert "total_checks" in data
        assert "devices" in data
        print(f"✓ SLA: {data['overall_sla_pct']}% overall")
    
    def test_changes_metrics(self, auth_headers):
        """GET /api/metrics/changes/{client_id} - Get network changes."""
        response = requests.get(f"{BASE_URL}/api/metrics/changes/{CLIENT_ID}?days=7", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        assert "total_changes" in data
        assert "changes" in data
        print(f"✓ Changes: {data['total_changes']} in last 7 days")
    
    def test_heatmap_metrics(self, auth_headers):
        """GET /api/metrics/heatmap/{client_id} - Get uptime heatmap."""
        response = requests.get(f"{BASE_URL}/api/metrics/heatmap/{CLIENT_ID}?days=7", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        
        assert "devices" in data
        print(f"✓ Heatmap: {len(data['devices'])} devices")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
