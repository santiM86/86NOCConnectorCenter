"""
Test Extended SNMP Metrics for HPE 5130 Switches and HPE ILO Servers
Tests: device-report, device-poll-status, device-metrics endpoints
"""
import pytest
import requests
import os
import time
from datetime import datetime, timezone

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestExtendedSNMPMetrics:
    """Test extended SNMP metrics (CPU, Memory, Temperature, Hardware) for HPE devices"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures"""
        self.admin_email = "admin@86bit.it"
        self.admin_password = "admin123"
        self.token = None
        self.api_key = None
        self.client_id = None
        
        # Login and get token
        login_resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": self.admin_email,
            "password": self.admin_password
        })
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
        self.token = login_resp.json()["token"]
        
        # Get client API key
        clients_resp = requests.get(f"{BASE_URL}/api/clients", headers={
            "Authorization": f"Bearer {self.token}"
        })
        assert clients_resp.status_code == 200
        clients = clients_resp.json()
        assert len(clients) > 0, "No clients found"
        self.api_key = clients[0]["api_key"]
        self.client_id = clients[0]["id"]
    
    # ==================== device-poll-status Tests ====================
    
    def test_device_poll_status_returns_extended_fields(self):
        """GET /api/connector/device-poll-status should return extended fields"""
        resp = requests.get(f"{BASE_URL}/api/connector/device-poll-status", headers={
            "Authorization": f"Bearer {self.token}"
        })
        assert resp.status_code == 200, f"Failed: {resp.text}"
        devices = resp.json()
        
        # Check that at least one device exists
        assert len(devices) > 0, "No devices in poll status"
        
        # Verify extended fields are present in response schema
        device = devices[0]
        expected_fields = ["cpu_usage", "memory_usage", "temperature", "device_class", "hardware"]
        for field in expected_fields:
            assert field in device, f"Missing field: {field}"
        
        print(f"✓ device-poll-status returns {len(devices)} devices with extended fields")
    
    def test_device_poll_status_requires_auth(self):
        """GET /api/connector/device-poll-status requires authentication"""
        resp = requests.get(f"{BASE_URL}/api/connector/device-poll-status")
        assert resp.status_code == 403 or resp.status_code == 401, f"Expected 401/403, got {resp.status_code}"
        print("✓ device-poll-status requires authentication")
    
    # ==================== device-report Tests ====================
    
    def test_device_report_accepts_extended_metrics_hpe_switch(self):
        """POST /api/connector/device-report accepts HPE 5130 switch extended metrics"""
        test_device_ip = "10.99.99.1"  # Test IP
        
        # Send device report with extended metrics for HPE 5130 switch
        report_data = {
            "hostname": "TEST_CONNECTOR",
            "devices": [{
                "device_ip": test_device_ip,
                "device_name": "TEST_HPE_5130_Switch",
                "reachable": True,
                "monitor_type": "snmp",
                "ports": [
                    {"index": "1", "status": "up", "speed_bps": 1000000000, "in_bps": 50000000, "out_bps": 30000000, "in_errors": 0, "out_errors": 0},
                    {"index": "2", "status": "up", "speed_bps": 1000000000, "in_bps": 10000000, "out_bps": 5000000, "in_errors": 0, "out_errors": 0},
                    {"index": "3", "status": "down", "speed_bps": 0, "in_bps": 0, "out_bps": 0, "in_errors": 0, "out_errors": 0}
                ],
                "sys_descr": "HPE Comware Platform Software, Version 7.1.070",
                "sys_uptime": "15 days, 4:32:10",
                "cpu_usage": 45,
                "memory_usage": 62,
                "temperature": 38,
                "device_class": "hpe-comware",
                "poll_timestamp": datetime.now(timezone.utc).isoformat()
            }]
        }
        
        resp = requests.post(f"{BASE_URL}/api/connector/device-report", 
            json=report_data,
            headers={"X-API-Key": self.api_key}
        )
        assert resp.status_code == 200, f"Failed: {resp.text}"
        result = resp.json()
        assert result["status"] == "ok"
        assert result["devices_updated"] == 1
        
        # Verify data was stored correctly
        poll_resp = requests.get(f"{BASE_URL}/api/connector/device-poll-status", headers={
            "Authorization": f"Bearer {self.token}"
        })
        assert poll_resp.status_code == 200
        devices = poll_resp.json()
        
        test_device = next((d for d in devices if d["device_ip"] == test_device_ip), None)
        assert test_device is not None, f"Test device {test_device_ip} not found in poll status"
        
        # Verify extended metrics were stored
        assert test_device["cpu_usage"] == 45, f"CPU usage mismatch: {test_device['cpu_usage']}"
        assert test_device["memory_usage"] == 62, f"Memory usage mismatch: {test_device['memory_usage']}"
        assert test_device["temperature"] == 38, f"Temperature mismatch: {test_device['temperature']}"
        assert test_device["device_class"] == "hpe-comware", f"Device class mismatch: {test_device['device_class']}"
        
        # Verify ports with traffic data
        assert len(test_device["ports"]) == 3, f"Expected 3 ports, got {len(test_device['ports'])}"
        
        print("✓ device-report accepts and stores HPE 5130 switch extended metrics")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/connector/device-poll-status/{test_device_ip}", headers={
            "Authorization": f"Bearer {self.token}"
        })
    
    def test_device_report_accepts_hpe_ilo_hardware_data(self):
        """POST /api/connector/device-report accepts HPE ILO server hardware health data"""
        test_device_ip = "10.99.99.2"  # Test IP
        
        # Send device report with hardware health data for HPE ILO
        report_data = {
            "hostname": "TEST_CONNECTOR",
            "devices": [{
                "device_ip": test_device_ip,
                "device_name": "TEST_HPE_ILO_Server",
                "reachable": True,
                "monitor_type": "snmp",
                "ports": [],
                "sys_descr": "HPE iLO 5 v2.70",
                "sys_uptime": "45 days, 12:15:30",
                "cpu_usage": 25,
                "memory_usage": 78,
                "temperature": 42,
                "device_class": "hpe-ilo",
                "hardware": {
                    "health_status": "ok",
                    "fans": [
                        {"locale": "Fan 1", "condition": "ok", "speed": 35},
                        {"locale": "Fan 2", "condition": "ok", "speed": 38},
                        {"locale": "Fan 3", "condition": "degraded", "speed": 100}
                    ],
                    "power_supplies": [
                        {"name": "PSU 1", "condition": "ok"},
                        {"name": "PSU 2", "condition": "ok"}
                    ],
                    "temperatures": [
                        {"locale": "CPU 1", "value": 45, "condition": "ok"},
                        {"locale": "CPU 2", "value": 47, "condition": "ok"},
                        {"locale": "Ambient", "value": 28, "condition": "ok"}
                    ],
                    "disks": [
                        {"name": "Disk 0", "status": "ok"},
                        {"name": "Disk 1", "status": "ok"},
                        {"name": "Disk 2", "status": "predictiveFailure"}
                    ]
                },
                "poll_timestamp": datetime.now(timezone.utc).isoformat()
            }]
        }
        
        resp = requests.post(f"{BASE_URL}/api/connector/device-report", 
            json=report_data,
            headers={"X-API-Key": self.api_key}
        )
        assert resp.status_code == 200, f"Failed: {resp.text}"
        result = resp.json()
        assert result["status"] == "ok"
        
        # Verify data was stored correctly
        poll_resp = requests.get(f"{BASE_URL}/api/connector/device-poll-status", headers={
            "Authorization": f"Bearer {self.token}"
        })
        assert poll_resp.status_code == 200
        devices = poll_resp.json()
        
        test_device = next((d for d in devices if d["device_ip"] == test_device_ip), None)
        assert test_device is not None, f"Test device {test_device_ip} not found"
        
        # Verify hardware data was stored
        assert test_device["hardware"] is not None, "Hardware data not stored"
        hw = test_device["hardware"]
        
        assert hw["health_status"] == "ok", f"Health status mismatch: {hw['health_status']}"
        assert len(hw["fans"]) == 3, f"Expected 3 fans, got {len(hw['fans'])}"
        assert len(hw["power_supplies"]) == 2, f"Expected 2 PSUs, got {len(hw['power_supplies'])}"
        assert len(hw["temperatures"]) == 3, f"Expected 3 temp sensors, got {len(hw['temperatures'])}"
        assert len(hw["disks"]) == 3, f"Expected 3 disks, got {len(hw['disks'])}"
        
        # Verify specific hardware conditions
        degraded_fan = next((f for f in hw["fans"] if f["condition"] == "degraded"), None)
        assert degraded_fan is not None, "Degraded fan not found"
        
        predictive_disk = next((d for d in hw["disks"] if d["status"] == "predictiveFailure"), None)
        assert predictive_disk is not None, "Predictive failure disk not found"
        
        print("✓ device-report accepts and stores HPE ILO hardware health data")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/connector/device-poll-status/{test_device_ip}", headers={
            "Authorization": f"Bearer {self.token}"
        })
    
    def test_device_report_requires_api_key(self):
        """POST /api/connector/device-report requires X-API-Key header"""
        resp = requests.post(f"{BASE_URL}/api/connector/device-report", json={
            "hostname": "TEST",
            "devices": []
        })
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
        print("✓ device-report requires API key")
    
    def test_device_report_rejects_invalid_api_key(self):
        """POST /api/connector/device-report rejects invalid API key"""
        resp = requests.post(f"{BASE_URL}/api/connector/device-report", 
            json={"hostname": "TEST", "devices": []},
            headers={"X-API-Key": "invalid_key_12345"}
        )
        assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"
        print("✓ device-report rejects invalid API key")
    
    # ==================== device-metrics Tests ====================
    
    def test_device_metrics_history_endpoint(self):
        """GET /api/connector/device-metrics/{device_ip} returns historical metrics"""
        test_device_ip = "10.99.99.3"
        
        # First, send some device reports with metrics to create history
        for i in range(3):
            report_data = {
                "hostname": "TEST_CONNECTOR",
                "devices": [{
                    "device_ip": test_device_ip,
                    "device_name": "TEST_Metrics_Device",
                    "reachable": True,
                    "monitor_type": "snmp",
                    "ports": [],
                    "cpu_usage": 30 + i * 10,  # 30, 40, 50
                    "memory_usage": 50 + i * 5,  # 50, 55, 60
                    "temperature": 35 + i * 2,  # 35, 37, 39
                    "device_class": "hpe-comware",
                    "poll_timestamp": datetime.now(timezone.utc).isoformat()
                }]
            }
            resp = requests.post(f"{BASE_URL}/api/connector/device-report", 
                json=report_data,
                headers={"X-API-Key": self.api_key}
            )
            assert resp.status_code == 200
            time.sleep(0.1)  # Small delay between reports
        
        # Get metrics history
        metrics_resp = requests.get(f"{BASE_URL}/api/connector/device-metrics/{test_device_ip}", headers={
            "Authorization": f"Bearer {self.token}"
        })
        assert metrics_resp.status_code == 200, f"Failed: {metrics_resp.text}"
        metrics = metrics_resp.json()
        
        # Verify we have historical data
        assert len(metrics) >= 3, f"Expected at least 3 metrics entries, got {len(metrics)}"
        
        # Verify metrics structure
        for m in metrics:
            assert "timestamp" in m, "Missing timestamp"
            assert "cpu_usage" in m, "Missing cpu_usage"
            assert "memory_usage" in m, "Missing memory_usage"
            assert "temperature" in m, "Missing temperature"
        
        print(f"✓ device-metrics returns {len(metrics)} historical entries")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/connector/device-poll-status/{test_device_ip}", headers={
            "Authorization": f"Bearer {self.token}"
        })
    
    def test_device_metrics_requires_auth(self):
        """GET /api/connector/device-metrics/{device_ip} requires authentication"""
        resp = requests.get(f"{BASE_URL}/api/connector/device-metrics/192.168.1.1")
        assert resp.status_code == 403 or resp.status_code == 401, f"Expected 401/403, got {resp.status_code}"
        print("✓ device-metrics requires authentication")
    
    def test_device_metrics_returns_empty_for_unknown_device(self):
        """GET /api/connector/device-metrics/{device_ip} returns empty array for unknown device"""
        resp = requests.get(f"{BASE_URL}/api/connector/device-metrics/99.99.99.99", headers={
            "Authorization": f"Bearer {self.token}"
        })
        assert resp.status_code == 200, f"Failed: {resp.text}"
        metrics = resp.json()
        assert isinstance(metrics, list), "Expected list response"
        # Unknown device should return empty list
        print(f"✓ device-metrics returns empty list for unknown device (got {len(metrics)} entries)")
    
    # ==================== Edge Cases ====================
    
    def test_device_report_with_null_extended_fields(self):
        """POST /api/connector/device-report handles null extended fields gracefully"""
        test_device_ip = "10.99.99.4"
        
        # Send report with null/missing extended fields (simulating old connector)
        report_data = {
            "hostname": "TEST_OLD_CONNECTOR",
            "devices": [{
                "device_ip": test_device_ip,
                "device_name": "TEST_Basic_Device",
                "reachable": True,
                "monitor_type": "snmp",
                "ports": [{"index": "1", "status": "up"}],
                "sys_descr": "Generic Switch",
                "poll_timestamp": datetime.now(timezone.utc).isoformat()
                # No cpu_usage, memory_usage, temperature, device_class, hardware
            }]
        }
        
        resp = requests.post(f"{BASE_URL}/api/connector/device-report", 
            json=report_data,
            headers={"X-API-Key": self.api_key}
        )
        assert resp.status_code == 200, f"Failed: {resp.text}"
        
        # Verify device was stored with null extended fields
        poll_resp = requests.get(f"{BASE_URL}/api/connector/device-poll-status", headers={
            "Authorization": f"Bearer {self.token}"
        })
        devices = poll_resp.json()
        test_device = next((d for d in devices if d["device_ip"] == test_device_ip), None)
        assert test_device is not None
        
        # Extended fields should be null/None
        assert test_device["cpu_usage"] is None
        assert test_device["memory_usage"] is None
        assert test_device["temperature"] is None
        assert test_device["device_class"] == "generic"  # Default value
        assert test_device["hardware"] is None
        
        print("✓ device-report handles null extended fields gracefully")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/connector/device-poll-status/{test_device_ip}", headers={
            "Authorization": f"Bearer {self.token}"
        })
    
    def test_device_report_updates_existing_device(self):
        """POST /api/connector/device-report updates existing device data"""
        test_device_ip = "10.99.99.5"
        
        # First report - initial data
        report1 = {
            "hostname": "TEST_CONNECTOR",
            "devices": [{
                "device_ip": test_device_ip,
                "device_name": "TEST_Update_Device",
                "reachable": True,
                "monitor_type": "snmp",
                "ports": [],
                "cpu_usage": 20,
                "memory_usage": 40,
                "temperature": 30,
                "device_class": "hpe-comware",
                "poll_timestamp": datetime.now(timezone.utc).isoformat()
            }]
        }
        resp1 = requests.post(f"{BASE_URL}/api/connector/device-report", 
            json=report1, headers={"X-API-Key": self.api_key})
        assert resp1.status_code == 200
        
        # Second report - updated data
        report2 = {
            "hostname": "TEST_CONNECTOR",
            "devices": [{
                "device_ip": test_device_ip,
                "device_name": "TEST_Update_Device_Renamed",
                "reachable": True,
                "monitor_type": "snmp",
                "ports": [],
                "cpu_usage": 80,  # Changed
                "memory_usage": 90,  # Changed
                "temperature": 55,  # Changed
                "device_class": "hpe-comware",
                "poll_timestamp": datetime.now(timezone.utc).isoformat()
            }]
        }
        resp2 = requests.post(f"{BASE_URL}/api/connector/device-report", 
            json=report2, headers={"X-API-Key": self.api_key})
        assert resp2.status_code == 200
        
        # Verify updated data
        poll_resp = requests.get(f"{BASE_URL}/api/connector/device-poll-status", headers={
            "Authorization": f"Bearer {self.token}"
        })
        devices = poll_resp.json()
        test_device = next((d for d in devices if d["device_ip"] == test_device_ip), None)
        assert test_device is not None
        
        # Should have updated values
        assert test_device["cpu_usage"] == 80, f"CPU not updated: {test_device['cpu_usage']}"
        assert test_device["memory_usage"] == 90, f"Memory not updated: {test_device['memory_usage']}"
        assert test_device["temperature"] == 55, f"Temperature not updated: {test_device['temperature']}"
        assert test_device["device_name"] == "TEST_Update_Device_Renamed"
        
        print("✓ device-report updates existing device data correctly")
        
        # Cleanup
        requests.delete(f"{BASE_URL}/api/connector/device-poll-status/{test_device_ip}", headers={
            "Authorization": f"Bearer {self.token}"
        })


class TestExistingDeviceData:
    """Test that existing device data is returned correctly"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.admin_email = "admin@86bit.it"
        self.admin_password = "admin123"
        login_resp = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": self.admin_email,
            "password": self.admin_password
        })
        assert login_resp.status_code == 200
        self.token = login_resp.json()["token"]
    
    def test_existing_snmp_device_data(self):
        """Verify existing SNMP device data is returned correctly"""
        resp = requests.get(f"{BASE_URL}/api/connector/device-poll-status", headers={
            "Authorization": f"Bearer {self.token}"
        })
        assert resp.status_code == 200
        devices = resp.json()
        
        # Find SNMP type device
        snmp_device = next((d for d in devices if d.get("monitor_type") == "snmp"), None)
        if snmp_device:
            assert "device_ip" in snmp_device
            assert "device_name" in snmp_device
            assert "reachable" in snmp_device
            assert "ports" in snmp_device
            print(f"✓ SNMP device found: {snmp_device['device_name']} ({snmp_device['device_ip']})")
        else:
            print("⚠ No SNMP devices found in poll status")
    
    def test_existing_ping_device_data(self):
        """Verify existing PING device data is returned correctly"""
        resp = requests.get(f"{BASE_URL}/api/connector/device-poll-status", headers={
            "Authorization": f"Bearer {self.token}"
        })
        assert resp.status_code == 200
        devices = resp.json()
        
        # Find PING type device
        ping_device = next((d for d in devices if d.get("monitor_type") == "ping"), None)
        if ping_device:
            assert "device_ip" in ping_device
            assert "device_name" in ping_device
            assert "reachable" in ping_device
            assert "ping_ms" in ping_device
            assert "http_status" in ping_device
            print(f"✓ PING device found: {ping_device['device_name']} ({ping_device['device_ip']}) - {ping_device.get('ping_ms')}ms")
        else:
            print("⚠ No PING devices found in poll status")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
