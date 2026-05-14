"""
Tests for device silence toggle + auto-classify endpoint + device_classifier module.

Covers iteration_63 review-request:
  - PUT /api/connector/{client_id}/managed-devices/{device_id}/silence
  - POST /api/connector/{client_id}/managed-devices/auto-classify
  - device_classifier.classify_device_type (isolated unit tests)
  - alert_filter.insert_alert_if_emit semantics
"""
import os
import sys
import asyncio
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
CLIENT_ID = "da3d6e40-b3e5-4d46-9787-dde328a3aa36"  # 86BIT_Office (demo seed)
ADMIN_EMAIL = "admin@86bit.it"
ADMIN_PASSWORD = "password"

# Make backend importable for isolated unit tests
sys.path.insert(0, "/app/backend")


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    if r.status_code != 200:
        pytest.skip(f"Admin login failed: {r.status_code} {r.text}")
    return r.json().get("access_token") or r.json().get("token")


@pytest.fixture(scope="module")
def headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def sample_device(headers):
    """Use known NETGEAR seed device id from 86BIT_Office demo client."""
    return {"id": "3f20edc0-5d79-472d-9780-17eea4b041b5", "ip": "192.168.1.3"}


# ---------- Silence endpoint tests ----------
class TestSilenceEndpoint:
    def test_silence_on(self, headers, sample_device):
        did = sample_device["id"]
        r = requests.put(
            f"{BASE_URL}/api/connector/{CLIENT_ID}/managed-devices/{did}/silence",
            headers=headers,
            json={"silenced": True, "reason": "TEST_silence_reason"},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is True
        assert data.get("alerts_silenced") is True
        assert data.get("device_id") == did

    def test_silence_off_clears_reason(self, headers, sample_device):
        did = sample_device["id"]
        r = requests.put(
            f"{BASE_URL}/api/connector/{CLIENT_ID}/managed-devices/{did}/silence",
            headers=headers,
            json={"silenced": False},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("alerts_silenced") is False

    def test_silence_404_unknown_device(self, headers):
        r = requests.put(
            f"{BASE_URL}/api/connector/{CLIENT_ID}/managed-devices/does-not-exist-xyz/silence",
            headers=headers,
            json={"silenced": True},
            timeout=15,
        )
        assert r.status_code == 404, r.text


# ---------- Auto-classify endpoint ----------
class TestAutoClassifyEndpoint:
    def test_auto_classify_returns_changed_shape(self, headers):
        r = requests.post(
            f"{BASE_URL}/api/connector/{CLIENT_ID}/managed-devices/auto-classify",
            headers=headers,
            timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is True
        assert "changed_count" in data
        assert "changed" in data
        assert isinstance(data["changed"], list)
        assert data["changed_count"] == len(data["changed"])
        for item in data["changed"]:
            assert {"id", "name", "ip", "old_type", "new_type"}.issubset(item.keys())


# ---------- device_classifier module unit tests ----------
class TestDeviceClassifier:
    def test_printer_sys_object_id_hp(self):
        from device_classifier import classify_device_type

        t = classify_device_type(sys_object_id="1.3.6.1.4.1.11.2.3.9.1")
        assert t == "printer"

    def test_printer_hostname_brother(self):
        from device_classifier import classify_device_type

        t = classify_device_type(hostname="Brother MFC-L6710DW")
        assert t == "printer"

    def test_printer_sys_descr_hp_laserjet(self):
        from device_classifier import classify_device_type

        t = classify_device_type(sys_descr="HP OfficeJet Pro 9010")
        assert t == "printer"

    def test_switch_cisco_catalyst(self):
        from device_classifier import classify_device_type

        t = classify_device_type(hostname="Cisco Catalyst 2960")
        assert t == "switch"

    def test_switch_netgear_gs(self):
        from device_classifier import classify_device_type

        t = classify_device_type(hostname="NETGEAR GS110EMX")
        assert t == "switch"

    def test_none_for_unknown(self):
        from device_classifier import classify_device_type

        t = classify_device_type(hostname="random-host-xyz", sys_descr="Linux 5.10")
        assert t is None

    def test_switch_beats_printer_on_procurve(self):
        """HP ProCurve switches may match 'M...' pattern but must NOT be classified as printer."""
        from device_classifier import classify_device_type

        t = classify_device_type(hostname="HP ProCurve 2530-24G Switch")
        assert t == "switch"


# ---------- alert_filter.insert_alert_if_emit semantics ----------
class TestAlertFilter:
    def test_insert_alert_if_emit_no_device_ip_always_inserts(self):
        """Alerts without device_ip (connector_watchdog etc) must always insert."""
        from alert_filter import insert_alert_if_emit

        calls = []

        class FakeCollection:
            async def insert_one(self, doc):
                calls.append(doc)
                return type("R", (), {"inserted_id": "x"})()

            async def find_one(self, *a, **kw):
                return None

        class FakeDB:
            alerts = FakeCollection()
            managed_devices = FakeCollection()

        async def run():
            ok = await insert_alert_if_emit(
                FakeDB(), {"client_id": "c1", "title": "connector_watchdog down"}
            )
            return ok

        ok = asyncio.get_event_loop().run_until_complete(run())
        assert ok is True
        assert len(calls) == 1

    def test_insert_alert_if_emit_skips_when_silenced(self):
        from alert_filter import insert_alert_if_emit, invalidate_silence_cache

        invalidate_silence_cache()
        inserted = []

        class AlertsColl:
            async def insert_one(self, doc):
                inserted.append(doc)

        class MDColl:
            async def find_one(self, q, *a, **kw):
                # Simulate silenced device match
                if q.get("alerts_silenced") is True and q.get("ip") == "10.0.0.1":
                    return {"id": "dev1"}
                return None

        class FakeDB:
            alerts = AlertsColl()
            managed_devices = MDColl()

        async def run():
            return await insert_alert_if_emit(
                FakeDB(), {"client_id": "c1", "device_ip": "10.0.0.1", "title": "t"}
            )

        ok = asyncio.get_event_loop().run_until_complete(run())
        assert ok is False
        assert inserted == []

    def test_insert_alert_if_emit_inserts_when_not_silenced(self):
        from alert_filter import insert_alert_if_emit, invalidate_silence_cache

        invalidate_silence_cache()
        inserted = []

        class AlertsColl:
            async def insert_one(self, doc):
                inserted.append(doc)

        class MDColl:
            async def find_one(self, *a, **kw):
                return None

        class FakeDB:
            alerts = AlertsColl()
            managed_devices = MDColl()

        async def run():
            return await insert_alert_if_emit(
                FakeDB(), {"client_id": "c1", "ip": "10.0.0.2", "title": "t"}
            )

        ok = asyncio.get_event_loop().run_until_complete(run())
        assert ok is True
        assert len(inserted) == 1


# ---------- Import smoke test for all alert emitters ----------
@pytest.mark.skip(reason="Module imports require MONGO_URL env; backend process already validates this at startup")
def test_all_alert_emitters_import_filter():
    """Ensures every migrated module can import alert_filter successfully."""
    mods = [
        "connector_watchdog",
        "redfish",
        "routes.alerts",
        "routes.backup",
        "routes.external_monitor",
        "routes.ingestion",
        "routes.printers",
        "routes.connector",
    ]
    import importlib

    failed = []
    for m in mods:
        try:
            importlib.import_module(m)
        except Exception as e:
            failed.append((m, str(e)))
    assert not failed, f"Import failures: {failed}"
