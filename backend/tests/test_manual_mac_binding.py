"""
Test suite v3.6.16 - Manual MAC Binding.

Endpoints under test:
  POST   /api/topology/mac-bindings
  GET    /api/topology/mac-bindings (?client_id=)
  DELETE /api/topology/mac-bindings/{mac}
  GET    /api/devices/{ip}/switch-ports  (priorita' manual + nuovi campi top-level)

Coverage:
  - create / update / validation errors (mac, ip, name)
  - also_create_managed_device crea un record in db.devices con created_via=manual_mac_binding
  - listing con/senza client_id
  - delete + cleanup di discovered_endpoints (manual_binding_* via $unset)
  - GET switch-ports: priorita' mac_manual sotto LLDP e sopra mac_managed/oui/unknown
  - GET switch-ports top-level: device_name + client_id
  - Regressione: mac_managed/oui/unknown intatti se nessun binding presente
"""

import os
import sys
import uuid
import pytest
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

BACKEND_DIR = "/app/backend"
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from pymongo import MongoClient  # noqa: E402

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"

ADMIN_EMAIL = "admin@86bit.it"
ADMIN_PASSWORD = "password"

# Test data identifiers
CLIENT_ID = f"TEST_mac_binding_{uuid.uuid4().hex[:8]}"
SWITCH_IP = "10.250.97.11"
SWITCH_NAME = "TEST_MMB_Switch"

# MAC addresses for different scenarios
MAC_TO_BIND = "AA:BB:CC:DD:EE:FF"     # binding manuale
MAC_LLDP_ALSO_BOUND = "11:22:33:44:55:66"  # ha LLDP + binding -> LLDP vince
MAC_REGRESSION_OUI = "28:CF:E9:00:11:22"  # Apple OUI, nessun binding -> mac_oui
MAC_REGRESSION_UNKNOWN = "F2:F2:F2:AA:BB:CC"  # OUI sconosciuto -> mac_unknown
MAC_MANAGED_REGRESSION = "00:11:32:DE:AD:01"  # NAS managed, no binding -> mac_managed

BOUND_IP = "10.250.97.50"
BOUND_NAME = "TEST_MMB_Bound_Device"
NAS_IP = "10.250.97.60"

ENDPOOINT_MACS = [
    MAC_TO_BIND, MAC_LLDP_ALSO_BOUND, MAC_REGRESSION_OUI,
    MAC_REGRESSION_UNKNOWN, MAC_MANAGED_REGRESSION,
]


# ---------------- Fixtures ----------------

@pytest.fixture(scope="module")
def mongo_db():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=10,
    )
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module", autouse=True)
def seed_data(mongo_db):
    """Seed managed_devices + switch_ports + discovered_endpoints + lldp neighbor."""
    now = datetime.now(timezone.utc).isoformat()

    # managed_devices: switch + NAS managed
    mongo_db.managed_devices.delete_many({"client_id": CLIENT_ID})
    mongo_db.managed_devices.insert_many([
        {
            "id": str(uuid.uuid4()), "client_id": CLIENT_ID,
            "ip": SWITCH_IP, "device_name": SWITCH_NAME,
            "device_type": "switch", "vendor": "HPE", "monitor_type": "snmp",
        },
        {
            "id": str(uuid.uuid4()), "client_id": CLIENT_ID,
            "ip": NAS_IP, "device_name": "TEST_MMB_NAS",
            "device_type": "nas", "vendor": "Synology", "monitor_type": "snmp",
        },
    ])

    # switch_ports: 5 porte (idx 10..14)
    mongo_db.switch_ports.delete_many({"local_ip": SWITCH_IP})
    mongo_db.switch_ports.insert_many([
        {"local_ip": SWITCH_IP, "idx": 10, "name": "Gi1/0/10", "alias": "TEST_manual",
         "oper": 1, "admin": 1, "speed_mbps": 1000, "updated_at": now},
        {"local_ip": SWITCH_IP, "idx": 11, "name": "Gi1/0/11", "alias": "TEST_lldp_plus_manual",
         "oper": 1, "admin": 1, "speed_mbps": 1000, "updated_at": now},
        {"local_ip": SWITCH_IP, "idx": 12, "name": "Gi1/0/12", "alias": "TEST_oui",
         "oper": 1, "admin": 1, "speed_mbps": 1000, "updated_at": now},
        {"local_ip": SWITCH_IP, "idx": 13, "name": "Gi1/0/13", "alias": "TEST_unknown",
         "oper": 1, "admin": 1, "speed_mbps": 1000, "updated_at": now},
        {"local_ip": SWITCH_IP, "idx": 14, "name": "Gi1/0/14", "alias": "TEST_mac_managed",
         "oper": 1, "admin": 1, "speed_mbps": 1000, "updated_at": now},
    ])

    # discovered_endpoints (1 MAC per porta)
    mongo_db.discovered_endpoints.delete_many({"switch_ip": SWITCH_IP})
    mongo_db.discovered_endpoints.insert_many([
        {"client_id": CLIENT_ID, "switch_ip": SWITCH_IP, "port": 10,
         "mac": MAC_TO_BIND, "ip": "", "is_managed": False, "hostname": ""},
        {"client_id": CLIENT_ID, "switch_ip": SWITCH_IP, "port": 11,
         "mac": MAC_LLDP_ALSO_BOUND, "ip": "", "is_managed": False, "hostname": ""},
        {"client_id": CLIENT_ID, "switch_ip": SWITCH_IP, "port": 12,
         "mac": MAC_REGRESSION_OUI, "ip": "", "is_managed": False, "hostname": ""},
        {"client_id": CLIENT_ID, "switch_ip": SWITCH_IP, "port": 13,
         "mac": MAC_REGRESSION_UNKNOWN, "ip": "", "is_managed": False, "hostname": ""},
        {"client_id": CLIENT_ID, "switch_ip": SWITCH_IP, "port": 14,
         "mac": MAC_MANAGED_REGRESSION, "ip": NAS_IP, "is_managed": True,
         "hostname": "TEST_MMB_NAS"},
    ])

    # lldp_neighbors: solo porta 11 (per testare priorita' LLDP vs manual)
    mongo_db.lldp_neighbors.delete_many({"local_ip": SWITCH_IP})
    mongo_db.lldp_neighbors.insert_one({
        "client_id": CLIENT_ID,
        "local_ip": SWITCH_IP,
        "local_port_id": "Gi1/0/11",
        "local_port_desc": "Gi1/0/11",
        "remote_sys_name": "TEST_MMB_LLDP_Peer",
        "remote_ip": "10.250.97.99",
        "remote_port_id": "Gi0/2",
        "remote_port_desc": "Uplink",
        "remote_chassis_id": "AA:11:22:33:44:55",
        "remote_sys_cap": 4,
        "remote_sys_desc": "LLDP via SNMP",
    })

    # cleanup pre-existing bindings
    mongo_db.mac_device_bindings.delete_many({"mac": {"$in": ENDPOOINT_MACS}})
    mongo_db.devices.delete_many({"client_id": CLIENT_ID})

    yield

    # Teardown
    mongo_db.managed_devices.delete_many({"client_id": CLIENT_ID})
    mongo_db.switch_ports.delete_many({"local_ip": SWITCH_IP})
    mongo_db.discovered_endpoints.delete_many({"switch_ip": SWITCH_IP})
    mongo_db.lldp_neighbors.delete_many({"local_ip": SWITCH_IP})
    mongo_db.mac_device_bindings.delete_many({"mac": {"$in": ENDPOOINT_MACS}})
    mongo_db.devices.delete_many({"client_id": CLIENT_ID})


# ---------------- TESTS ----------------

class TestMacBindingCreateValidation:
    """POST /api/topology/mac-bindings - input validation."""

    def test_post_missing_name(self, admin_headers):
        r = requests.post(
            f"{BASE_URL}/api/topology/mac-bindings",
            headers=admin_headers,
            json={"mac": MAC_TO_BIND, "ip": BOUND_IP},
            timeout=10,
        )
        assert r.status_code == 400, f"Expected 400, got {r.status_code} {r.text}"
        assert "obbligatori" in r.text.lower() or "mac" in r.text.lower()

    def test_post_missing_ip(self, admin_headers):
        r = requests.post(
            f"{BASE_URL}/api/topology/mac-bindings",
            headers=admin_headers,
            json={"mac": MAC_TO_BIND, "name": "X"},
            timeout=10,
        )
        assert r.status_code == 400
        assert "obbligatori" in r.text.lower() or "ip" in r.text.lower()

    def test_post_invalid_mac(self, admin_headers):
        r = requests.post(
            f"{BASE_URL}/api/topology/mac-bindings",
            headers=admin_headers,
            json={"mac": "AABBCC", "ip": BOUND_IP, "name": "X"},
            timeout=10,
        )
        assert r.status_code == 400
        assert "mac" in r.text.lower()

    def test_post_invalid_ip(self, admin_headers):
        r = requests.post(
            f"{BASE_URL}/api/topology/mac-bindings",
            headers=admin_headers,
            json={"mac": "AA:BB:CC:DD:EE:01", "ip": "999.999.0.0", "name": "X"},
            timeout=10,
        )
        assert r.status_code == 400
        assert "ip" in r.text.lower()


class TestMacBindingCreateAndUpdate:
    """POST /api/topology/mac-bindings - create / update / also_create_managed_device."""

    def test_create_with_also_create_managed_device(self, admin_headers, mongo_db):
        payload = {
            "mac": MAC_TO_BIND,
            "ip": BOUND_IP,
            "name": BOUND_NAME,
            "device_type": "printer",
            "client_id": CLIENT_ID,
            "also_create_managed_device": True,
        }
        r = requests.post(
            f"{BASE_URL}/api/topology/mac-bindings",
            headers=admin_headers, json=payload, timeout=10,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["action"] == "created"
        assert body["mac"] == MAC_TO_BIND
        assert body["device_id"], "device_id should be present (also_create=true)"
        assert body["binding"]["ip"] == BOUND_IP
        assert body["binding"]["name"] == BOUND_NAME
        assert body["binding"]["device_type"] == "printer"

        # Verify db.mac_device_bindings persistence (single doc, no _id leak)
        bindings = list(mongo_db.mac_device_bindings.find({"mac": MAC_TO_BIND}))
        assert len(bindings) == 1, f"Expected 1 binding, found {len(bindings)}"
        assert bindings[0]["ip"] == BOUND_IP
        assert bindings[0]["created_by"] == ADMIN_EMAIL

        # Verify db.devices created
        dev = mongo_db.devices.find_one({"id": body["device_id"]})
        assert dev is not None, "Managed device not created"
        assert dev["created_via"] == "manual_mac_binding"
        assert dev["bound_mac"] == MAC_TO_BIND
        assert dev["ip_address"] == BOUND_IP
        assert dev["client_id"] == CLIENT_ID

        # Verify discovered_endpoints updated
        ep = mongo_db.discovered_endpoints.find_one(
            {"switch_ip": SWITCH_IP, "mac": MAC_TO_BIND}
        )
        assert ep is not None
        assert ep.get("manual_binding_ip") == BOUND_IP
        assert ep.get("manual_binding_name") == BOUND_NAME
        assert ep.get("manual_binding_type") == "printer"

    def test_update_same_mac_no_duplicate(self, admin_headers, mongo_db):
        # Re-POST same MAC con name diverso -> action=updated, NO duplicate
        new_name = "TEST_MMB_Bound_Device_RENAMED"
        payload = {
            "mac": MAC_TO_BIND,
            "ip": BOUND_IP,
            "name": new_name,
            "device_type": "printer",
            "client_id": CLIENT_ID,
            "also_create_managed_device": False,
        }
        r = requests.post(
            f"{BASE_URL}/api/topology/mac-bindings",
            headers=admin_headers, json=payload, timeout=10,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["action"] == "updated", f"Expected updated, got {body}"

        bindings = list(mongo_db.mac_device_bindings.find({"mac": MAC_TO_BIND}))
        assert len(bindings) == 1, f"Duplicate detected: {len(bindings)}"
        assert bindings[0]["name"] == new_name

        # discovered_endpoints riallineato
        ep = mongo_db.discovered_endpoints.find_one(
            {"switch_ip": SWITCH_IP, "mac": MAC_TO_BIND}
        )
        assert ep.get("manual_binding_name") == new_name

    def test_post_lowercase_mac_normalized_to_upper(self, admin_headers, mongo_db):
        """Verifica normalizzazione MAC (lowercase -> uppercase)."""
        lower_mac = "aa:bb:cc:dd:ee:01"
        r = requests.post(
            f"{BASE_URL}/api/topology/mac-bindings",
            headers=admin_headers,
            json={"mac": lower_mac, "ip": "10.250.97.51", "name": "TEST_MMB_lc",
                  "device_type": "generic", "client_id": CLIENT_ID},
            timeout=10,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["mac"] == lower_mac.upper()
        # cleanup this binding to keep set sane
        mongo_db.mac_device_bindings.delete_one({"mac": lower_mac.upper()})


class TestMacBindingList:
    """GET /api/topology/mac-bindings."""

    def test_list_all_no_filter(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/topology/mac-bindings",
            headers=admin_headers, timeout=10,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "items" in body and "count" in body
        assert isinstance(body["items"], list)
        assert body["count"] == len(body["items"])
        # Our created MAC must appear
        macs = [b.get("mac") for b in body["items"]]
        assert MAC_TO_BIND in macs

    def test_list_filtered_by_client_id(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/topology/mac-bindings",
            headers=admin_headers,
            params={"client_id": CLIENT_ID},
            timeout=10,
        )
        assert r.status_code == 200
        body = r.json()
        # Tutti gli items devono avere il nostro client_id
        for b in body["items"]:
            assert b.get("client_id") == CLIENT_ID
        macs = [b.get("mac") for b in body["items"]]
        assert MAC_TO_BIND in macs

    def test_list_filtered_unknown_client_returns_empty(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/topology/mac-bindings",
            headers=admin_headers,
            params={"client_id": "TEST_NONEXISTENT_CLIENT_xx"},
            timeout=10,
        )
        assert r.status_code == 200
        assert r.json()["count"] == 0


class TestSwitchPortsManualBindingPriority:
    """GET /api/devices/{ip}/switch-ports - priorita' manual e nuovi campi top-level."""

    def test_top_level_device_name_and_client_id(self, admin_headers):
        """v3.6.16: response top-level deve includere device_name e client_id."""
        r = requests.get(
            f"{BASE_URL}/api/devices/{SWITCH_IP}/switch-ports",
            headers=admin_headers, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "device_name" in body, "Missing top-level 'device_name'"
        assert "client_id" in body, "Missing top-level 'client_id'"
        assert body["device_name"] == SWITCH_NAME
        assert body["client_id"] == CLIENT_ID

    def test_port_with_manual_binding_match_source_mac_manual(self, admin_headers):
        """Port idx=10: MAC bound, no LLDP -> match_source='mac_manual'."""
        r = requests.get(
            f"{BASE_URL}/api/devices/{SWITCH_IP}/switch-ports",
            headers=admin_headers, timeout=15,
        )
        assert r.status_code == 200
        by_idx = {p["idx"]: p for p in r.json()["ports"]}
        port = by_idx.get(10)
        assert port is not None
        neigh = port.get("neighbor")
        assert neigh is not None, f"Neighbor missing on port 10: {port}"
        assert neigh.get("match_source") == "mac_manual", (
            f"Expected match_source='mac_manual', got '{neigh.get('match_source')}'"
        )
        assert neigh.get("remote_ip") == BOUND_IP
        # remote_device_name e remote_sys_name dal binding
        assert neigh.get("remote_device_name") == "TEST_MMB_Bound_Device_RENAMED"
        assert neigh.get("remote_sys_name") == "TEST_MMB_Bound_Device_RENAMED"
        assert neigh.get("remote_device_type") == "printer"

    def test_lldp_wins_over_manual_binding_on_same_port(self, admin_headers, mongo_db):
        """Port idx=11: ha LLDP + binding sul MAC -> LLDP vince (match_source='lldp')."""
        # Crea il binding sul MAC che e' sulla porta 11
        r = requests.post(
            f"{BASE_URL}/api/topology/mac-bindings",
            headers=admin_headers,
            json={"mac": MAC_LLDP_ALSO_BOUND, "ip": "10.250.97.61",
                  "name": "TEST_MMB_ShouldNotWin", "device_type": "generic",
                  "client_id": CLIENT_ID},
            timeout=10,
        )
        assert r.status_code == 200

        try:
            r = requests.get(
                f"{BASE_URL}/api/devices/{SWITCH_IP}/switch-ports",
                headers=admin_headers, timeout=15,
            )
            assert r.status_code == 200
            by_idx = {p["idx"]: p for p in r.json()["ports"]}
            port = by_idx.get(11)
            assert port is not None
            neigh = port.get("neighbor")
            assert neigh is not None
            assert neigh.get("match_source") == "lldp", (
                f"LLDP must win over manual binding, got '{neigh.get('match_source')}'"
            )
            assert neigh.get("remote_sys_name") == "TEST_MMB_LLDP_Peer"
        finally:
            mongo_db.mac_device_bindings.delete_one({"mac": MAC_LLDP_ALSO_BOUND})

    def test_regression_mac_oui_unchanged_without_binding(self, admin_headers):
        """Port idx=12: MAC Apple senza binding -> mac_oui (regressione)."""
        r = requests.get(
            f"{BASE_URL}/api/devices/{SWITCH_IP}/switch-ports",
            headers=admin_headers, timeout=15,
        )
        by_idx = {p["idx"]: p for p in r.json()["ports"]}
        neigh = by_idx[12].get("neighbor")
        assert neigh is not None
        assert neigh.get("match_source") == "mac_oui", (
            f"Expected mac_oui, got '{neigh.get('match_source')}'"
        )

    def test_regression_mac_unknown_unchanged_without_binding(self, admin_headers):
        """Port idx=13: MAC OUI sconosciuto, no binding -> mac_unknown."""
        r = requests.get(
            f"{BASE_URL}/api/devices/{SWITCH_IP}/switch-ports",
            headers=admin_headers, timeout=15,
        )
        by_idx = {p["idx"]: p for p in r.json()["ports"]}
        neigh = by_idx[13].get("neighbor")
        assert neigh is not None
        assert neigh.get("match_source") == "mac_unknown"

    def test_regression_mac_managed_unchanged_without_binding(self, admin_headers):
        """Port idx=14: MAC NAS managed, no binding -> mac_managed."""
        r = requests.get(
            f"{BASE_URL}/api/devices/{SWITCH_IP}/switch-ports",
            headers=admin_headers, timeout=15,
        )
        by_idx = {p["idx"]: p for p in r.json()["ports"]}
        neigh = by_idx[14].get("neighbor")
        assert neigh is not None
        assert neigh.get("match_source") == "mac_managed"
        assert neigh.get("remote_ip") == NAS_IP


class TestMacBindingDelete:
    """DELETE /api/topology/mac-bindings/{mac}."""

    def test_delete_existing_unsets_endpoint_overrides(self, admin_headers, mongo_db):
        """DELETE rimuove binding e fa $unset di manual_binding_* su discovered_endpoints."""
        # Pre-condition: binding esiste (creato in TestMacBindingCreateAndUpdate)
        ep_before = mongo_db.discovered_endpoints.find_one(
            {"switch_ip": SWITCH_IP, "mac": MAC_TO_BIND}
        )
        assert ep_before.get("manual_binding_ip") == BOUND_IP

        r = requests.delete(
            f"{BASE_URL}/api/topology/mac-bindings/{MAC_TO_BIND}",
            headers=admin_headers, timeout=10,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("deleted") == 1

        # Binding rimosso
        assert mongo_db.mac_device_bindings.find_one({"mac": MAC_TO_BIND}) is None

        # discovered_endpoints: campi rimossi
        ep_after = mongo_db.discovered_endpoints.find_one(
            {"switch_ip": SWITCH_IP, "mac": MAC_TO_BIND}
        )
        assert ep_after is not None
        assert "manual_binding_ip" not in ep_after, "manual_binding_ip not unset"
        assert "manual_binding_name" not in ep_after
        assert "manual_binding_type" not in ep_after

    def test_delete_nonexistent_returns_404(self, admin_headers):
        r = requests.delete(
            f"{BASE_URL}/api/topology/mac-bindings/00:00:00:00:00:00",
            headers=admin_headers, timeout=10,
        )
        assert r.status_code == 404

    def test_after_delete_port_falls_back_to_default_neighbor(self, admin_headers):
        """Dopo DELETE, port idx=10 (MAC unmanaged unknown OUI prefix AA:BB:CC) torna mac_unknown/oui."""
        r = requests.get(
            f"{BASE_URL}/api/devices/{SWITCH_IP}/switch-ports",
            headers=admin_headers, timeout=15,
        )
        by_idx = {p["idx"]: p for p in r.json()["ports"]}
        neigh = by_idx[10].get("neighbor")
        assert neigh is not None
        # Non deve piu' essere mac_manual
        assert neigh.get("match_source") != "mac_manual"
        assert neigh.get("match_source") in ("mac_unknown", "mac_oui")
