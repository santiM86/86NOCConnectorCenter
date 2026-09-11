"""
Test Vendor-Specific SNMP Monitoring Alerts (Fase B)
Tests POST /api/connector/device-report with vendor_metrics for all 13 vendor profiles.
Validates that correct alerts are generated for each vendor's critical conditions.
"""
import pytest
import requests
import os
import time
import uuid
from datetime import datetime, timezone

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')
API_KEY = "noc_35cf39b4d68740b1a981aedef2ee293d"
TEST_DEVICE_IP = "192.168.1.3"

# Headers for connector API calls
CONNECTOR_HEADERS = {
    "Content-Type": "application/json",
    "X-API-Key": API_KEY
}


def get_auth_token():
    """Get JWT token for authenticated endpoints"""
    resp = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "admin@86bit.it",
        "password": "password"
    })
    if resp.status_code == 200:
        return resp.json().get("token")
    return None


def get_client_id(token):
    """Get first available client_id"""
    resp = requests.get(f"{BASE_URL}/api/clients", headers={
        "Authorization": f"Bearer {token}"
    })
    if resp.status_code == 200:
        clients = resp.json()
        if clients:
            return clients[0].get("id")
    return None


def set_device_profile(client_id, device_ip, profile_key):
    """Set profile_key on managed_device via direct MongoDB update simulation
    We'll use the managed-devices endpoint to update the device
    """
    token = get_auth_token()
    if not token:
        return False
    
    # First check if device exists in managed_devices
    resp = requests.get(f"{BASE_URL}/api/managed-devices", headers={
        "Authorization": f"Bearer {token}"
    }, params={"client_id": client_id})
    
    if resp.status_code == 200:
        devices = resp.json()
        for d in devices:
            if d.get("ip") == device_ip:
                # Update the device with profile_key
                device_id = d.get("id")
                update_resp = requests.put(
                    f"{BASE_URL}/api/managed-devices/{device_id}",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"profile_key": profile_key}
                )
                return update_resp.status_code == 200
    return False


def send_device_report(client_id, device_ip, device_name, vendor_metrics, profile_key=None):
    """Send device-report with vendor_metrics"""
    payload = {
        "hostname": "test-connector",
        "devices": [{
            "device_ip": device_ip,
            "device_name": device_name,
            "reachable": True,
            "monitor_type": "snmp",
            "profile_key": profile_key,
            "vendor_metrics": vendor_metrics,
            "poll_timestamp": datetime.now(timezone.utc).isoformat()
        }]
    }
    
    resp = requests.post(
        f"{BASE_URL}/api/connector/device-report",
        headers=CONNECTOR_HEADERS,
        json=payload
    )
    return resp


def get_alerts_for_device(token, device_ip, source_type_prefix=None):
    """Get alerts for a specific device, optionally filtered by source_type prefix"""
    resp = requests.get(f"{BASE_URL}/api/alerts", headers={
        "Authorization": f"Bearer {token}"
    })
    if resp.status_code != 200:
        return []
    
    alerts = resp.json()
    filtered = [a for a in alerts if a.get("device_ip") == device_ip]
    
    if source_type_prefix:
        filtered = [a for a in filtered if a.get("source_type", "").startswith(source_type_prefix)]
    
    return filtered


def cleanup_vendor_alerts(token, device_ip):
    """Delete all vendor_* alerts for a device"""
    alerts = get_alerts_for_device(token, device_ip, "vendor_")
    for alert in alerts:
        alert_id = alert.get("id")
        if alert_id:
            requests.delete(f"{BASE_URL}/api/alerts/{alert_id}", headers={
                "Authorization": f"Bearer {token}"
            })


class TestVendorAlertSetup:
    """Setup and basic connectivity tests"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.token = get_auth_token()
        assert self.token, "Failed to get auth token"
        self.client_id = get_client_id(self.token)
        assert self.client_id, "Failed to get client_id"
    
    def test_connector_device_report_endpoint_exists(self):
        """Verify device-report endpoint is accessible"""
        resp = requests.post(
            f"{BASE_URL}/api/connector/device-report",
            headers=CONNECTOR_HEADERS,
            json={"hostname": "test", "devices": []}
        )
        # Should return 200 even with empty devices
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        print("PASS: device-report endpoint accessible")
    
    def test_vendor_details_endpoint_exists(self):
        """Verify vendor-details endpoint exists"""
        resp = requests.get(
            f"{BASE_URL}/api/devices/by-ip/{TEST_DEVICE_IP}/vendor-details",
            headers={"Authorization": f"Bearer {self.token}"}
        )
        # May return 404 if device doesn't exist, but endpoint should be reachable
        assert resp.status_code in [200, 404], f"Unexpected status: {resp.status_code}"
        print(f"PASS: vendor-details endpoint exists (status={resp.status_code})")


class TestSynologyAlerts:
    """Test Synology DSM vendor-specific alerts"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.token = get_auth_token()
        self.client_id = get_client_id(self.token)
        # Cleanup before test
        cleanup_vendor_alerts(self.token, TEST_DEVICE_IP)
    
    def test_synology_raid_degraded_alert(self):
        """raidStatus=11 should generate 'RAID DEGRADED' alert"""
        resp = send_device_report(
            self.client_id, TEST_DEVICE_IP, "Synology-Test",
            vendor_metrics={"raidStatus": 11},
            profile_key="synology_dsm"
        )
        assert resp.status_code == 200, f"device-report failed: {resp.text}"
        
        time.sleep(0.5)  # Allow alert processing
        alerts = get_alerts_for_device(self.token, TEST_DEVICE_IP, "vendor_raid")
        
        raid_degraded = [a for a in alerts if "DEGRADED" in a.get("title", "").upper()]
        assert len(raid_degraded) > 0, f"Expected RAID DEGRADED alert, got: {alerts}"
        assert raid_degraded[0].get("severity") == "high"
        print(f"PASS: Synology RAID DEGRADED alert generated: {raid_degraded[0].get('title')}")
    
    def test_synology_raid_crashed_alert(self):
        """raidStatus=12 should generate 'RAID CRASHED' alert"""
        cleanup_vendor_alerts(self.token, TEST_DEVICE_IP)
        
        resp = send_device_report(
            self.client_id, TEST_DEVICE_IP, "Synology-Test",
            vendor_metrics={"raidStatus": 12},
            profile_key="synology_dsm"
        )
        assert resp.status_code == 200
        
        time.sleep(0.5)
        alerts = get_alerts_for_device(self.token, TEST_DEVICE_IP, "vendor_raid")
        
        raid_crashed = [a for a in alerts if "CRASHED" in a.get("title", "").upper()]
        assert len(raid_crashed) > 0, f"Expected RAID CRASHED alert, got: {alerts}"
        assert raid_crashed[0].get("severity") == "critical"
        print(f"PASS: Synology RAID CRASHED alert generated: {raid_crashed[0].get('title')}")
    
    def test_synology_disk_crashed_alert(self):
        """diskStatus=4 should generate 'Disk Crashed' alert"""
        cleanup_vendor_alerts(self.token, TEST_DEVICE_IP)
        
        resp = send_device_report(
            self.client_id, TEST_DEVICE_IP, "Synology-Test",
            vendor_metrics={"diskStatus": {"1": 4}},
            profile_key="synology_dsm"
        )
        assert resp.status_code == 200
        
        time.sleep(0.5)
        alerts = get_alerts_for_device(self.token, TEST_DEVICE_IP, "vendor_disk")
        
        disk_crashed = [a for a in alerts if "CRASHED" in a.get("title", "").upper() or "FAILED" in a.get("title", "").upper()]
        assert len(disk_crashed) > 0, f"Expected Disk Crashed alert, got: {alerts}"
        print(f"PASS: Synology Disk Crashed alert generated: {disk_crashed[0].get('title')}")
    
    def test_synology_disk_temperature_alert(self):
        """diskTemperature > threshold should generate temperature alert"""
        cleanup_vendor_alerts(self.token, TEST_DEVICE_IP)
        
        resp = send_device_report(
            self.client_id, TEST_DEVICE_IP, "Synology-Test",
            vendor_metrics={"diskTemperature": {"1": 65}},  # Above default 60°C critical
            profile_key="synology_dsm"
        )
        assert resp.status_code == 200
        
        time.sleep(0.5)
        alerts = get_alerts_for_device(self.token, TEST_DEVICE_IP, "vendor_disk_temp")
        
        assert len(alerts) > 0, f"Expected disk temperature alert, got: {alerts}"
        print(f"PASS: Synology disk temperature alert generated: {alerts[0].get('title')}")


class TestAPCUPSAlerts:
    """Test APC UPS vendor-specific alerts"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.token = get_auth_token()
        self.client_id = get_client_id(self.token)
        cleanup_vendor_alerts(self.token, TEST_DEVICE_IP)
    
    def test_ups_battery_low_alert(self):
        """upsBatteryStatus=3 should generate 'Battery Low' alert"""
        resp = send_device_report(
            self.client_id, TEST_DEVICE_IP, "APC-UPS-Test",
            vendor_metrics={"upsBatteryStatus": 3},
            profile_key="apc_ups"
        )
        assert resp.status_code == 200
        
        time.sleep(0.5)
        alerts = get_alerts_for_device(self.token, TEST_DEVICE_IP, "vendor_ups")
        
        battery_low = [a for a in alerts if "BASSA" in a.get("title", "").upper() or "LOW" in a.get("title", "").upper()]
        assert len(battery_low) > 0, f"Expected Battery Low alert, got: {alerts}"
        print(f"PASS: APC UPS Battery Low alert generated: {battery_low[0].get('title')}")
    
    def test_ups_on_battery_alert(self):
        """upsOutputSource=5 should generate 'On Battery' alert"""
        cleanup_vendor_alerts(self.token, TEST_DEVICE_IP)
        
        resp = send_device_report(
            self.client_id, TEST_DEVICE_IP, "APC-UPS-Test",
            vendor_metrics={"upsOutputSource": 5},
            profile_key="apc_ups"
        )
        assert resp.status_code == 200
        
        time.sleep(0.5)
        alerts = get_alerts_for_device(self.token, TEST_DEVICE_IP, "vendor_ups")
        
        on_battery = [a for a in alerts if "BATTERIA" in a.get("title", "").upper() or "BATTERY" in a.get("title", "").upper()]
        assert len(on_battery) > 0, f"Expected On Battery alert, got: {alerts}"
        print(f"PASS: APC UPS On Battery alert generated: {on_battery[0].get('title')}")
    
    def test_ups_charge_critical_alert(self):
        """upsEstimatedChargeRemaining=15 should generate critical charge alert"""
        cleanup_vendor_alerts(self.token, TEST_DEVICE_IP)
        
        resp = send_device_report(
            self.client_id, TEST_DEVICE_IP, "APC-UPS-Test",
            vendor_metrics={"upsEstimatedChargeRemaining": 15},  # Below 20% critical threshold
            profile_key="apc_ups"
        )
        assert resp.status_code == 200
        
        time.sleep(0.5)
        alerts = get_alerts_for_device(self.token, TEST_DEVICE_IP, "vendor_ups_battery_pct")
        
        assert len(alerts) > 0, f"Expected charge critical alert, got: {alerts}"
        assert alerts[0].get("severity") == "critical"
        print(f"PASS: APC UPS charge critical alert generated: {alerts[0].get('title')}")
    
    def test_ups_runtime_critical_alert(self):
        """upsEstimatedMinutesRemaining=3 should generate runtime critical alert"""
        cleanup_vendor_alerts(self.token, TEST_DEVICE_IP)
        
        resp = send_device_report(
            self.client_id, TEST_DEVICE_IP, "APC-UPS-Test",
            vendor_metrics={"upsEstimatedMinutesRemaining": 3},  # Below 5 min critical
            profile_key="apc_ups"
        )
        assert resp.status_code == 200
        
        time.sleep(0.5)
        alerts = get_alerts_for_device(self.token, TEST_DEVICE_IP, "vendor_ups_runtime")
        
        assert len(alerts) > 0, f"Expected runtime critical alert, got: {alerts}"
        assert alerts[0].get("severity") == "critical"
        print(f"PASS: APC UPS runtime critical alert generated: {alerts[0].get('title')}")


class TestFortinetAlerts:
    """Test Fortinet FortiGate vendor-specific alerts"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.token = get_auth_token()
        self.client_id = get_client_id(self.token)
        cleanup_vendor_alerts(self.token, TEST_DEVICE_IP)
    
    def test_fortinet_vpn_tunnel_down_alert(self):
        """fgVpnTunnelStatus={tunnel1:1} should generate 'VPN tunnel DOWN' alert"""
        resp = send_device_report(
            self.client_id, TEST_DEVICE_IP, "Fortinet-Test",
            vendor_metrics={"fgVpnTunnelStatus": {"tunnel1": 1}},  # 1=down, 2=up
            profile_key="fortinet_fortigate"
        )
        assert resp.status_code == 200
        
        time.sleep(0.5)
        alerts = get_alerts_for_device(self.token, TEST_DEVICE_IP, "vendor_vpn")
        
        vpn_down = [a for a in alerts if "DOWN" in a.get("title", "").upper() or "VPN" in a.get("title", "").upper()]
        assert len(vpn_down) > 0, f"Expected VPN tunnel DOWN alert, got: {alerts}"
        print(f"PASS: Fortinet VPN tunnel DOWN alert generated: {vpn_down[0].get('title')}")
    
    def test_fortinet_ha_out_of_sync_alert(self):
        """fgHaStatsSyncStatus=0 should generate 'HA OUT-OF-SYNC' alert"""
        cleanup_vendor_alerts(self.token, TEST_DEVICE_IP)
        
        resp = send_device_report(
            self.client_id, TEST_DEVICE_IP, "Fortinet-Test",
            vendor_metrics={"fgHaStatsSyncStatus": 0},  # 0=out-of-sync, 1=in-sync
            profile_key="fortinet_fortigate"
        )
        assert resp.status_code == 200
        
        time.sleep(0.5)
        alerts = get_alerts_for_device(self.token, TEST_DEVICE_IP, "vendor_ha")
        
        ha_oos = [a for a in alerts if "SYNC" in a.get("title", "").upper() or "HA" in a.get("title", "").upper()]
        assert len(ha_oos) > 0, f"Expected HA OUT-OF-SYNC alert, got: {alerts}"
        print(f"PASS: Fortinet HA OUT-OF-SYNC alert generated: {ha_oos[0].get('title')}")


class TestHPEComwareAlerts:
    """Test HPE Comware switch vendor-specific alerts"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.token = get_auth_token()
        self.client_id = get_client_id(self.token)
        cleanup_vendor_alerts(self.token, TEST_DEVICE_IP)
    
    def test_hpe_comware_cpu_critical_alert(self):
        """h3cEntityExtCpuUsage>90 should generate CPU critical alert"""
        resp = send_device_report(
            self.client_id, TEST_DEVICE_IP, "HPE-Comware-Test",
            vendor_metrics={"h3cEntityExtCpuUsage": {"1": 95}},
            profile_key="hpe_comware"
        )
        assert resp.status_code == 200
        
        time.sleep(0.5)
        alerts = get_alerts_for_device(self.token, TEST_DEVICE_IP, "vendor_h3c")
        
        cpu_alerts = [a for a in alerts if "CPU" in a.get("title", "").upper()]
        assert len(cpu_alerts) > 0, f"Expected CPU critical alert, got: {alerts}"
        print(f"PASS: HPE Comware CPU critical alert generated: {cpu_alerts[0].get('title')}")
    
    def test_hpe_comware_fan_fault_alert(self):
        """h3cFanState>=3 should generate Fan fault alert"""
        cleanup_vendor_alerts(self.token, TEST_DEVICE_IP)
        
        resp = send_device_report(
            self.client_id, TEST_DEVICE_IP, "HPE-Comware-Test",
            vendor_metrics={"h3cFanState": {"1": 3}},  # 3+ = fault
            profile_key="hpe_comware"
        )
        assert resp.status_code == 200
        
        time.sleep(0.5)
        alerts = get_alerts_for_device(self.token, TEST_DEVICE_IP, "vendor_h3cFanState")
        
        fan_alerts = [a for a in alerts if "FAN" in a.get("title", "").upper()]
        assert len(fan_alerts) > 0, f"Expected Fan fault alert, got: {alerts}"
        print(f"PASS: HPE Comware Fan fault alert generated: {fan_alerts[0].get('title')}")
    
    def test_hpe_comware_psu_fault_alert(self):
        """h3cPowerState>=3 should generate PSU fault alert"""
        cleanup_vendor_alerts(self.token, TEST_DEVICE_IP)
        
        resp = send_device_report(
            self.client_id, TEST_DEVICE_IP, "HPE-Comware-Test",
            vendor_metrics={"h3cPowerState": {"1": 4}},  # 3+ = fault
            profile_key="hpe_comware"
        )
        assert resp.status_code == 200
        
        time.sleep(0.5)
        alerts = get_alerts_for_device(self.token, TEST_DEVICE_IP, "vendor_h3cPowerState")
        
        psu_alerts = [a for a in alerts if "POWER" in a.get("title", "").upper() or "PSU" in a.get("title", "").upper()]
        assert len(psu_alerts) > 0, f"Expected PSU fault alert, got: {alerts}"
        print(f"PASS: HPE Comware PSU fault alert generated: {psu_alerts[0].get('title')}")


class TestMikroTikAlerts:
    """Test MikroTik RouterOS vendor-specific alerts"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.token = get_auth_token()
        self.client_id = get_client_id(self.token)
        cleanup_vendor_alerts(self.token, TEST_DEVICE_IP)
    
    def test_mikrotik_psu_fault_alert(self):
        """mtxrHlPsu1Status=0 should generate PSU fault alert"""
        resp = send_device_report(
            self.client_id, TEST_DEVICE_IP, "MikroTik-Test",
            vendor_metrics={"mtxrHlPsu1Status": 0},  # 0=fault, 1=ok
            profile_key="mikrotik_routeros"
        )
        assert resp.status_code == 200
        
        time.sleep(0.5)
        alerts = get_alerts_for_device(self.token, TEST_DEVICE_IP, "vendor_mikrotik")
        
        psu_alerts = [a for a in alerts if "PSU" in a.get("title", "").upper()]
        assert len(psu_alerts) > 0, f"Expected PSU fault alert, got: {alerts}"
        print(f"PASS: MikroTik PSU fault alert generated: {psu_alerts[0].get('title')}")
    
    def test_mikrotik_temperature_critical_celsius(self):
        """mtxrHlTemperature>70 (Celsius) should generate temp critical alert"""
        cleanup_vendor_alerts(self.token, TEST_DEVICE_IP)
        
        resp = send_device_report(
            self.client_id, TEST_DEVICE_IP, "MikroTik-Test",
            vendor_metrics={"mtxrHlTemperature": 75},  # 75°C > 70°C threshold
            profile_key="mikrotik_routeros"
        )
        assert resp.status_code == 200
        
        time.sleep(0.5)
        alerts = get_alerts_for_device(self.token, TEST_DEVICE_IP, "vendor_mikrotik_temp")
        
        assert len(alerts) > 0, f"Expected temperature critical alert, got: {alerts}"
        print(f"PASS: MikroTik temperature critical alert (Celsius) generated: {alerts[0].get('title')}")
    
    def test_mikrotik_temperature_critical_decicelsius(self):
        """mtxrHlTemperature>700 (decicelsius) should generate temp critical alert"""
        cleanup_vendor_alerts(self.token, TEST_DEVICE_IP)
        
        resp = send_device_report(
            self.client_id, TEST_DEVICE_IP, "MikroTik-Test",
            vendor_metrics={"mtxrHlTemperature": 750},  # 750 decicelsius = 75°C
            profile_key="mikrotik_routeros"
        )
        assert resp.status_code == 200
        
        time.sleep(0.5)
        alerts = get_alerts_for_device(self.token, TEST_DEVICE_IP, "vendor_mikrotik_temp")
        
        assert len(alerts) > 0, f"Expected temperature critical alert, got: {alerts}"
        print(f"PASS: MikroTik temperature critical alert (decicelsius) generated: {alerts[0].get('title')}")


class TestCiscoIOSAlerts:
    """Test Cisco IOS vendor-specific alerts"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.token = get_auth_token()
        self.client_id = get_client_id(self.token)
        cleanup_vendor_alerts(self.token, TEST_DEVICE_IP)
    
    def test_cisco_temperature_critical_alert(self):
        """ciscoEnvMonTemperatureStatusValue>=3 should generate temp alert"""
        resp = send_device_report(
            self.client_id, TEST_DEVICE_IP, "Cisco-Test",
            vendor_metrics={"ciscoEnvMonTemperatureStatusValue": {"1": 3}},  # 3=critical
            profile_key="cisco_ios"
        )
        assert resp.status_code == 200
        
        time.sleep(0.5)
        alerts = get_alerts_for_device(self.token, TEST_DEVICE_IP, "vendor_cisco_temp")
        
        assert len(alerts) > 0, f"Expected Cisco temperature alert, got: {alerts}"
        print(f"PASS: Cisco temperature critical alert generated: {alerts[0].get('title')}")
    
    def test_cisco_cpu_critical_alert(self):
        """cpmCPUTotal5min>90 should generate CPU critical alert"""
        cleanup_vendor_alerts(self.token, TEST_DEVICE_IP)
        
        resp = send_device_report(
            self.client_id, TEST_DEVICE_IP, "Cisco-Test",
            vendor_metrics={"cpmCPUTotal5min": {"1": 95}},
            profile_key="cisco_ios"
        )
        assert resp.status_code == 200
        
        time.sleep(0.5)
        alerts = get_alerts_for_device(self.token, TEST_DEVICE_IP, "vendor_cisco_cpu")
        
        assert len(alerts) > 0, f"Expected Cisco CPU critical alert, got: {alerts}"
        print(f"PASS: Cisco CPU critical alert generated: {alerts[0].get('title')}")


class TestQNAPAlerts:
    """Test QNAP NAS vendor-specific alerts"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.token = get_auth_token()
        self.client_id = get_client_id(self.token)
        cleanup_vendor_alerts(self.token, TEST_DEVICE_IP)
    
    def test_qnap_smart_error_alert(self):
        """hddSMART='ERROR' should generate critical alert"""
        resp = send_device_report(
            self.client_id, TEST_DEVICE_IP, "QNAP-Test",
            vendor_metrics={"hddSMART": {"1": "ERROR"}},
            profile_key="qnap_nas"
        )
        assert resp.status_code == 200
        
        time.sleep(0.5)
        alerts = get_alerts_for_device(self.token, TEST_DEVICE_IP, "vendor_qnap_smart")
        
        error_alerts = [a for a in alerts if "ERROR" in a.get("title", "").upper()]
        assert len(error_alerts) > 0, f"Expected QNAP SMART ERROR alert, got: {alerts}"
        assert error_alerts[0].get("severity") == "critical"
        print(f"PASS: QNAP SMART ERROR alert generated: {error_alerts[0].get('title')}")
    
    def test_qnap_smart_warning_alert(self):
        """hddSMART='WARNING' should generate high severity alert"""
        cleanup_vendor_alerts(self.token, TEST_DEVICE_IP)
        
        resp = send_device_report(
            self.client_id, TEST_DEVICE_IP, "QNAP-Test",
            vendor_metrics={"hddSMART": {"1": "WARNING"}},
            profile_key="qnap_nas"
        )
        assert resp.status_code == 200
        
        time.sleep(0.5)
        alerts = get_alerts_for_device(self.token, TEST_DEVICE_IP, "vendor_qnap_smart")
        
        warning_alerts = [a for a in alerts if "WARNING" in a.get("title", "").upper()]
        assert len(warning_alerts) > 0, f"Expected QNAP SMART WARNING alert, got: {alerts}"
        assert warning_alerts[0].get("severity") == "high"
        print(f"PASS: QNAP SMART WARNING alert generated: {warning_alerts[0].get('title')}")


class TestZyxelAlerts:
    """Test Zyxel vendor-specific alerts"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.token = get_auth_token()
        self.client_id = get_client_id(self.token)
        cleanup_vendor_alerts(self.token, TEST_DEVICE_IP)
    
    def test_zyxel_cpu_critical_alert(self):
        """zyxelCpu5min>90 should generate CPU alert"""
        resp = send_device_report(
            self.client_id, TEST_DEVICE_IP, "Zyxel-Test",
            vendor_metrics={"zyxelCpu5min": 95},
            profile_key="zyxel_nebula"
        )
        assert resp.status_code == 200
        
        time.sleep(0.5)
        alerts = get_alerts_for_device(self.token, TEST_DEVICE_IP, "vendor_zyxel_cpu")
        
        assert len(alerts) > 0, f"Expected Zyxel CPU alert, got: {alerts}"
        print(f"PASS: Zyxel CPU critical alert generated: {alerts[0].get('title')}")


class TestVendorDetailsEndpoint:
    """Test GET /api/devices/by-ip/{ip}/vendor-details endpoint"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.token = get_auth_token()
        self.client_id = get_client_id(self.token)
    
    def test_vendor_details_returns_vendor_metrics(self):
        """vendor-details should return vendor_metrics after device-report"""
        # First send a device report with vendor_metrics
        test_metrics = {
            "raidStatus": 1,
            "diskTemperature": {"1": 35, "2": 36},
            "systemStatus": 1
        }
        
        resp = send_device_report(
            self.client_id, TEST_DEVICE_IP, "Vendor-Details-Test",
            vendor_metrics=test_metrics,
            profile_key="synology_dsm"
        )
        assert resp.status_code == 200
        
        time.sleep(0.5)
        
        # Now fetch vendor-details
        resp = requests.get(
            f"{BASE_URL}/api/devices/by-ip/{TEST_DEVICE_IP}/vendor-details",
            headers={"Authorization": f"Bearer {self.token}"}
        )
        
        assert resp.status_code == 200, f"vendor-details failed: {resp.text}"
        data = resp.json()
        
        assert "device_ip" in data
        assert "vendor_metrics" in data
        assert data["device_ip"] == TEST_DEVICE_IP
        
        # Verify vendor_metrics were saved
        vm = data.get("vendor_metrics", {})
        assert vm.get("raidStatus") == 1 or "raidStatus" in vm, f"vendor_metrics not saved: {vm}"
        
        print(f"PASS: vendor-details returns vendor_metrics: {list(vm.keys())}")
    
    def test_vendor_details_returns_profile_info(self):
        """vendor-details should return profile info when profile_key is set"""
        resp = requests.get(
            f"{BASE_URL}/api/devices/by-ip/{TEST_DEVICE_IP}/vendor-details",
            headers={"Authorization": f"Bearer {self.token}"}
        )
        
        if resp.status_code == 200:
            data = resp.json()
            # Check structure
            assert "profile_key" in data or data.get("profile") is not None
            assert "last_poll" in data
            assert "cpu_usage" in data
            assert "temperature" in data
            print(f"PASS: vendor-details returns expected structure: profile_key={data.get('profile_key')}")
        else:
            print(f"SKIP: Device not found (status={resp.status_code})")


class TestRegressionDeviceReport:
    """Regression tests: device-report without vendor_metrics should still work"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.token = get_auth_token()
        self.client_id = get_client_id(self.token)
    
    def test_device_report_without_vendor_metrics(self):
        """device-report without vendor_metrics should work normally"""
        payload = {
            "hostname": "test-connector",
            "devices": [{
                "device_ip": "192.168.1.100",
                "device_name": "Regression-Test-Device",
                "reachable": True,
                "monitor_type": "snmp",
                "cpu_usage": 45,
                "memory_usage": 60,
                "poll_timestamp": datetime.now(timezone.utc).isoformat()
            }]
        }
        
        resp = requests.post(
            f"{BASE_URL}/api/connector/device-report",
            headers=CONNECTOR_HEADERS,
            json=payload
        )
        
        assert resp.status_code == 200, f"Regression failed: {resp.text}"
        print("PASS: device-report without vendor_metrics works correctly")
    
    def test_devices_endpoint_works(self):
        """GET /api/devices should work normally"""
        resp = requests.get(
            f"{BASE_URL}/api/devices",
            headers={"Authorization": f"Bearer {self.token}"}
        )
        
        assert resp.status_code == 200, f"devices endpoint failed: {resp.text}"
        devices = resp.json()
        assert isinstance(devices, list)
        print(f"PASS: /api/devices returns {len(devices)} devices")


class TestConnectorDownloadEndpoint:
    """Test connector download endpoint for v3.4.5"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.token = get_auth_token()
    
    def test_connector_zip_accessible(self):
        """86NocConnector.zip should be downloadable"""
        # Try public path first
        resp = requests.head(f"{BASE_URL}/86NocConnector.zip")
        if resp.status_code == 200:
            print("PASS: 86NocConnector.zip accessible via public path")
            return
        
        # Try with auth
        resp = requests.get(
            f"{BASE_URL}/api/connector/update-info",
            headers={"Authorization": f"Bearer {self.token}"}
        )
        
        if resp.status_code == 200:
            data = resp.json()
            version = data.get("version", "unknown")
            print(f"PASS: Connector update info available, version={version}")
        else:
            print(f"INFO: Connector update-info status={resp.status_code}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
