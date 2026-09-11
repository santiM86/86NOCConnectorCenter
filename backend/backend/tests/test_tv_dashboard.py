"""
TV Dashboard API Tests
Tests for /api/tv/dashboard endpoint - Full-screen NOC monitoring view
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestTvDashboardAPI:
    """TV Dashboard endpoint tests - NO AUTH REQUIRED"""
    
    def test_tv_dashboard_no_auth_required(self):
        """GET /api/tv/dashboard should work WITHOUT authentication"""
        response = requests.get(f"{BASE_URL}/api/tv/dashboard")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("PASS: TV Dashboard accessible without authentication")
    
    def test_tv_dashboard_response_structure(self):
        """Response should contain timestamp, global_stats, clients, alerts, low_toner"""
        response = requests.get(f"{BASE_URL}/api/tv/dashboard")
        assert response.status_code == 200
        
        data = response.json()
        
        # Check top-level keys
        assert "timestamp" in data, "Missing 'timestamp' in response"
        assert "global_stats" in data, "Missing 'global_stats' in response"
        assert "clients" in data, "Missing 'clients' in response"
        assert "alerts" in data, "Missing 'alerts' in response"
        assert "low_toner" in data, "Missing 'low_toner' in response"
        
        print("PASS: Response contains all required top-level keys")
    
    def test_global_stats_structure(self):
        """global_stats should contain all required fields"""
        response = requests.get(f"{BASE_URL}/api/tv/dashboard")
        assert response.status_code == 200
        
        g = response.json()["global_stats"]
        
        required_fields = [
            "total_clients",
            "total_devices",
            "total_online",
            "total_offline",
            "total_alerts",
            "critical_alerts",
            "open_incidents",
            "total_printers",
            "low_toner_count"
        ]
        
        for field in required_fields:
            assert field in g, f"Missing '{field}' in global_stats"
            assert isinstance(g[field], int), f"'{field}' should be integer, got {type(g[field])}"
        
        print(f"PASS: global_stats contains all {len(required_fields)} required fields")
        print(f"  - total_clients: {g['total_clients']}")
        print(f"  - total_devices: {g['total_devices']}")
        print(f"  - total_online: {g['total_online']}")
        print(f"  - total_offline: {g['total_offline']}")
        print(f"  - total_alerts: {g['total_alerts']}")
        print(f"  - critical_alerts: {g['critical_alerts']}")
        print(f"  - open_incidents: {g['open_incidents']}")
        print(f"  - total_printers: {g['total_printers']}")
        print(f"  - low_toner_count: {g['low_toner_count']}")
    
    def test_clients_array_structure(self):
        """clients array should contain client summaries with health_pct, online, offline, etc."""
        response = requests.get(f"{BASE_URL}/api/tv/dashboard")
        assert response.status_code == 200
        
        clients = response.json()["clients"]
        assert isinstance(clients, list), "clients should be an array"
        
        if len(clients) > 0:
            client = clients[0]
            required_fields = [
                "id", "name", "total_devices", "online", "offline",
                "health_pct", "alert_count", "critical_alerts", "high_alerts",
                "connector_online", "problem_devices"
            ]
            
            for field in required_fields:
                assert field in client, f"Missing '{field}' in client object"
            
            # Validate types
            assert isinstance(client["health_pct"], int), "health_pct should be integer"
            assert 0 <= client["health_pct"] <= 100, "health_pct should be 0-100"
            assert isinstance(client["connector_online"], bool), "connector_online should be boolean"
            assert isinstance(client["problem_devices"], list), "problem_devices should be array"
            
            print(f"PASS: clients array structure valid ({len(clients)} clients)")
            print(f"  - First client: {client['name']}")
            print(f"  - Health: {client['health_pct']}%")
            print(f"  - Online: {client['online']}, Offline: {client['offline']}")
            print(f"  - Connector: {'ONLINE' if client['connector_online'] else 'OFFLINE'}")
        else:
            print("INFO: No clients in response (empty array)")
    
    def test_alerts_array_structure(self):
        """alerts array should contain top 20 active alerts sorted by severity"""
        response = requests.get(f"{BASE_URL}/api/tv/dashboard")
        assert response.status_code == 200
        
        alerts = response.json()["alerts"]
        assert isinstance(alerts, list), "alerts should be an array"
        assert len(alerts) <= 20, f"alerts should be max 20, got {len(alerts)}"
        
        if len(alerts) > 0:
            alert = alerts[0]
            # Check basic alert fields
            assert "severity" in alert, "Missing 'severity' in alert"
            assert alert["severity"] in ["critical", "high", "medium", "low"], \
                f"Invalid severity: {alert['severity']}"
            
            # Verify sorted by severity (critical first)
            severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            for i in range(len(alerts) - 1):
                current_sev = severity_order.get(alerts[i].get("severity", "low"), 4)
                next_sev = severity_order.get(alerts[i+1].get("severity", "low"), 4)
                assert current_sev <= next_sev, "Alerts not sorted by severity"
            
            print(f"PASS: alerts array valid ({len(alerts)} alerts, max 20)")
            print(f"  - Sorted by severity: critical -> high -> medium -> low")
        else:
            print("INFO: No active alerts in response")
    
    def test_low_toner_array_structure(self):
        """low_toner array should contain printers with supplies <= 15%"""
        response = requests.get(f"{BASE_URL}/api/tv/dashboard")
        assert response.status_code == 200
        
        low_toner = response.json()["low_toner"]
        assert isinstance(low_toner, list), "low_toner should be an array"
        
        if len(low_toner) > 0:
            item = low_toner[0]
            required_fields = [
                "printer_name", "printer_ip", "client_id",
                "supply_name", "level_pct", "color_hex"
            ]
            
            for field in required_fields:
                assert field in item, f"Missing '{field}' in low_toner item"
            
            # Validate level_pct is <= 15
            for t in low_toner:
                assert 0 < t["level_pct"] <= 15, \
                    f"level_pct should be 0-15, got {t['level_pct']}"
            
            print(f"PASS: low_toner array valid ({len(low_toner)} items)")
            for t in low_toner[:5]:
                print(f"  - {t['supply_name']}: {t['level_pct']}% ({t['printer_name']})")
        else:
            print("INFO: No low toner items in response")
    
    def test_timestamp_format(self):
        """timestamp should be ISO format"""
        response = requests.get(f"{BASE_URL}/api/tv/dashboard")
        assert response.status_code == 200
        
        timestamp = response.json()["timestamp"]
        assert isinstance(timestamp, str), "timestamp should be string"
        
        # Should be ISO format with timezone
        from datetime import datetime
        try:
            # Try parsing ISO format
            if timestamp.endswith('Z'):
                datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            else:
                datetime.fromisoformat(timestamp)
            print(f"PASS: timestamp is valid ISO format: {timestamp}")
        except ValueError as e:
            pytest.fail(f"Invalid timestamp format: {timestamp} - {e}")
    
    def test_data_consistency(self):
        """Verify data consistency between global_stats and clients"""
        response = requests.get(f"{BASE_URL}/api/tv/dashboard")
        assert response.status_code == 200
        
        data = response.json()
        g = data["global_stats"]
        clients = data["clients"]
        
        # Sum of client devices should match total
        total_from_clients = sum(c["total_devices"] for c in clients)
        assert g["total_devices"] == total_from_clients, \
            f"total_devices mismatch: global={g['total_devices']}, sum={total_from_clients}"
        
        # Sum of online devices
        online_from_clients = sum(c["online"] for c in clients)
        assert g["total_online"] == online_from_clients, \
            f"total_online mismatch: global={g['total_online']}, sum={online_from_clients}"
        
        # Sum of offline devices
        offline_from_clients = sum(c["offline"] for c in clients)
        assert g["total_offline"] == offline_from_clients, \
            f"total_offline mismatch: global={g['total_offline']}, sum={offline_from_clients}"
        
        # Client count
        assert g["total_clients"] == len(clients), \
            f"total_clients mismatch: global={g['total_clients']}, actual={len(clients)}"
        
        print("PASS: Data consistency verified")
        print(f"  - total_clients: {g['total_clients']} == {len(clients)}")
        print(f"  - total_devices: {g['total_devices']} == {total_from_clients}")
        print(f"  - total_online: {g['total_online']} == {online_from_clients}")
        print(f"  - total_offline: {g['total_offline']} == {offline_from_clients}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
