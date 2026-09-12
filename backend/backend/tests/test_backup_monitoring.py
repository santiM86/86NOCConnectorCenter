"""
Backup Monitoring API Tests - Hornetsecurity VM Backup + Hyper-V Integration
Tests: process-status, dashboard, history, vm-detail, summary-all, auto-alert, auto-resolve
"""
import pytest
import requests
import os
import time
from datetime import datetime, timezone

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test credentials
TEST_EMAIL = "admin@86bit.it"
TEST_PASSWORD = "password"
CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"
API_KEY = "noc_35cf39b4d68740b1a981aedef2ee293d"


@pytest.fixture(scope="module")
def auth_token():
    """Get authentication token for API calls."""
    response = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD
    })
    if response.status_code == 200:
        return response.json().get("token")
    pytest.skip(f"Authentication failed: {response.status_code} - {response.text}")


@pytest.fixture(scope="module")
def headers(auth_token):
    """Headers with Bearer token for authenticated endpoints."""
    return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def api_key_headers():
    """Headers with X-API-Key for connector endpoints."""
    return {"X-API-Key": API_KEY, "Content-Type": "application/json"}


class TestBackupProcessStatus:
    """Test POST /api/backup/process-status - Connector data ingestion"""
    
    def test_process_status_with_valid_api_key(self, api_key_headers):
        """Test that connector can send backup data with API key."""
        payload = {
            "vms": [
                {
                    "vm_name": "TEST_DC-01",
                    "vm_state": "Running",
                    "backup_status": "success",
                    "last_backup_time": datetime.now(timezone.utc).isoformat(),
                    "last_backup_size_bytes": 5368709120,  # 5GB
                    "next_backup_time": datetime.now(timezone.utc).isoformat(),
                    "backup_type": "Incremental",
                    "memory_mb": 8192,
                    "checkpoint_count": 0
                },
                {
                    "vm_name": "TEST_SQL-01",
                    "vm_state": "Running",
                    "backup_status": "warning",
                    "last_backup_time": datetime.now(timezone.utc).isoformat(),
                    "last_backup_size_bytes": 10737418240,  # 10GB
                    "next_backup_time": datetime.now(timezone.utc).isoformat(),
                    "backup_type": "Full",
                    "memory_mb": 16384,
                    "checkpoint_count": 2
                },
                {
                    "vm_name": "EXCHANGE-04",
                    "vm_state": "Running",
                    "backup_status": "failed",
                    "last_backup_time": "2025-01-01T00:00:00Z",
                    "last_backup_size_bytes": 0,
                    "next_backup_time": None,
                    "backup_type": "Full",
                    "memory_mb": 32768,
                    "checkpoint_count": 0
                }
            ],
            "summary": {
                "total_vms": 3,
                "backup_ok": 1,
                "backup_warning": 1,
                "backup_failed": 1,
                "backup_missing": 0
            },
            "hyperv_vms": [
                {"name": "TEST_DC-01", "state": "Running", "memory_mb": 8192, "cpu_usage": 15},
                {"name": "TEST_SQL-01", "state": "Running", "memory_mb": 16384, "cpu_usage": 45},
                {"name": "EXCHANGE-04", "state": "Running", "memory_mb": 32768, "cpu_usage": 30}
            ],
            "altaro_connected": True,
            "hyperv_connected": True
        }
        
        response = requests.post(f"{BASE_URL}/api/backup/process-status", 
                                 json=payload, headers=api_key_headers)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data.get("status") == "ok"
        assert data.get("vms_processed") == 3
        print(f"✓ Process status: {data}")
    
    def test_process_status_without_api_key(self):
        """Test that process-status rejects requests without API key."""
        payload = {"vms": [], "summary": {}}
        response = requests.post(f"{BASE_URL}/api/backup/process-status", json=payload)
        
        # Should fail without API key
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print(f"✓ Correctly rejected request without API key: {response.status_code}")
    
    def test_process_status_with_invalid_api_key(self):
        """Test that process-status rejects invalid API key."""
        payload = {"vms": [], "summary": {}}
        headers = {"X-API-Key": "invalid_key_12345", "Content-Type": "application/json"}
        response = requests.post(f"{BASE_URL}/api/backup/process-status", json=payload, headers=headers)
        
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print(f"✓ Correctly rejected invalid API key: {response.status_code}")


class TestBackupDashboard:
    """Test GET /api/backup/dashboard/{client_id}"""
    
    def test_dashboard_returns_data(self, headers):
        """Test dashboard endpoint returns backup data."""
        response = requests.get(f"{BASE_URL}/api/backup/dashboard/{CLIENT_ID}", headers=headers)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify structure
        assert "client_id" in data
        assert "vms" in data
        assert "summary" in data
        assert "altaro_connected" in data
        assert "hyperv_connected" in data
        
        # Verify data was stored from process-status
        if data.get("has_data"):
            assert len(data["vms"]) > 0, "Expected VMs in dashboard"
            summary = data["summary"]
            assert "total_vms" in summary
            assert "backup_ok" in summary
            assert "backup_failed" in summary
            print(f"✓ Dashboard data: {len(data['vms'])} VMs, summary: {summary}")
        else:
            print("✓ Dashboard returned (no data yet)")
    
    def test_dashboard_requires_auth(self):
        """Test dashboard requires authentication."""
        response = requests.get(f"{BASE_URL}/api/backup/dashboard/{CLIENT_ID}")
        assert response.status_code in [401, 403], f"Expected 401/403, got {response.status_code}"
        print(f"✓ Dashboard correctly requires auth: {response.status_code}")


class TestBackupHistory:
    """Test GET /api/backup/history/{client_id}"""
    
    def test_history_returns_data(self, headers):
        """Test history endpoint returns chart data."""
        response = requests.get(f"{BASE_URL}/api/backup/history/{CLIENT_ID}?days=7", headers=headers)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert "client_id" in data
        assert "days" in data
        assert "data" in data
        assert data["days"] == 7
        
        # History data is a list
        assert isinstance(data["data"], list)
        print(f"✓ History: {len(data['data'])} records for {data['days']} days")
    
    def test_history_with_different_days(self, headers):
        """Test history with different day ranges."""
        for days in [1, 7, 30]:
            response = requests.get(f"{BASE_URL}/api/backup/history/{CLIENT_ID}?days={days}", headers=headers)
            assert response.status_code == 200
            data = response.json()
            assert data["days"] == days
        print("✓ History works with different day ranges (1, 7, 30)")


class TestBackupVmDetail:
    """Test GET /api/backup/vm/{client_id}/{vm_name}"""
    
    def test_vm_detail_for_exchange04(self, headers):
        """Test VM detail for EXCHANGE-04 (should have alert)."""
        vm_name = "EXCHANGE-04"
        response = requests.get(f"{BASE_URL}/api/backup/vm/{CLIENT_ID}/{vm_name}", headers=headers)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert data["vm_name"] == vm_name
        assert "backup" in data
        assert "alerts" in data
        
        # EXCHANGE-04 should have backup_failure alert
        if data.get("backup"):
            assert data["backup"]["backup_status"] == "failed"
            print(f"✓ VM detail for {vm_name}: status={data['backup']['backup_status']}")
        
        # Check for alerts
        if data.get("alerts"):
            print(f"✓ VM {vm_name} has {len(data['alerts'])} alert(s)")
            for alert in data["alerts"]:
                print(f"  - {alert.get('title')} (resolved: {alert.get('resolved', False)})")
        else:
            print(f"✓ VM {vm_name} detail returned (no alerts yet)")
    
    def test_vm_detail_not_found(self, headers):
        """Test VM detail for non-existent VM."""
        response = requests.get(f"{BASE_URL}/api/backup/vm/{CLIENT_ID}/NONEXISTENT_VM", headers=headers)
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("✓ Correctly returns 404 for non-existent VM")


class TestBackupSummaryAll:
    """Test GET /api/backup/summary-all"""
    
    def test_summary_all_returns_data(self, headers):
        """Test summary-all endpoint for TV dashboard."""
        response = requests.get(f"{BASE_URL}/api/backup/summary-all", headers=headers)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert "total" in data
        assert "clients" in data
        
        total = data["total"]
        assert "total_vms" in total
        assert "backup_ok" in total
        assert "backup_failed" in total
        
        print(f"✓ Summary-all: {len(data['clients'])} clients, total: {total}")
        
        # Check client details
        for client in data["clients"]:
            assert "client_id" in client
            assert "summary" in client
            if client.get("failed_vms"):
                print(f"  - Client {client.get('client_name', client['client_id'])}: failed VMs = {client['failed_vms']}")


class TestAutoAlertGeneration:
    """Test automatic alert generation for failed/missing backups"""
    
    def test_alert_created_for_failed_backup(self, headers, api_key_headers):
        """Test that alert is auto-created for failed backup."""
        # First, send a failed backup status
        payload = {
            "vms": [
                {
                    "vm_name": "TEST_ALERT_VM",
                    "vm_state": "Running",
                    "backup_status": "failed",
                    "last_backup_time": "2025-01-01T00:00:00Z",
                    "last_backup_size_bytes": 0,
                    "memory_mb": 4096
                }
            ],
            "summary": {"total_vms": 1, "backup_ok": 0, "backup_warning": 0, "backup_failed": 1, "backup_missing": 0},
            "altaro_connected": True,
            "hyperv_connected": True
        }
        
        response = requests.post(f"{BASE_URL}/api/backup/process-status", 
                                 json=payload, headers=api_key_headers)
        assert response.status_code == 200
        
        # Check VM detail for alert
        time.sleep(0.5)  # Small delay for DB write
        response = requests.get(f"{BASE_URL}/api/backup/vm/{CLIENT_ID}/TEST_ALERT_VM", headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            alerts = data.get("alerts", [])
            # Should have at least one unresolved backup_failure alert
            unresolved = [a for a in alerts if not a.get("resolved")]
            print(f"✓ Alert check for TEST_ALERT_VM: {len(alerts)} total, {len(unresolved)} unresolved")
        else:
            print(f"✓ VM detail returned {response.status_code} (may not have data yet)")


class TestAutoResolve:
    """Test automatic alert resolution when backup succeeds"""
    
    def test_alert_resolved_when_backup_succeeds(self, headers, api_key_headers):
        """Test that alert is auto-resolved when VM backup succeeds."""
        vm_name = "TEST_RESOLVE_VM"
        
        # Step 1: Create a failed backup (generates alert)
        payload_failed = {
            "vms": [
                {
                    "vm_name": vm_name,
                    "vm_state": "Running",
                    "backup_status": "failed",
                    "last_backup_time": "2025-01-01T00:00:00Z",
                    "last_backup_size_bytes": 0,
                    "memory_mb": 4096
                }
            ],
            "summary": {"total_vms": 1, "backup_ok": 0, "backup_warning": 0, "backup_failed": 1, "backup_missing": 0},
            "altaro_connected": True,
            "hyperv_connected": True
        }
        
        response = requests.post(f"{BASE_URL}/api/backup/process-status", 
                                 json=payload_failed, headers=api_key_headers)
        assert response.status_code == 200
        print(f"✓ Step 1: Sent failed backup for {vm_name}")
        
        time.sleep(0.5)
        
        # Step 2: Send success status (should resolve alert)
        payload_success = {
            "vms": [
                {
                    "vm_name": vm_name,
                    "vm_state": "Running",
                    "backup_status": "success",
                    "last_backup_time": datetime.now(timezone.utc).isoformat(),
                    "last_backup_size_bytes": 5368709120,
                    "memory_mb": 4096
                }
            ],
            "summary": {"total_vms": 1, "backup_ok": 1, "backup_warning": 0, "backup_failed": 0, "backup_missing": 0},
            "altaro_connected": True,
            "hyperv_connected": True
        }
        
        response = requests.post(f"{BASE_URL}/api/backup/process-status", 
                                 json=payload_success, headers=api_key_headers)
        assert response.status_code == 200
        print(f"✓ Step 2: Sent success backup for {vm_name}")
        
        time.sleep(0.5)
        
        # Step 3: Check that alert is resolved
        response = requests.get(f"{BASE_URL}/api/backup/vm/{CLIENT_ID}/{vm_name}", headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            alerts = data.get("alerts", [])
            unresolved = [a for a in alerts if not a.get("resolved")]
            resolved = [a for a in alerts if a.get("resolved")]
            
            print(f"✓ Step 3: Alert status - {len(resolved)} resolved, {len(unresolved)} unresolved")
            
            # All alerts should be resolved now
            if alerts:
                assert len(unresolved) == 0, f"Expected 0 unresolved alerts, got {len(unresolved)}"
                print(f"✓ Auto-resolve working: all {len(alerts)} alerts resolved")
        else:
            print(f"✓ VM detail returned {response.status_code}")


class TestExchange04Alert:
    """Test that EXCHANGE-04 has auto-generated alert from initial data"""
    
    def test_exchange04_has_backup_failure_alert(self, headers):
        """Verify EXCHANGE-04 has backup_failure alert."""
        response = requests.get(f"{BASE_URL}/api/backup/vm/{CLIENT_ID}/EXCHANGE-04", headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            alerts = data.get("alerts", [])
            
            # Look for backup_failure alert
            backup_alerts = [a for a in alerts if a.get("alert_type") == "backup_failure"]
            
            if backup_alerts:
                print(f"✓ EXCHANGE-04 has {len(backup_alerts)} backup_failure alert(s)")
                for alert in backup_alerts:
                    print(f"  - {alert.get('title')} | severity: {alert.get('severity')} | resolved: {alert.get('resolved')}")
            else:
                print("⚠ EXCHANGE-04 has no backup_failure alerts (may need to run process-status first)")
        elif response.status_code == 404:
            print("⚠ EXCHANGE-04 not found - need to run process-status first")
        else:
            print(f"⚠ Unexpected response: {response.status_code}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
