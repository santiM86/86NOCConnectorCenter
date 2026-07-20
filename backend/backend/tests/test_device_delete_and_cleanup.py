"""Test backend per DELETE device multi-source + cleanup-stale + sync-active (iteration_67)."""
import os
import uuid
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"
ADMIN_EMAIL = "admin@86bit.it"
ADMIN_PASSWORD = "password"


@pytest.fixture(scope="module")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------- Delete - manual device ----------
class TestDeleteManualDevice:
    def test_create_and_delete_manual_device(self, headers):
        # Create device via POST /api/devices
        test_ip = f"10.99.99.{int(time.time()) % 250 + 1}"
        payload = {
            "client_id": CLIENT_ID,
            "name": f"TEST_delete_{uuid.uuid4().hex[:6]}",
            "device_type": "server",
            "ip_address": test_ip,
        }
        r = requests.post(f"{BASE_URL}/api/devices", json=payload, headers=headers, timeout=15)
        assert r.status_code == 200, f"Create failed: {r.status_code} {r.text}"
        dev = r.json()
        device_id = dev["id"]
        assert dev["ip_address"] == test_ip

        # Delete
        r = requests.delete(
            f"{BASE_URL}/api/connector/{CLIENT_ID}/managed-devices/{device_id}",
            headers=headers, timeout=15,
        )
        assert r.status_code == 200, f"Delete failed: {r.status_code} {r.text}"
        body = r.json()
        assert body.get("status") == "ok"
        assert body.get("total", 0) >= 1
        assert "deletes" in body
        # devices collection must be 1 (since manual)
        assert body["deletes"].get("devices", 0) >= 1

        # Verify not present anymore
        r = requests.get(f"{BASE_URL}/api/devices?client_id={CLIENT_ID}", headers=headers, timeout=15)
        assert r.status_code == 200
        ips = [d.get("ip_address") for d in r.json()]
        assert test_ip not in ips, f"Device {test_ip} still present after delete"


# ---------- Delete - fake id ----------
class TestDeleteFakeId:
    def test_delete_fake_id_returns_404(self, headers):
        fake_id = f"nonexistent-{uuid.uuid4()}"
        r = requests.delete(
            f"{BASE_URL}/api/connector/{CLIENT_ID}/managed-devices/{fake_id}",
            headers=headers, timeout=15,
        )
        assert r.status_code == 404
        detail = r.json().get("detail", "")
        assert "non trovato" in detail.lower() or "not found" in detail.lower()


# ---------- Delete - poll_<ip> synthetic id ----------
class TestDeletePollSyntheticId:
    def test_delete_poll_synthetic_returns_404_if_not_present(self, headers):
        # This one should respond 404 if no such ip exists (safe path) OR 200 if it
        # can resolve. Either is acceptable — we just want no 500.
        synth = "poll_10_88_88_88"  # unlikely to exist
        r = requests.delete(
            f"{BASE_URL}/api/connector/{CLIENT_ID}/managed-devices/{synth}",
            headers=headers, timeout=15,
        )
        assert r.status_code in (200, 404), f"Unexpected: {r.status_code} {r.text}"


# ---------- Delete - alerts resolution ----------
class TestDeleteResolvesAlerts:
    def test_delete_resolves_open_alerts(self, headers):
        # Create manual device
        test_ip = f"10.99.77.{int(time.time()) % 250 + 1}"
        payload = {
            "client_id": CLIENT_ID,
            "name": f"TEST_alert_{uuid.uuid4().hex[:6]}",
            "device_type": "server",
            "ip_address": test_ip,
        }
        r = requests.post(f"{BASE_URL}/api/devices", json=payload, headers=headers, timeout=15)
        assert r.status_code == 200
        device_id = r.json()["id"]

        # We can't easily inject a fake alert without DB access, so we just call DELETE
        # and verify the endpoint path for alert resolution doesn't crash.
        r = requests.delete(
            f"{BASE_URL}/api/connector/{CLIENT_ID}/managed-devices/{device_id}",
            headers=headers, timeout=15,
        )
        assert r.status_code == 200
        body = r.json()
        assert body.get("status") == "ok"


# ---------- Cleanup stale - connector offline (demo) ----------
class TestCleanupStaleDevices:
    def test_cleanup_stale_dry_run(self, headers):
        r = requests.post(
            f"{BASE_URL}/api/connector/{CLIENT_ID}/cleanup-stale-devices",
            json={"dry_run": True}, headers=headers, timeout=15,
        )
        # Possible outcomes:
        # - 404: connector not registered (demo env)
        # - 200 with {ok:False, reason:'connector_offline'}
        # - 200 with {ok:True, dry_run:True, candidates:[...]}
        assert r.status_code in (200, 404), f"Unexpected: {r.status_code} {r.text}"
        if r.status_code == 200:
            body = r.json()
            # must have either 'ok' key or 'reason'
            assert "ok" in body
            if body["ok"] is False:
                assert body.get("reason") == "connector_offline"
            else:
                assert body.get("dry_run") is True
                assert "candidates" in body
                assert isinstance(body["candidates"], list)
        else:
            detail = r.json().get("detail", "")
            assert "connector" in detail.lower() or "non registrato" in detail.lower()

    def test_cleanup_stale_fake_client(self, headers):
        fake_client = "fake-client-id-" + uuid.uuid4().hex[:8]
        r = requests.post(
            f"{BASE_URL}/api/connector/{fake_client}/cleanup-stale-devices",
            json={"dry_run": True}, headers=headers, timeout=15,
        )
        assert r.status_code == 404


# ---------- Sync active devices ----------
class TestSyncActiveDevices:
    def test_sync_active_dry_run(self, headers):
        # Dry run with empty active list: would_remove should list all connector devices
        r = requests.post(
            f"{BASE_URL}/api/connector/{CLIENT_ID}/sync-active-devices",
            json={"active_ips": ["192.168.1.1"], "dry_run": True},
            headers=headers, timeout=15,
        )
        assert r.status_code == 200, f"Unexpected: {r.status_code} {r.text}"
        body = r.json()
        assert body.get("ok") is True
        assert body.get("dry_run") is True
        assert "would_remove_count" in body
        assert "would_remove" in body
        assert isinstance(body["would_remove"], list)

    def test_sync_active_invalid_payload(self, headers):
        r = requests.post(
            f"{BASE_URL}/api/connector/{CLIENT_ID}/sync-active-devices",
            json={"active_ips": "not-a-list"},
            headers=headers, timeout=15,
        )
        assert r.status_code == 400


# ---------- Auth required ----------
class TestAuthRequired:
    def test_delete_requires_auth(self):
        r = requests.delete(
            f"{BASE_URL}/api/connector/{CLIENT_ID}/managed-devices/anything",
            timeout=15,
        )
        assert r.status_code in (401, 403)

    def test_cleanup_requires_auth(self):
        r = requests.post(
            f"{BASE_URL}/api/connector/{CLIENT_ID}/cleanup-stale-devices",
            json={}, timeout=15,
        )
        assert r.status_code in (401, 403)
