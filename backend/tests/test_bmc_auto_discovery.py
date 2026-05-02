"""
Test suite for NOC Connector Redfish/BMC Auto-Discovery feature (v3.6.14)

Covers:
- POST /api/connector/network-discovery con bmc_candidates: persistence in db.network_discovery
- Upsert in db.bmc_candidates per-IP (unique per client_id+ip)
- discovered_endpoints arricchiti con bmc_kind / bmc_version
- _guess_endpoint_type ritorna 'server' per bmc_kind in (ilo,idrac,ipmi,xcc,redfish_generic)
- GET /api/bmc-candidates?client_id=X  (JWT admin)
- POST /api/bmc-candidates/{cid}/{ip}/dismiss
- POST /api/bmc-candidates/{cid}/{ip}/import
- Re-import = already_exists
- Regressione: payload legacy senza bmc_candidates funziona
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
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def test_client(admin_headers, mongo_db):
    """Crea un client di test + un seeded switch in device_poll_status."""
    name = f"TEST_bmc_{uuid.uuid4().hex[:8]}"
    r = requests.post(
        f"{BASE_URL}/api/clients",
        json={"name": name, "description": "BMC auto-discovery test", "contact_email": "test@example.com"},
        headers=admin_headers,
        timeout=10,
    )
    assert r.status_code == 200, f"Client create failed: {r.status_code} {r.text}"
    data = r.json()
    client_id = data["id"]
    api_key = data["api_key"]

    switch_ip = "10.88.88.1"
    mongo_db.device_poll_status.insert_one({
        "client_id": client_id,
        "device_ip": switch_ip,
        "device_name": "TEST_BMC_Switch",
        "device_type": "switch",
        "reachable": True,
        "ports": [],
        "monitor_type": "snmp",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })

    yield {
        "id": client_id,
        "api_key": api_key,
        "switch_ip": switch_ip,
    }

    # Cleanup
    for coll in [
        "network_discovery", "discovered_endpoints", "mac_connections",
        "device_poll_status", "bmc_candidates", "devices", "managed_devices",
    ]:
        mongo_db[coll].delete_many({"client_id": client_id})
    requests.delete(f"{BASE_URL}/api/clients/{client_id}", headers=admin_headers, timeout=10)


@pytest.fixture(scope="module")
def post_bmc_payload(test_client, mongo_db):
    """Posta un payload network-discovery con BMC candidates e ritorna info utili."""
    switch_ip = test_client["switch_ip"]
    bmc_ilo_ip = "10.88.88.50"
    bmc_idrac_ip = "10.88.88.51"
    bmc_ipmi_ip = "10.88.88.52"

    payload = {
        "mac_tables": [
            {
                "switch_ip": switch_ip,
                "entries": [
                    {"mac": "AA:BB:CC:11:11:01", "port": 1, "vlan": "20", "ip": bmc_ilo_ip, "hostname": ""},
                    {"mac": "AA:BB:CC:11:11:02", "port": 2, "vlan": "20", "ip": bmc_idrac_ip, "hostname": ""},
                    {"mac": "AA:BB:CC:11:11:03", "port": 3, "vlan": "20", "ip": bmc_ipmi_ip, "hostname": ""},
                ],
            }
        ],
        "device_macs": [
            {"ip": bmc_ilo_ip, "macs": ["AA:BB:CC:11:11:01"]},
            {"ip": bmc_idrac_ip, "macs": ["AA:BB:CC:11:11:02"]},
            {"ip": bmc_ipmi_ip, "macs": ["AA:BB:CC:11:11:03"]},
        ],
        "ip_port_probes": [
            {"ip": bmc_ilo_ip, "ports": [443]},
            {"ip": bmc_idrac_ip, "ports": [443]},
            {"ip": bmc_ipmi_ip, "ports": [443]},
        ],
        "bmc_candidates": [
            {"ip": bmc_ilo_ip, "bmc_kind": "ilo", "redfish_version": "1.6.0",
             "oem_hint": "HPE", "server_header": "HP-iLO-Server"},
            {"ip": bmc_idrac_ip, "bmc_kind": "idrac", "redfish_version": "1.11.0",
             "oem_hint": "Dell", "server_header": "iDRAC9"},
            {"ip": bmc_ipmi_ip, "bmc_kind": "ipmi", "redfish_version": "",
             "oem_hint": "Supermicro", "server_header": ""},
        ],
    }
    r = requests.post(
        f"{BASE_URL}/api/connector/network-discovery",
        json=payload,
        headers={"X-API-Key": test_client["api_key"]},
        timeout=15,
    )
    assert r.status_code == 200, f"network-discovery POST failed: {r.status_code} {r.text}"
    return {
        "ilo_ip": bmc_ilo_ip,
        "idrac_ip": bmc_idrac_ip,
        "ipmi_ip": bmc_ipmi_ip,
    }


# ---------- Tests ----------
class TestNetworkDiscoveryBMCPersistence:
    def test_network_discovery_with_bmc_returns_ok(self, test_client, post_bmc_payload):
        # The fixture already POSTed and asserted 200.
        assert post_bmc_payload["ilo_ip"] == "10.88.88.50"

    def test_bmc_candidates_persisted_in_network_discovery(self, test_client, post_bmc_payload, mongo_db):
        doc = mongo_db.network_discovery.find_one({"client_id": test_client["id"]})
        assert doc is not None
        assert "bmc_candidates" in doc
        bmcs = doc["bmc_candidates"]
        assert isinstance(bmcs, list) and len(bmcs) == 3
        kinds = sorted([b["bmc_kind"] for b in bmcs])
        assert kinds == ["idrac", "ilo", "ipmi"]

    def test_bmc_candidates_upserted_per_ip(self, test_client, post_bmc_payload, mongo_db):
        items = list(mongo_db.bmc_candidates.find(
            {"client_id": test_client["id"]}, {"_id": 0}
        ))
        ip_set = {i["ip"] for i in items}
        assert post_bmc_payload["ilo_ip"] in ip_set
        assert post_bmc_payload["idrac_ip"] in ip_set
        assert post_bmc_payload["ipmi_ip"] in ip_set

        for it in items:
            assert it.get("client_id") == test_client["id"]
            assert it.get("dismissed") is False
            assert it.get("first_seen")
            assert it.get("last_seen")
            assert it.get("bmc_kind") in ("ilo", "idrac", "ipmi")

    def test_discovered_endpoints_enriched_with_bmc(self, test_client, post_bmc_payload, mongo_db):
        eps = list(mongo_db.discovered_endpoints.find(
            {"client_id": test_client["id"]}, {"_id": 0}
        ))
        by_ip = {e.get("ip"): e for e in eps if e.get("ip")}
        ilo = by_ip.get(post_bmc_payload["ilo_ip"])
        idrac = by_ip.get(post_bmc_payload["idrac_ip"])
        ipmi = by_ip.get(post_bmc_payload["ipmi_ip"])
        assert ilo and ilo.get("bmc_kind") == "ilo"
        assert ilo.get("bmc_version") == "1.6.0"
        assert idrac and idrac.get("bmc_kind") == "idrac"
        assert idrac.get("bmc_version") == "1.11.0"
        assert ipmi and ipmi.get("bmc_kind") == "ipmi"

    def test_idempotent_upsert_no_duplicates(self, test_client, post_bmc_payload, mongo_db):
        """Re-POST con stesso payload (full) non deve creare duplicati di bmc_candidates."""
        before = mongo_db.bmc_candidates.count_documents({"client_id": test_client["id"]})
        switch_ip = test_client["switch_ip"]
        # Re-post FULL payload to keep discovered_endpoints intact for downstream tests
        payload = {
            "mac_tables": [
                {
                    "switch_ip": switch_ip,
                    "entries": [
                        {"mac": "AA:BB:CC:11:11:01", "port": 1, "vlan": "20", "ip": post_bmc_payload["ilo_ip"]},
                        {"mac": "AA:BB:CC:11:11:02", "port": 2, "vlan": "20", "ip": post_bmc_payload["idrac_ip"]},
                        {"mac": "AA:BB:CC:11:11:03", "port": 3, "vlan": "20", "ip": post_bmc_payload["ipmi_ip"]},
                    ],
                }
            ],
            "device_macs": [
                {"ip": post_bmc_payload["ilo_ip"], "macs": ["AA:BB:CC:11:11:01"]},
                {"ip": post_bmc_payload["idrac_ip"], "macs": ["AA:BB:CC:11:11:02"]},
                {"ip": post_bmc_payload["ipmi_ip"], "macs": ["AA:BB:CC:11:11:03"]},
            ],
            "ip_port_probes": [
                {"ip": post_bmc_payload["ilo_ip"], "ports": [443]},
                {"ip": post_bmc_payload["idrac_ip"], "ports": [443]},
                {"ip": post_bmc_payload["ipmi_ip"], "ports": [443]},
            ],
            "bmc_candidates": [
                {"ip": post_bmc_payload["ilo_ip"], "bmc_kind": "ilo", "redfish_version": "1.6.0"},
                {"ip": post_bmc_payload["idrac_ip"], "bmc_kind": "idrac", "redfish_version": "1.11.0"},
                {"ip": post_bmc_payload["ipmi_ip"], "bmc_kind": "ipmi", "redfish_version": ""},
            ],
        }
        r = requests.post(
            f"{BASE_URL}/api/connector/network-discovery", json=payload,
            headers={"X-API-Key": test_client["api_key"]}, timeout=15,
        )
        assert r.status_code == 200
        after = mongo_db.bmc_candidates.count_documents({"client_id": test_client["id"]})
        assert after == before, f"upsert duplicated rows: {before} -> {after}"


class TestBMCCandidatesAdminAPI:
    def test_list_requires_jwt(self, test_client):
        r = requests.get(f"{BASE_URL}/api/bmc-candidates", timeout=10)
        assert r.status_code in (401, 403), f"expected 401/403 without JWT, got {r.status_code}"

    def test_list_returns_items_enriched(self, test_client, post_bmc_payload, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/bmc-candidates",
            params={"client_id": test_client["id"]},
            headers=admin_headers,
            timeout=10,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "items" in data and "count" in data
        items = data["items"]
        assert data["count"] == len(items)
        assert len(items) >= 3
        ips = {i["ip"] for i in items}
        assert post_bmc_payload["ilo_ip"] in ips
        # Enrichment: switch_ip and switch_port from discovered_endpoints
        ilo_item = next(i for i in items if i["ip"] == post_bmc_payload["ilo_ip"])
        assert ilo_item.get("switch_ip") == test_client["switch_ip"]
        assert ilo_item.get("switch_port") in (1, 2, 3)
        assert ilo_item.get("mac")
        assert "vlan" in ilo_item

    def test_dismiss_hides_candidate(self, test_client, post_bmc_payload, admin_headers, mongo_db):
        ip = post_bmc_payload["ipmi_ip"]
        r = requests.post(
            f"{BASE_URL}/api/bmc-candidates/{test_client['id']}/{ip}/dismiss",
            headers=admin_headers, timeout=10,
        )
        assert r.status_code == 200, r.text
        assert r.json().get("status") == "ok"
        # Verify db
        doc = mongo_db.bmc_candidates.find_one({"client_id": test_client["id"], "ip": ip})
        assert doc and doc.get("dismissed") is True
        # Verify GET no longer returns it
        r2 = requests.get(
            f"{BASE_URL}/api/bmc-candidates",
            params={"client_id": test_client["id"]},
            headers=admin_headers, timeout=10,
        )
        assert r2.status_code == 200
        ips_returned = {i["ip"] for i in r2.json()["items"]}
        assert ip not in ips_returned

    def test_dismiss_unknown_returns_404(self, test_client, admin_headers):
        r = requests.post(
            f"{BASE_URL}/api/bmc-candidates/{test_client['id']}/9.9.9.9/dismiss",
            headers=admin_headers, timeout=10,
        )
        assert r.status_code == 404

    def test_import_creates_device(self, test_client, post_bmc_payload, admin_headers, mongo_db):
        ip = post_bmc_payload["ilo_ip"]
        r = requests.post(
            f"{BASE_URL}/api/bmc-candidates/{test_client['id']}/{ip}/import",
            headers=admin_headers, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("status") == "imported"
        device_id = body.get("device_id")
        assert device_id
        # Device record
        dev = mongo_db.devices.find_one({"id": device_id}, {"_id": 0})
        assert dev is not None
        assert dev.get("device_type") == "server"
        assert dev.get("redfish_enabled") is True
        assert dev.get("created_via") == "bmc_auto_discovery"
        assert dev.get("bmc_kind") == "ilo"
        assert dev.get("ip_address") == ip
        assert dev.get("client_id") == test_client["id"]
        # Candidate marcato come dismissed
        cand = mongo_db.bmc_candidates.find_one({"client_id": test_client["id"], "ip": ip})
        assert cand and cand.get("dismissed") is True
        assert cand.get("imported_as") == device_id

    def test_reimport_returns_already_exists(self, test_client, post_bmc_payload, admin_headers):
        ip = post_bmc_payload["ilo_ip"]
        r = requests.post(
            f"{BASE_URL}/api/bmc-candidates/{test_client['id']}/{ip}/import",
            headers=admin_headers, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("status") == "already_exists"
        assert body.get("device_id")

    def test_import_unknown_returns_404(self, test_client, admin_headers):
        r = requests.post(
            f"{BASE_URL}/api/bmc-candidates/{test_client['id']}/8.8.8.8/import",
            headers=admin_headers, timeout=10,
        )
        assert r.status_code == 404


class TestGuessEndpointTypeBMC:
    """Unit-level test of _guess_endpoint_type with bmc_kind parameter."""

    def test_bmc_kind_ilo_classifies_as_server(self):
        from routes.topology import _guess_endpoint_type
        assert _guess_endpoint_type(hostname="", mac="", listening_ports=[443], bmc_kind="ilo") == "server"

    def test_bmc_kind_idrac_classifies_as_server(self):
        from routes.topology import _guess_endpoint_type
        assert _guess_endpoint_type(hostname="", mac="", listening_ports=[443], bmc_kind="idrac") == "server"

    def test_bmc_kind_ipmi_classifies_as_server(self):
        from routes.topology import _guess_endpoint_type
        assert _guess_endpoint_type(hostname="", mac="", listening_ports=[443], bmc_kind="ipmi") == "server"

    def test_bmc_kind_xcc_classifies_as_server(self):
        from routes.topology import _guess_endpoint_type
        assert _guess_endpoint_type(hostname="", mac="", listening_ports=[443], bmc_kind="xcc") == "server"

    def test_bmc_kind_redfish_generic_classifies_as_server(self):
        from routes.topology import _guess_endpoint_type
        assert _guess_endpoint_type(hostname="", mac="", listening_ports=[443], bmc_kind="redfish_generic") == "server"

    def test_bmc_kind_takes_priority_over_other_signals(self):
        """Anche con hostname 'printer' e porte 9100, BMC vince sempre."""
        from routes.topology import _guess_endpoint_type
        assert _guess_endpoint_type(
            hostname="printer-foo", mac="00:11:22:33:44:55",
            listening_ports=[9100, 443], bmc_kind="ilo"
        ) == "server"

    def test_no_bmc_kind_falls_back_to_v3_6_13_behavior(self):
        """bmc_kind vuoto: deve mantenere il comportamento v3.6.13."""
        from routes.topology import _guess_endpoint_type
        # Solo 9100 -> printer
        assert _guess_endpoint_type(hostname="", mac="", listening_ports=[9100], bmc_kind="") == "printer"
        # 3389 -> server (Windows RDP)
        assert _guess_endpoint_type(hostname="", mac="", listening_ports=[3389], bmc_kind="") == "server"
        # 22+443 -> server
        assert _guess_endpoint_type(hostname="", mac="", listening_ports=[22, 443], bmc_kind="") == "server"

    def test_empty_bmc_kind_with_443_only_not_server(self):
        """Solo 443 senza BMC -> NON server (regressione)."""
        from routes.topology import _guess_endpoint_type
        result = _guess_endpoint_type(hostname="", mac="", listening_ports=[443], bmc_kind="")
        assert result != "server"


class TestLegacyPayloadRegression:
    """POST senza bmc_candidates deve continuare a funzionare."""

    def test_legacy_payload_no_bmc_candidates(self, test_client):
        switch_ip = test_client["switch_ip"]
        payload = {
            "mac_tables": [{
                "switch_ip": switch_ip,
                "entries": [{"mac": "AA:BB:CC:99:99:99", "port": 5, "vlan": "30"}],
            }],
            "device_macs": [],
            "ip_port_probes": [{"ip": "10.88.88.200", "ports": [22]}],
        }
        r = requests.post(
            f"{BASE_URL}/api/connector/network-discovery",
            json=payload,
            headers={"X-API-Key": test_client["api_key"]},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        assert r.json().get("status") == "ok"

    def test_completely_minimal_payload(self, test_client):
        r = requests.post(
            f"{BASE_URL}/api/connector/network-discovery",
            json={"mac_tables": [], "device_macs": []},
            headers={"X-API-Key": test_client["api_key"]},
            timeout=15,
        )
        assert r.status_code == 200, r.text
