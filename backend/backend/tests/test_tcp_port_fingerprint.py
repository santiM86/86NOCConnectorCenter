"""
Test suite for NOC Connector TCP Port Fingerprint Probe feature (v3.6.13)

Covers:
- POST /api/connector/network-discovery with ip_port_probes: persistence in db.network_discovery
- discovered_endpoints collection gets listening_ports populated
- GET /api/network/topology/{client_id} returns nodes with listening_ports and correct type
- _guess_endpoint_type direct unit-level behavior via topology nodes
- Regression: legacy payload without ip_port_probes still works
"""
import os
import sys
import uuid
import pytest
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load env from backend/.env and frontend/.env so BASE_URL / MONGO_URL / DB_NAME are set
load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")

# Ensure backend modules are importable for direct unit test of _guess_endpoint_type
BACKEND_DIR = "/app/backend"
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from pymongo import MongoClient  # noqa: E402

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set (frontend/.env)"

ADMIN_EMAIL = "admin@86bit.it"
ADMIN_PASSWORD = "password"


# ---------- Shared fixtures ----------
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
def test_client(admin_token, mongo_db):
    """Create a dedicated test client + a seeded managed device in device_poll_status.
    Teardown removes everything created."""
    headers = {"Authorization": f"Bearer {admin_token}"}
    name = f"TEST_tcp_fp_{uuid.uuid4().hex[:8]}"
    r = requests.post(
        f"{BASE_URL}/api/clients",
        json={"name": name, "description": "TCP fingerprint test", "contact_email": "test@example.com"},
        headers=headers,
        timeout=10,
    )
    assert r.status_code == 200, f"Client create failed: {r.status_code} {r.text}"
    data = r.json()
    client_id = data["id"]
    api_key = data["api_key"]

    # Seed a managed device (a switch) in device_poll_status so topology has a node.
    switch_ip = "10.77.77.1"
    managed_srv_ip = "10.77.77.10"  # Will be referenced in device_macs (managed via ARP)
    mongo_db.device_poll_status.insert_many([
        {
            "client_id": client_id,
            "device_ip": switch_ip,
            "device_name": "TEST_Core_Switch",
            "device_type": "switch",
            "reachable": True,
            "ping_ms": 1,
            "ports": [],
            "monitor_type": "snmp",
            "sys_descr": "test switch",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    ])

    yield {
        "id": client_id,
        "api_key": api_key,
        "switch_ip": switch_ip,
        "managed_srv_ip": managed_srv_ip,
    }

    # Cleanup
    for coll in [
        "network_discovery", "discovered_endpoints", "mac_connections",
        "port_speeds", "device_poll_status", "topology_layouts", "lldp_neighbors",
        "alerts", "port_flap_events",
    ]:
        mongo_db[coll].delete_many({"client_id": client_id})
    requests.delete(f"{BASE_URL}/api/clients/{client_id}", headers=headers, timeout=10)


# ---------- Tests ----------

class TestNetworkDiscoveryPersistence:
    """Persistence of ip_port_probes in db.network_discovery"""

    def test_post_with_ip_port_probes_returns_ok_and_persists(self, test_client, mongo_db):
        switch_ip = test_client["switch_ip"]
        payload = {
            "mac_tables": [
                {
                    "switch_ip": switch_ip,
                    "entries": [
                        {"mac": "AA:BB:CC:00:00:01", "port": 1, "vlan": "10", "ip": "10.77.77.100", "hostname": ""},
                        {"mac": "AA:BB:CC:00:00:02", "port": 2, "vlan": "10", "ip": "10.77.77.101", "hostname": ""},
                        {"mac": "AA:BB:CC:00:00:03", "port": 3, "vlan": "10", "ip": "10.77.77.102", "hostname": ""},
                    ],
                }
            ],
            "device_macs": [
                # Managed server advertised via ARP with its MAC
                {"ip": test_client["managed_srv_ip"], "macs": ["AA:BB:CC:00:00:99"]},
            ],
            "port_speeds": [],
            "ip_port_probes": [
                {"ip": "10.77.77.100", "ports": [3389]},            # server (RDP)
                {"ip": "10.77.77.101", "ports": [9100]},            # printer (RAW)
                {"ip": "10.77.77.102", "ports": [22, 80]},          # server (SSH+HTTP)
                {"ip": test_client["managed_srv_ip"], "ports": [443, 22]},  # managed server
            ],
        }
        r = requests.post(
            f"{BASE_URL}/api/connector/network-discovery",
            json=payload,
            headers={"X-API-Key": test_client["api_key"]},
            timeout=15,
        )
        assert r.status_code == 200, f"status={r.status_code} body={r.text}"
        body = r.json()
        assert body.get("status") == "ok"

        # Verify persistence in db.network_discovery
        doc = mongo_db.network_discovery.find_one({"client_id": test_client["id"]})
        assert doc is not None, "network_discovery doc missing"
        assert "ip_port_probes" in doc, "ip_port_probes field missing in network_discovery"
        stored = doc["ip_port_probes"]
        assert isinstance(stored, list) and len(stored) == 4
        stored_map = {p["ip"]: sorted(p["ports"]) for p in stored}
        assert stored_map["10.77.77.100"] == [3389]
        assert stored_map["10.77.77.101"] == [9100]
        assert sorted(stored_map["10.77.77.102"]) == [22, 80]


class TestDiscoveredEndpointsListeningPorts:
    """discovered_endpoints must have listening_ports when IP is known in probes"""

    def test_listening_ports_populated_on_endpoints(self, test_client, mongo_db):
        # Relies on data pushed in previous class, but re-post to be order-independent.
        switch_ip = test_client["switch_ip"]
        payload = {
            "mac_tables": [
                {
                    "switch_ip": switch_ip,
                    "entries": [
                        {"mac": "AA:BB:CC:00:00:01", "port": 1, "vlan": "10", "ip": "10.77.77.100"},
                        {"mac": "AA:BB:CC:00:00:02", "port": 2, "vlan": "10", "ip": "10.77.77.101"},
                        {"mac": "AA:BB:CC:00:00:03", "port": 3, "vlan": "10", "ip": "10.77.77.102"},
                        # Entry with no IP and not in device_macs → listening_ports should be empty list
                        {"mac": "AA:BB:CC:00:00:04", "port": 4, "vlan": "10"},
                    ],
                }
            ],
            "device_macs": [
                {"ip": test_client["managed_srv_ip"], "macs": ["AA:BB:CC:00:00:99"]},
            ],
            "ip_port_probes": [
                {"ip": "10.77.77.100", "ports": [3389]},
                {"ip": "10.77.77.101", "ports": [9100]},
                {"ip": "10.77.77.102", "ports": [22, 80]},
            ],
        }
        r = requests.post(
            f"{BASE_URL}/api/connector/network-discovery",
            json=payload,
            headers={"X-API-Key": test_client["api_key"]},
            timeout=15,
        )
        assert r.status_code == 200, r.text

        eps = list(mongo_db.discovered_endpoints.find({"client_id": test_client["id"]}, {"_id": 0}))
        by_ip = {e.get("ip"): e for e in eps if e.get("ip")}

        assert "10.77.77.100" in by_ip
        assert by_ip["10.77.77.100"].get("listening_ports") == [3389]

        assert "10.77.77.101" in by_ip
        assert by_ip["10.77.77.101"].get("listening_ports") == [9100]

        assert "10.77.77.102" in by_ip
        assert sorted(by_ip["10.77.77.102"].get("listening_ports") or []) == [22, 80]

        # Endpoint with no IP must have empty listening_ports (not missing)
        no_ip_eps = [e for e in eps if not e.get("ip")]
        assert len(no_ip_eps) >= 1
        for e in no_ip_eps:
            assert e.get("listening_ports") == []


class TestTopologyNodesListeningPorts:
    """Topology should expose listening_ports & classify type correctly on discovered_endpoint nodes"""

    def test_topology_nodes_have_listening_ports_and_correct_type(self, test_client, mongo_db, admin_token):
        # Push discovery
        switch_ip = test_client["switch_ip"]
        payload = {
            "mac_tables": [
                {
                    "switch_ip": switch_ip,
                    "entries": [
                        {"mac": "AA:BB:CC:00:00:01", "port": 1, "vlan": "10", "ip": "10.77.77.100"},
                        {"mac": "AA:BB:CC:00:00:02", "port": 2, "vlan": "10", "ip": "10.77.77.101"},
                        {"mac": "AA:BB:CC:00:00:03", "port": 3, "vlan": "10", "ip": "10.77.77.102"},
                    ],
                }
            ],
            "ip_port_probes": [
                {"ip": "10.77.77.100", "ports": [3389]},     # server
                {"ip": "10.77.77.101", "ports": [9100]},     # printer
                {"ip": "10.77.77.102", "ports": [22, 80]},   # server
            ],
        }
        r = requests.post(
            f"{BASE_URL}/api/connector/network-discovery",
            json=payload,
            headers={"X-API-Key": test_client["api_key"]},
            timeout=15,
        )
        assert r.status_code == 200, r.text

        # Ensure no saved layout masks the inferred flow
        mongo_db.topology_layouts.delete_many({"client_id": test_client["id"]})

        # Fetch topology
        r2 = requests.get(
            f"{BASE_URL}/api/network/topology/{test_client['id']}",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        assert r2.status_code == 200, r2.text
        topo = r2.json()
        assert not topo.get("has_custom_layout"), "Custom layout present, invalidates inferred test"

        ep_nodes = [n for n in topo.get("nodes", []) if n.get("role") == "discovered_endpoint"]
        by_ip = {n.get("ip"): n for n in ep_nodes if n.get("ip")}

        # Assert we have our 3 test endpoints (all unmanaged since not in device_macs nor poll_status)
        for ip in ("10.77.77.100", "10.77.77.101", "10.77.77.102"):
            assert ip in by_ip, f"Endpoint {ip} missing from topology nodes: {list(by_ip.keys())}"

        # listening_ports must be exposed
        assert by_ip["10.77.77.100"].get("listening_ports") == [3389]
        assert by_ip["10.77.77.101"].get("listening_ports") == [9100]
        assert sorted(by_ip["10.77.77.102"].get("listening_ports") or []) == [22, 80]

        # Type classification
        assert by_ip["10.77.77.100"].get("type") == "server", f"3389 → expected server, got {by_ip['10.77.77.100'].get('type')}"
        assert by_ip["10.77.77.101"].get("type") == "printer", f"9100 → expected printer, got {by_ip['10.77.77.101'].get('type')}"
        assert by_ip["10.77.77.102"].get("type") == "server", f"22+80 → expected server, got {by_ip['10.77.77.102'].get('type')}"


class TestGuessEndpointTypeDirect:
    """Direct unit test on _guess_endpoint_type"""

    def test_guess_endpoint_type_port_fingerprints(self):
        from routes.topology import _guess_endpoint_type

        # RDP → server
        assert _guess_endpoint_type("", "", [3389]) == "server"
        # Printer ports
        assert _guess_endpoint_type("", "", [9100]) == "printer"
        assert _guess_endpoint_type("", "", [515]) == "printer"
        assert _guess_endpoint_type("", "", [631]) == "printer"
        # SSH + HTTP → server
        assert _guess_endpoint_type("", "", [22, 80]) == "server"
        # SSH alone → server
        assert _guess_endpoint_type("", "", [22]) == "server"
        # SIP → generic (VoIP phone)
        assert _guess_endpoint_type("", "", [5060]) == "generic"
        # Hostname priority over ports
        assert _guess_endpoint_type("printer-lab", "", [3389]) == "printer"
        # No hostname, no mac, no ports → generic fallback
        assert _guess_endpoint_type("", "", []) == "generic"


class TestLegacyPayloadRegression:
    """Payload without ip_port_probes must still work (backward compatibility)"""

    def test_legacy_payload_without_ip_port_probes(self, test_client, mongo_db):
        switch_ip = test_client["switch_ip"]
        payload = {
            "mac_tables": [
                {
                    "switch_ip": switch_ip,
                    "entries": [
                        {"mac": "DE:AD:BE:EF:00:01", "port": 10, "vlan": "20", "ip": "10.77.77.200"},
                    ],
                }
            ],
            "device_macs": [],
            "port_speeds": [],
            # No ip_port_probes key intentionally
        }
        r = requests.post(
            f"{BASE_URL}/api/connector/network-discovery",
            json=payload,
            headers={"X-API-Key": test_client["api_key"]},
            timeout=15,
        )
        assert r.status_code == 200, f"Legacy payload failed: {r.status_code} {r.text}"
        body = r.json()
        assert body.get("status") == "ok"
        assert body.get("mac_entries") == 1

        # listening_ports should be an empty list on the persisted endpoint
        ep = mongo_db.discovered_endpoints.find_one(
            {"client_id": test_client["id"], "ip": "10.77.77.200"}, {"_id": 0}
        )
        assert ep is not None
        assert ep.get("listening_ports") == []

        # network_discovery doc exists and ip_port_probes is [] (since we didn't send it)
        nd = mongo_db.network_discovery.find_one({"client_id": test_client["id"]})
        assert nd is not None
        assert nd.get("ip_port_probes", []) == []
