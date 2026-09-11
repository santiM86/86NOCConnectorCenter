"""
Test suite for v3.6.15 MAC Cross-Correlation per trunk switch-to-switch.

Endpoint sotto test: GET /api/devices/{device_ip}/switch-ports
File: backend/routes/topology.py (precomputazione remote_port_cache + _build_mac_neighbor)

Cosa verifichiamo:
1) Trunk bidirezionale tra 2 switch managed (A,B):
   - porta di A che vede in FDB un MAC di un'interfaccia di B,
   - e B vede in FDB un MAC delle interfacce di A su una sua porta
   --> match_source='mac_fdb_trunk', remote_ip=B_ip, remote_port_id='<port_int_string>',
       remote_sys_cap=4, remote_sys_desc contiene 'Trunk switch-to-switch'.
2) Caso "managed NON switch" (NAS): match_source='mac_managed', remote_port_id=''.
3) Regressione LLDP: porta con LLDP neighbor presente -> match_source='lldp'
   (il neighbor LLDP ha priorita' su MAC).
4) Regressione MAC OUI: porta con endpoint unmanaged + OUI noto -> 'mac_oui'.
5) Regressione MAC unknown: OUI sconosciuto -> 'mac_unknown'.
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

# Test data identifiers (TEST_ prefix for cleanup)
CLIENT_ID = f"TEST_mac_trunk_{uuid.uuid4().hex[:8]}"
SWITCH_A_IP = "10.250.99.11"
SWITCH_B_IP = "10.250.99.12"
NAS_IP = "10.250.99.50"

# MAC interfacce switch
A_IF_MAC_1 = "AA:BB:CC:00:00:11"
A_IF_MAC_2 = "AA:BB:CC:00:00:12"
B_IF_MAC_1 = "BB:CC:DD:00:00:21"
B_IF_MAC_2 = "BB:CC:DD:00:00:22"
NAS_MAC = "00:11:32:AA:BB:CC"  # Synology OUI 00:11:32

# Apple OUI per test mac_oui (28:CF:E9 = Apple)
APPLE_MAC = "28:CF:E9:11:22:33"
# OUI sconosciuto - usiamo F2:F2:F2 (locally administered, sicuramente sconosciuto)
UNKNOWN_MAC = "F2:F2:F2:33:44:55"


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
    """Seed managed_devices, switch_ports, network_discovery, discovered_endpoints, lldp_neighbors."""
    now = datetime.now(timezone.utc).isoformat()

    # --- managed_devices: 2 switch + 1 NAS ---
    mongo_db.managed_devices.delete_many({"client_id": CLIENT_ID})
    mongo_db.managed_devices.insert_many([
        {
            "id": str(uuid.uuid4()), "client_id": CLIENT_ID,
            "ip": SWITCH_A_IP, "device_name": "TEST_Switch_A",
            "device_type": "switch", "vendor": "HPE", "monitor_type": "snmp",
        },
        {
            "id": str(uuid.uuid4()), "client_id": CLIENT_ID,
            "ip": SWITCH_B_IP, "device_name": "TEST_Switch_B",
            "device_type": "switch", "vendor": "HPE", "monitor_type": "snmp",
        },
        {
            "id": str(uuid.uuid4()), "client_id": CLIENT_ID,
            "ip": NAS_IP, "device_name": "TEST_NAS_Synology",
            "device_type": "nas", "vendor": "Synology", "monitor_type": "snmp",
        },
    ])

    # --- switch_ports: porte di A (idx 24..28) ---
    mongo_db.switch_ports.delete_many({"local_ip": SWITCH_A_IP, "alias": {"$regex": "^TEST_"}})
    mongo_db.switch_ports.delete_many({"local_ip": SWITCH_A_IP})  # pulizia totale per device test
    ports_A = [
        {"local_ip": SWITCH_A_IP, "idx": 24, "name": "Gi1/0/24", "alias": "TEST_lldp_port",
         "oper": 1, "admin": 1, "speed_mbps": 1000, "updated_at": now},
        {"local_ip": SWITCH_A_IP, "idx": 25, "name": "Gi1/0/25", "alias": "TEST_trunk_port",
         "oper": 1, "admin": 1, "speed_mbps": 10000, "updated_at": now},
        {"local_ip": SWITCH_A_IP, "idx": 26, "name": "Gi1/0/26", "alias": "TEST_nas_port",
         "oper": 1, "admin": 1, "speed_mbps": 1000, "updated_at": now},
        {"local_ip": SWITCH_A_IP, "idx": 27, "name": "Gi1/0/27", "alias": "TEST_apple_port",
         "oper": 1, "admin": 1, "speed_mbps": 1000, "updated_at": now},
        {"local_ip": SWITCH_A_IP, "idx": 28, "name": "Gi1/0/28", "alias": "TEST_unknown_port",
         "oper": 1, "admin": 1, "speed_mbps": 1000, "updated_at": now},
    ]
    mongo_db.switch_ports.insert_many(ports_A)

    # --- network_discovery: device_macs di A e B ---
    mongo_db.network_discovery.delete_many({"client_id": CLIENT_ID})
    mongo_db.network_discovery.insert_one({
        "client_id": CLIENT_ID,
        "updated_at": now,
        "device_macs": [
            {"ip": SWITCH_A_IP, "macs": [A_IF_MAC_1, A_IF_MAC_2]},
            {"ip": SWITCH_B_IP, "macs": [B_IF_MAC_1, B_IF_MAC_2]},
        ],
    })

    # --- discovered_endpoints ---
    mongo_db.discovered_endpoints.delete_many({"switch_ip": {"$in": [SWITCH_A_IP, SWITCH_B_IP]}})
    endpoints = [
        # Porta 25 di A: MAC di un'interfaccia di B (B e' managed switch) -> trunk side
        {"client_id": CLIENT_ID, "switch_ip": SWITCH_A_IP, "port": 25,
         "mac": B_IF_MAC_1, "ip": SWITCH_B_IP, "is_managed": True,
         "hostname": "TEST_Switch_B"},
        # Porta 26 di A: MAC del NAS managed (NON switch -> deve restare mac_managed)
        {"client_id": CLIENT_ID, "switch_ip": SWITCH_A_IP, "port": 26,
         "mac": NAS_MAC, "ip": NAS_IP, "is_managed": True,
         "hostname": "TEST_NAS"},
        # Porta 27 di A: MAC Apple unmanaged (mac_oui)
        {"client_id": CLIENT_ID, "switch_ip": SWITCH_A_IP, "port": 27,
         "mac": APPLE_MAC, "ip": "", "is_managed": False, "hostname": ""},
        # Porta 28 di A: MAC unknown unmanaged (mac_unknown)
        {"client_id": CLIENT_ID, "switch_ip": SWITCH_A_IP, "port": 28,
         "mac": UNKNOWN_MAC, "ip": "", "is_managed": False, "hostname": ""},
        # Su B porta 26: MAC di interfaccia di A (chiude il trunk bidirezionale)
        {"client_id": CLIENT_ID, "switch_ip": SWITCH_B_IP, "port": 26,
         "mac": A_IF_MAC_1, "ip": SWITCH_A_IP, "is_managed": True,
         "hostname": "TEST_Switch_A"},
        # Aggiungiamo anche un secondo MAC di A su B porta 26 per validare il counter
        {"client_id": CLIENT_ID, "switch_ip": SWITCH_B_IP, "port": 26,
         "mac": A_IF_MAC_2, "ip": SWITCH_A_IP, "is_managed": True,
         "hostname": "TEST_Switch_A"},
    ]
    mongo_db.discovered_endpoints.insert_many(endpoints)

    # --- lldp_neighbors: porta 24 di A ha LLDP attivo (regressione: ha precedenza) ---
    mongo_db.lldp_neighbors.delete_many({"local_ip": SWITCH_A_IP})
    mongo_db.lldp_neighbors.insert_one({
        "client_id": CLIENT_ID,
        "local_ip": SWITCH_A_IP,
        "local_port_id": "Gi1/0/24",
        "local_port_desc": "Gi1/0/24",
        "remote_sys_name": "TEST_LLDP_Peer",
        "remote_ip": "10.250.99.99",
        "remote_port_id": "Gi0/1",
        "remote_port_desc": "Uplink",
        "remote_chassis_id": "11:22:33:44:55:66",
        "remote_sys_cap": 4,
        "remote_sys_desc": "LLDP via SNMP",
    })

    yield

    # Teardown
    mongo_db.managed_devices.delete_many({"client_id": CLIENT_ID})
    mongo_db.switch_ports.delete_many({"local_ip": SWITCH_A_IP})
    mongo_db.network_discovery.delete_many({"client_id": CLIENT_ID})
    mongo_db.discovered_endpoints.delete_many({"switch_ip": {"$in": [SWITCH_A_IP, SWITCH_B_IP]}})
    mongo_db.lldp_neighbors.delete_many({"local_ip": SWITCH_A_IP})


# ---------------- Tests ----------------

def _get_switch_ports(headers):
    r = requests.get(
        f"{BASE_URL}/api/devices/{SWITCH_A_IP}/switch-ports",
        headers=headers, timeout=15,
    )
    assert r.status_code == 200, f"Got {r.status_code}: {r.text}"
    body = r.json()
    assert "ports" in body
    by_idx = {p["idx"]: p for p in body["ports"]}
    return body, by_idx


class TestMacTrunkCorrelation:
    """v3.6.15 - MAC Cross-Correlation switch-to-switch."""

    def test_mac_fdb_trunk_when_peer_is_managed_switch_with_bidirectional_fdb(self, admin_headers):
        """Porta 25 di A: peer e' switch B managed e B vede MAC di A su porta 26 -> mac_fdb_trunk."""
        body, by_idx = _get_switch_ports(admin_headers)
        port = by_idx.get(25)
        assert port is not None, "Port idx=25 missing in response"
        neigh = port.get("neighbor")
        assert neigh is not None, f"Neighbor missing on port 25: {port}"

        assert neigh.get("match_source") == "mac_fdb_trunk", (
            f"Expected match_source='mac_fdb_trunk', got '{neigh.get('match_source')}'"
        )
        assert neigh.get("remote_ip") == SWITCH_B_IP
        # remote_port_id deve essere stringa numerica '26'
        rport = neigh.get("remote_port_id")
        assert rport == "26", f"Expected remote_port_id='26', got '{rport}' (type={type(rport).__name__})"
        assert isinstance(rport, str), f"remote_port_id must be string, got {type(rport).__name__}"
        # bridge cap bit
        assert int(neigh.get("remote_sys_cap") or 0) == 4, (
            f"Expected remote_sys_cap=4 (bridge), got {neigh.get('remote_sys_cap')}"
        )
        assert "Trunk switch-to-switch" in (neigh.get("remote_sys_desc") or ""), (
            f"remote_sys_desc must contain 'Trunk switch-to-switch', got '{neigh.get('remote_sys_desc')}'"
        )
        # remote_port_desc derivato
        assert "26" in (neigh.get("remote_port_desc") or "")

    def test_mac_managed_when_peer_is_managed_non_switch_nas(self, admin_headers):
        """Porta 26 di A: peer e' un NAS managed (non switch) -> match_source='mac_managed', remote_port_id=''."""
        _, by_idx = _get_switch_ports(admin_headers)
        port = by_idx.get(26)
        assert port is not None
        neigh = port.get("neighbor")
        assert neigh is not None, f"Neighbor missing on port 26 (NAS): {port}"

        assert neigh.get("match_source") == "mac_managed", (
            f"Expected 'mac_managed' (non-switch managed), got '{neigh.get('match_source')}'"
        )
        assert neigh.get("remote_ip") == NAS_IP
        assert neigh.get("remote_port_id") == "", (
            f"remote_port_id must be empty for non-switch peer, got '{neigh.get('remote_port_id')}'"
        )
        # cap=0 perche' non e' bridge
        assert int(neigh.get("remote_sys_cap") or 0) == 0
        # remote_device_type del NAS
        assert (neigh.get("remote_device_type") or "").lower() == "nas"

    def test_lldp_takes_priority_over_mac(self, admin_headers):
        """Porta 24 ha LLDP -> match_source='lldp' anche se ci fossero endpoint MAC."""
        _, by_idx = _get_switch_ports(admin_headers)
        port = by_idx.get(24)
        assert port is not None
        neigh = port.get("neighbor")
        assert neigh is not None
        assert neigh.get("match_source") == "lldp", (
            f"LLDP must win over MAC, got match_source='{neigh.get('match_source')}'"
        )
        assert neigh.get("remote_sys_name") == "TEST_LLDP_Peer"

    def test_mac_oui_for_unmanaged_known_vendor(self, admin_headers):
        """Porta 27: MAC Apple unmanaged -> match_source='mac_oui'."""
        _, by_idx = _get_switch_ports(admin_headers)
        port = by_idx.get(27)
        assert port is not None
        neigh = port.get("neighbor")
        assert neigh is not None, f"Neighbor missing on port 27 (Apple): {port}"
        assert neigh.get("match_source") == "mac_oui", (
            f"Expected 'mac_oui' for known OUI unmanaged, got '{neigh.get('match_source')}'"
        )
        # remote_port_id vuoto, cap=0
        assert neigh.get("remote_port_id") == ""
        assert int(neigh.get("remote_sys_cap") or 0) == 0

    def test_mac_unknown_for_unmanaged_unknown_oui(self, admin_headers):
        """Porta 28: MAC OUI sconosciuto -> match_source='mac_unknown'."""
        _, by_idx = _get_switch_ports(admin_headers)
        port = by_idx.get(28)
        assert port is not None
        neigh = port.get("neighbor")
        assert neigh is not None, f"Neighbor missing on port 28 (unknown): {port}"
        assert neigh.get("match_source") == "mac_unknown", (
            f"Expected 'mac_unknown', got '{neigh.get('match_source')}'"
        )

    def test_response_totals_and_status_ok(self, admin_headers):
        """Smoke test: la risposta complessiva ha totals coerenti."""
        body, by_idx = _get_switch_ports(admin_headers)
        assert body.get("device_ip") == SWITCH_A_IP
        assert isinstance(body.get("ports"), list)
        assert len(body["ports"]) >= 5
        totals = body.get("totals", {})
        # almeno 5 porte UP nei nostri seed
        assert totals.get("up", 0) >= 5
        # neighbor totali: 5 (24 lldp + 25,26,27,28 mac)
        assert totals.get("with_neighbor", 0) >= 5

    def test_no_n_plus_1_query_explosion(self, admin_headers):
        """La precomputazione cache deve raggruppare le query: la chiamata deve restare veloce.
        Soglia generosa (5s) sul caso minimo: 1 peer switch candidato.
        """
        import time
        t0 = time.time()
        r = requests.get(
            f"{BASE_URL}/api/devices/{SWITCH_A_IP}/switch-ports",
            headers=admin_headers, timeout=15,
        )
        dt = time.time() - t0
        assert r.status_code == 200
        assert dt < 5.0, f"Switch-ports endpoint too slow: {dt:.2f}s"
