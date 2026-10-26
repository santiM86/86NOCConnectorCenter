"""
Test Zyxel USG Firewall SNMP Metrics Monitoring Feature
Tests:
- POST /api/connector/device-report accepts Zyxel firewall data with device_class zyxel-usg
- Firewall data (active_sessions, flash_usage, vpn_throughput, firmware, product_name, serial_number, cpu_detail) is stored
- Metrics history stores active_sessions and vpn_throughput for Zyxel devices
- GET /api/connector/device-metrics/{device_ip} returns historical data including active_sessions
"""
import pytest
import requests
import os
import time

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
API_KEY = "noc_35cf39b4d68740b1a981aedef2ee293d"
TEST_DEVICE_IP = "192.168.1.254"

# Test credentials
ADMIN_EMAIL = "admin@86bit.it"
ADMIN_PASSWORD = "admin123"


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


class TestZyxelDeviceReport:
    """Test POST /api/connector/device-report for Zyxel firewall data."""
    
    def test_device_report_accepts_zyxel_firewall_data(self):
        """Test that device-report endpoint accepts Zyxel firewall data with device_class zyxel-usg."""
        payload = {
            "hostname": "test-connector",
            "devices": [{
                "device_ip": TEST_DEVICE_IP,
                "device_name": "Zyxel USG Test",
                "reachable": True,
                "monitor_type": "snmp",
                "device_class": "zyxel-usg",
                "cpu_usage": 25,
                "memory_usage": 45,
                "sys_descr": "Zyxel USG FLEX 200",
                "sys_uptime": "10 days, 5:30:00",
                "poll_timestamp": "2026-01-27T10:00:00Z",
                "firewall": {
                    "active_sessions": 12500,
                    "flash_usage": 65,
                    "vpn_throughput": 52428800,  # 50 Mbps in bps
                    "firmware": "5.37(ABUH.0)",
                    "product_name": "USG FLEX 200",
                    "serial_number": "S212345678901",
                    "cpu_detail": {
                        "current": 25,
                        "avg_5sec": 28,
                        "avg_1min": 22,
                        "avg_5min": 20
                    }
                },
                "ports": [
                    {"index": "1", "status": "up", "speed_bps": 1000000000, "in_bps": 5000000, "out_bps": 3000000},
                    {"index": "2", "status": "up", "speed_bps": 1000000000, "in_bps": 2000000, "out_bps": 1500000},
                    {"index": "3", "status": "down", "speed_bps": 0}
                ]
            }]
        }
        
        response = requests.post(
            f"{BASE_URL}/api/connector/device-report",
            json=payload,
            headers={"X-API-Key": API_KEY, "Content-Type": "application/json"}
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data.get("status") == "ok"
        assert data.get("devices_updated") == 1
        print(f"✓ Device report accepted for Zyxel firewall: {data}")
    
    def test_device_report_requires_api_key(self):
        """Test that device-report endpoint requires API key."""
        payload = {"hostname": "test", "devices": []}
        response = requests.post(
            f"{BASE_URL}/api/connector/device-report",
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 401
        print("✓ Device report requires API key (401 without key)")
    
    def test_device_report_rejects_invalid_api_key(self):
        """Test that device-report endpoint rejects invalid API key."""
        payload = {"hostname": "test", "devices": []}
        response = requests.post(
            f"{BASE_URL}/api/connector/device-report",
            json=payload,
            headers={"X-API-Key": "invalid_key", "Content-Type": "application/json"}
        )
        assert response.status_code == 401
        print("✓ Device report rejects invalid API key (401)")


class TestZyxelDataStorage:
    """Test that Zyxel firewall data is stored correctly in device_poll_status."""
    
    def test_firewall_data_stored_in_poll_status(self, auth_headers):
        """Test that firewall data is stored in device_poll_status collection."""
        # First, send a device report to ensure data exists
        payload = {
            "hostname": "test-connector",
            "devices": [{
                "device_ip": TEST_DEVICE_IP,
                "device_name": "Zyxel USG Test",
                "reachable": True,
                "monitor_type": "snmp",
                "device_class": "zyxel-usg",
                "cpu_usage": 30,
                "memory_usage": 50,
                "firewall": {
                    "active_sessions": 15000,
                    "flash_usage": 70,
                    "vpn_throughput": 104857600,  # 100 Mbps
                    "firmware": "5.37(ABUH.0)",
                    "product_name": "USG FLEX 200",
                    "serial_number": "S212345678901",
                    "cpu_detail": {
                        "current": 30,
                        "avg_5sec": 32,
                        "avg_1min": 28,
                        "avg_5min": 25
                    }
                },
                "poll_timestamp": "2026-01-27T10:05:00Z"
            }]
        }
        
        requests.post(
            f"{BASE_URL}/api/connector/device-report",
            json=payload,
            headers={"X-API-Key": API_KEY, "Content-Type": "application/json"}
        )
        
        # Now fetch the poll status
        response = requests.get(
            f"{BASE_URL}/api/connector/device-poll-status",
            headers=auth_headers
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        statuses = response.json()
        
        # Find our test device
        zyxel_device = None
        for status in statuses:
            if status.get("device_ip") == TEST_DEVICE_IP:
                zyxel_device = status
                break
        
        assert zyxel_device is not None, f"Zyxel device {TEST_DEVICE_IP} not found in poll status"
        
        # Verify device_class
        assert zyxel_device.get("device_class") == "zyxel-usg", f"Expected device_class 'zyxel-usg', got {zyxel_device.get('device_class')}"
        
        # Verify firewall data is stored
        firewall = zyxel_device.get("firewall")
        assert firewall is not None, "Firewall data not stored"
        assert firewall.get("active_sessions") == 15000, f"Expected active_sessions 15000, got {firewall.get('active_sessions')}"
        assert firewall.get("flash_usage") == 70, f"Expected flash_usage 70, got {firewall.get('flash_usage')}"
        assert firewall.get("vpn_throughput") == 104857600, f"Expected vpn_throughput 104857600, got {firewall.get('vpn_throughput')}"
        assert firewall.get("firmware") == "5.37(ABUH.0)", f"Expected firmware '5.37(ABUH.0)', got {firewall.get('firmware')}"
        assert firewall.get("product_name") == "USG FLEX 200", f"Expected product_name 'USG FLEX 200', got {firewall.get('product_name')}"
        assert firewall.get("serial_number") == "S212345678901", f"Expected serial_number 'S212345678901', got {firewall.get('serial_number')}"
        
        # Verify cpu_detail
        cpu_detail = firewall.get("cpu_detail")
        assert cpu_detail is not None, "cpu_detail not stored"
        assert cpu_detail.get("current") == 30
        assert cpu_detail.get("avg_5sec") == 32
        assert cpu_detail.get("avg_1min") == 28
        assert cpu_detail.get("avg_5min") == 25
        
        print(f"✓ Firewall data correctly stored: sessions={firewall.get('active_sessions')}, flash={firewall.get('flash_usage')}%, vpn={firewall.get('vpn_throughput')} bps")
        print(f"✓ CPU detail stored: current={cpu_detail.get('current')}%, 5s={cpu_detail.get('avg_5sec')}%, 1m={cpu_detail.get('avg_1min')}%, 5m={cpu_detail.get('avg_5min')}%")


class TestZyxelMetricsHistory:
    """Test that metrics history stores active_sessions and vpn_throughput for Zyxel devices."""
    
    def test_metrics_history_includes_firewall_metrics(self, auth_headers):
        """Test that GET /api/connector/device-metrics/{device_ip} returns historical data including active_sessions."""
        # First, send multiple device reports to create history
        for i in range(3):
            payload = {
                "hostname": "test-connector",
                "devices": [{
                    "device_ip": TEST_DEVICE_IP,
                    "device_name": "Zyxel USG Test",
                    "reachable": True,
                    "device_class": "zyxel-usg",
                    "cpu_usage": 25 + i * 5,
                    "memory_usage": 45 + i * 3,
                    "temperature": 40 + i,
                    "firewall": {
                        "active_sessions": 10000 + i * 1000,
                        "flash_usage": 60 + i * 2,
                        "vpn_throughput": 50000000 + i * 10000000,
                        "firmware": "5.37(ABUH.0)",
                        "product_name": "USG FLEX 200",
                        "serial_number": "S212345678901",
                        "cpu_detail": {
                            "current": 25 + i * 5,
                            "avg_5sec": 28 + i * 5,
                            "avg_1min": 22 + i * 5,
                            "avg_5min": 20 + i * 5
                        }
                    },
                    "poll_timestamp": f"2026-01-27T10:{10+i}:00Z"
                }]
            }
            
            requests.post(
                f"{BASE_URL}/api/connector/device-report",
                json=payload,
                headers={"X-API-Key": API_KEY, "Content-Type": "application/json"}
            )
            time.sleep(0.1)  # Small delay between reports
        
        # Now fetch metrics history
        response = requests.get(
            f"{BASE_URL}/api/connector/device-metrics/{TEST_DEVICE_IP}",
            headers=auth_headers
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        metrics = response.json()
        
        assert isinstance(metrics, list), "Expected list of metrics"
        assert len(metrics) >= 1, "Expected at least 1 metric entry"
        
        # Check that metrics contain expected fields
        latest_metric = metrics[-1] if metrics else {}
        assert "timestamp" in latest_metric, "Metric should have timestamp"
        assert "cpu_usage" in latest_metric, "Metric should have cpu_usage"
        
        print(f"✓ Metrics history returned {len(metrics)} entries")
        print(f"✓ Latest metric: cpu={latest_metric.get('cpu_usage')}%, memory={latest_metric.get('memory_usage')}%, temp={latest_metric.get('temperature')}C")
    
    def test_metrics_history_returns_active_sessions_and_vpn(self, auth_headers):
        """Test that device-metrics endpoint returns active_sessions and vpn_throughput fields."""
        # Fetch metrics history
        response = requests.get(
            f"{BASE_URL}/api/connector/device-metrics/{TEST_DEVICE_IP}",
            headers=auth_headers
        )
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        metrics = response.json()
        
        assert isinstance(metrics, list), "Expected list of metrics"
        assert len(metrics) >= 1, "Expected at least 1 metric entry"
        
        # Find a metric with active_sessions (from Zyxel device)
        zyxel_metrics = [m for m in metrics if m.get("active_sessions") is not None]
        assert len(zyxel_metrics) >= 1, "Expected at least 1 metric with active_sessions"
        
        latest_zyxel = zyxel_metrics[-1]
        assert "active_sessions" in latest_zyxel, "Metric should have active_sessions"
        assert "vpn_throughput" in latest_zyxel, "Metric should have vpn_throughput"
        assert latest_zyxel["active_sessions"] > 0, "active_sessions should be > 0"
        
        print(f"✓ Metrics history includes active_sessions: {latest_zyxel.get('active_sessions')}")
        print(f"✓ Metrics history includes vpn_throughput: {latest_zyxel.get('vpn_throughput')}")


class TestZyxelAlertThresholds:
    """Test alert thresholds for Zyxel firewall (sessions >50k, flash >90%)."""
    
    def test_high_sessions_data_accepted(self, auth_headers):
        """Test that high session count (>50k) data is accepted and stored."""
        payload = {
            "hostname": "test-connector",
            "devices": [{
                "device_ip": TEST_DEVICE_IP,
                "device_name": "Zyxel USG Test - High Sessions",
                "reachable": True,
                "device_class": "zyxel-usg",
                "cpu_usage": 75,
                "memory_usage": 80,
                "firewall": {
                    "active_sessions": 55000,  # Above 50k threshold
                    "flash_usage": 85,
                    "vpn_throughput": 200000000,
                    "firmware": "5.37(ABUH.0)",
                    "product_name": "USG FLEX 200",
                    "serial_number": "S212345678901",
                    "cpu_detail": {"current": 75, "avg_5sec": 78, "avg_1min": 72, "avg_5min": 70}
                },
                "poll_timestamp": "2026-01-27T11:00:00Z"
            }]
        }
        
        response = requests.post(
            f"{BASE_URL}/api/connector/device-report",
            json=payload,
            headers={"X-API-Key": API_KEY, "Content-Type": "application/json"}
        )
        
        assert response.status_code == 200
        
        # Verify data was stored
        status_response = requests.get(
            f"{BASE_URL}/api/connector/device-poll-status",
            headers=auth_headers
        )
        
        statuses = status_response.json()
        zyxel_device = next((s for s in statuses if s.get("device_ip") == TEST_DEVICE_IP), None)
        
        assert zyxel_device is not None
        assert zyxel_device.get("firewall", {}).get("active_sessions") == 55000
        print(f"✓ High sessions (55000 > 50k threshold) data accepted and stored")
    
    def test_high_flash_usage_data_accepted(self, auth_headers):
        """Test that high flash usage (>90%) data is accepted and stored."""
        payload = {
            "hostname": "test-connector",
            "devices": [{
                "device_ip": TEST_DEVICE_IP,
                "device_name": "Zyxel USG Test - High Flash",
                "reachable": True,
                "device_class": "zyxel-usg",
                "cpu_usage": 50,
                "memory_usage": 60,
                "firewall": {
                    "active_sessions": 20000,
                    "flash_usage": 95,  # Above 90% threshold
                    "vpn_throughput": 100000000,
                    "firmware": "5.37(ABUH.0)",
                    "product_name": "USG FLEX 200",
                    "serial_number": "S212345678901",
                    "cpu_detail": {"current": 50, "avg_5sec": 52, "avg_1min": 48, "avg_5min": 45}
                },
                "poll_timestamp": "2026-01-27T11:05:00Z"
            }]
        }
        
        response = requests.post(
            f"{BASE_URL}/api/connector/device-report",
            json=payload,
            headers={"X-API-Key": API_KEY, "Content-Type": "application/json"}
        )
        
        assert response.status_code == 200
        
        # Verify data was stored
        status_response = requests.get(
            f"{BASE_URL}/api/connector/device-poll-status",
            headers=auth_headers
        )
        
        statuses = status_response.json()
        zyxel_device = next((s for s in statuses if s.get("device_ip") == TEST_DEVICE_IP), None)
        
        assert zyxel_device is not None
        assert zyxel_device.get("firewall", {}).get("flash_usage") == 95
        print(f"✓ High flash usage (95% > 90% threshold) data accepted and stored")


class TestLoginFlow:
    """Test login flow works correctly."""
    
    def test_login_with_admin_credentials(self):
        """Test login with admin@86bit.it / admin123."""
        response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        })
        
        assert response.status_code == 200, f"Login failed: {response.status_code} - {response.text}"
        data = response.json()
        assert "token" in data, "Response should contain token"
        assert "user" in data, "Response should contain user"
        assert data["user"]["email"] == ADMIN_EMAIL
        assert data["user"]["role"] == "admin"
        print(f"✓ Login successful for {ADMIN_EMAIL} with role {data['user']['role']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
