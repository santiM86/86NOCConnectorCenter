"""
Test suite for the IMPROVED TV Dashboard API (iteration 35)
Tests the 3-column layout data structure with enriched fields:
- offline_devices with name, ip, client_name, down_since
- alerts with device_name, device_ip, client_name, time_ago
- incidents with title, priority, status, client_name, time_ago
- connectors with client_name, hostname, version, online, last_seen
- ticker with severity, message, client_name, time_ago
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestTvDashboardApiNoAuth:
    """TV Dashboard API should be accessible WITHOUT authentication"""
    
    def test_tv_dashboard_no_auth_required(self):
        """GET /api/tv/dashboard should return 200 without any auth headers"""
        response = requests.get(f"{BASE_URL}/api/tv/dashboard")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert "timestamp" in data
        assert "global_stats" in data
        print("✓ TV Dashboard accessible without authentication")


class TestTvDashboardResponseStructure:
    """Test the complete response structure of the improved TV Dashboard"""
    
    @pytest.fixture(scope="class")
    def dashboard_data(self):
        """Fetch dashboard data once for all tests in this class"""
        response = requests.get(f"{BASE_URL}/api/tv/dashboard")
        assert response.status_code == 200
        return response.json()
    
    def test_response_has_all_required_keys(self, dashboard_data):
        """Response should contain all required top-level keys"""
        required_keys = [
            "timestamp", "global_stats", "clients", "offline_devices",
            "alerts", "incidents", "connectors", "low_toner", "ticker"
        ]
        for key in required_keys:
            assert key in dashboard_data, f"Missing required key: {key}"
        print(f"✓ All {len(required_keys)} required keys present in response")
    
    def test_global_stats_structure(self, dashboard_data):
        """global_stats should have all required metrics"""
        stats = dashboard_data["global_stats"]
        required_stats = [
            "total_clients", "total_devices", "total_online", "total_offline",
            "total_alerts", "critical_alerts", "high_alerts", "open_incidents",
            "total_printers", "printers_online", "printers_offline", "low_toner_count"
        ]
        for stat in required_stats:
            assert stat in stats, f"Missing stat: {stat}"
            assert isinstance(stats[stat], int), f"{stat} should be int, got {type(stats[stat])}"
        print(f"✓ global_stats has all {len(required_stats)} required metrics")


class TestOfflineDevicesEnriched:
    """Test offline_devices array has enriched data"""
    
    @pytest.fixture(scope="class")
    def dashboard_data(self):
        response = requests.get(f"{BASE_URL}/api/tv/dashboard")
        return response.json()
    
    def test_offline_devices_is_array(self, dashboard_data):
        """offline_devices should be an array"""
        assert isinstance(dashboard_data["offline_devices"], list)
        print(f"✓ offline_devices is array with {len(dashboard_data['offline_devices'])} items")
    
    def test_offline_device_has_required_fields(self, dashboard_data):
        """Each offline device should have name, ip, client_name, down_since"""
        offline = dashboard_data["offline_devices"]
        if len(offline) == 0:
            pytest.skip("No offline devices to test")
        
        required_fields = ["name", "ip", "client_name", "down_since"]
        for device in offline:
            for field in required_fields:
                assert field in device, f"Offline device missing field: {field}"
        
        # Verify first device has actual values
        first = offline[0]
        assert first["name"], "Device name should not be empty"
        assert first["ip"], "Device IP should not be empty"
        assert first["client_name"], "Client name should not be empty"
        print(f"✓ Offline devices have all required fields: {required_fields}")
        print(f"  Sample: {first['name']} ({first['ip']}) - {first['client_name']} - {first['down_since']}")


class TestAlertsEnriched:
    """Test alerts array has enriched data with device/client info"""
    
    @pytest.fixture(scope="class")
    def dashboard_data(self):
        response = requests.get(f"{BASE_URL}/api/tv/dashboard")
        return response.json()
    
    def test_alerts_is_array(self, dashboard_data):
        """alerts should be an array"""
        assert isinstance(dashboard_data["alerts"], list)
        print(f"✓ alerts is array with {len(dashboard_data['alerts'])} items")
    
    def test_alert_has_enriched_fields(self, dashboard_data):
        """Each alert should have device_name, device_ip, client_name, time_ago"""
        alerts = dashboard_data["alerts"]
        if len(alerts) == 0:
            pytest.skip("No alerts to test")
        
        required_fields = ["id", "severity", "title", "device_name", "device_ip", "client_name", "time_ago"]
        for alert in alerts:
            for field in required_fields:
                assert field in alert, f"Alert missing field: {field}"
        
        first = alerts[0]
        assert first["severity"] in ["critical", "high", "medium", "low"], f"Invalid severity: {first['severity']}"
        assert first["time_ago"], "time_ago should not be empty"
        print(f"✓ Alerts have all required enriched fields: {required_fields}")
        print(f"  Sample: [{first['severity']}] {first['title']} - {first['time_ago']}")


class TestIncidentsEnriched:
    """Test incidents array has priority, status, client_name, time_ago"""
    
    @pytest.fixture(scope="class")
    def dashboard_data(self):
        response = requests.get(f"{BASE_URL}/api/tv/dashboard")
        return response.json()
    
    def test_incidents_is_array(self, dashboard_data):
        """incidents should be an array"""
        assert isinstance(dashboard_data["incidents"], list)
        print(f"✓ incidents is array with {len(dashboard_data['incidents'])} items")
    
    def test_incident_has_required_fields(self, dashboard_data):
        """Each incident should have title, priority, status, client_name, time_ago"""
        incidents = dashboard_data["incidents"]
        if len(incidents) == 0:
            pytest.skip("No incidents to test")
        
        required_fields = ["id", "title", "priority", "status", "client_name", "time_ago"]
        for inc in incidents:
            for field in required_fields:
                assert field in inc, f"Incident missing field: {field}"
        
        first = incidents[0]
        assert first["priority"] in ["critical", "high", "medium", "low"], f"Invalid priority: {first['priority']}"
        assert first["status"] in ["open", "in_progress", "resolved", "closed"], f"Invalid status: {first['status']}"
        print(f"✓ Incidents have all required fields: {required_fields}")
        print(f"  Sample: [{first['priority']}] {first['title']} - {first['status']} - {first['time_ago']}")


class TestConnectorsEnriched:
    """Test connectors array has hostname, version, online, last_seen"""
    
    @pytest.fixture(scope="class")
    def dashboard_data(self):
        response = requests.get(f"{BASE_URL}/api/tv/dashboard")
        return response.json()
    
    def test_connectors_is_array(self, dashboard_data):
        """connectors should be an array"""
        assert isinstance(dashboard_data["connectors"], list)
        print(f"✓ connectors is array with {len(dashboard_data['connectors'])} items")
    
    def test_connector_has_required_fields(self, dashboard_data):
        """Each connector should have client_name, hostname, version, online, last_seen"""
        connectors = dashboard_data["connectors"]
        if len(connectors) == 0:
            pytest.skip("No connectors to test")
        
        required_fields = ["client_name", "hostname", "version", "online", "last_seen"]
        for conn in connectors:
            for field in required_fields:
                assert field in conn, f"Connector missing field: {field}"
        
        first = connectors[0]
        assert isinstance(first["online"], bool), "online should be boolean"
        assert first["hostname"], "hostname should not be empty"
        print(f"✓ Connectors have all required fields: {required_fields}")
        print(f"  Sample: {first['client_name']} - {first['hostname']} v{first['version']} - {'ONLINE' if first['online'] else 'OFFLINE'} - {first['last_seen']}")


class TestTickerEnriched:
    """Test ticker array has severity, message, client_name, time_ago"""
    
    @pytest.fixture(scope="class")
    def dashboard_data(self):
        response = requests.get(f"{BASE_URL}/api/tv/dashboard")
        return response.json()
    
    def test_ticker_is_array(self, dashboard_data):
        """ticker should be an array"""
        assert isinstance(dashboard_data["ticker"], list)
        print(f"✓ ticker is array with {len(dashboard_data['ticker'])} items")
    
    def test_ticker_event_has_required_fields(self, dashboard_data):
        """Each ticker event should have severity, message, client_name, time_ago"""
        ticker = dashboard_data["ticker"]
        if len(ticker) == 0:
            pytest.skip("No ticker events to test")
        
        required_fields = ["severity", "message", "client_name", "time_ago"]
        for event in ticker:
            for field in required_fields:
                assert field in event, f"Ticker event missing field: {field}"
        
        first = ticker[0]
        assert first["severity"] in ["critical", "high", "medium", "low"], f"Invalid severity: {first['severity']}"
        assert first["message"], "message should not be empty"
        print(f"✓ Ticker events have all required fields: {required_fields}")
        print(f"  Sample: [{first['severity']}] {first['message'][:50]}... - {first['time_ago']}")


class TestLowTonerData:
    """Test low_toner array structure"""
    
    @pytest.fixture(scope="class")
    def dashboard_data(self):
        response = requests.get(f"{BASE_URL}/api/tv/dashboard")
        return response.json()
    
    def test_low_toner_is_array(self, dashboard_data):
        """low_toner should be an array"""
        assert isinstance(dashboard_data["low_toner"], list)
        print(f"✓ low_toner is array with {len(dashboard_data['low_toner'])} items")
    
    def test_low_toner_has_required_fields(self, dashboard_data):
        """Each low toner item should have printer_name, supply_name, level_pct, color_hex"""
        toner = dashboard_data["low_toner"]
        if len(toner) == 0:
            pytest.skip("No low toner items to test")
        
        required_fields = ["printer_name", "printer_ip", "client_name", "supply_name", "level_pct", "color_hex"]
        for item in toner:
            for field in required_fields:
                assert field in item, f"Low toner item missing field: {field}"
        
        first = toner[0]
        assert 0 <= first["level_pct"] <= 100, f"level_pct should be 0-100, got {first['level_pct']}"
        print(f"✓ Low toner items have all required fields: {required_fields}")
        print(f"  Sample: {first['printer_name']} - {first['supply_name']} at {first['level_pct']}%")


class TestClientSummaries:
    """Test client summaries in the response"""
    
    @pytest.fixture(scope="class")
    def dashboard_data(self):
        response = requests.get(f"{BASE_URL}/api/tv/dashboard")
        return response.json()
    
    def test_clients_is_array(self, dashboard_data):
        """clients should be an array"""
        assert isinstance(dashboard_data["clients"], list)
        print(f"✓ clients is array with {len(dashboard_data['clients'])} items")
    
    def test_client_has_required_fields(self, dashboard_data):
        """Each client should have comprehensive summary data"""
        clients = dashboard_data["clients"]
        if len(clients) == 0:
            pytest.skip("No clients to test")
        
        required_fields = [
            "id", "name", "total_devices", "online", "offline", "health_pct",
            "alert_count", "critical_alerts", "high_alerts",
            "connector_online", "connector_version", "last_heartbeat",
            "problem_devices", "printer_count"
        ]
        for client in clients:
            for field in required_fields:
                assert field in client, f"Client missing field: {field}"
        
        first = clients[0]
        assert 0 <= first["health_pct"] <= 100, f"health_pct should be 0-100"
        assert isinstance(first["problem_devices"], list), "problem_devices should be array"
        print(f"✓ Clients have all required fields: {len(required_fields)} fields")
        print(f"  Sample: {first['name']} - {first['online']}/{first['total_devices']} online - {first['health_pct']}% health")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
