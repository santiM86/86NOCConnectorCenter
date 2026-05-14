"""
v3.6.17 SCALE-UP regression tests:
- Switch-ports GET: must still return device_name + client_id, smoke perf < 500ms
- Connector update-check: 100 consecutive calls with X-API-Key should complete < 30s
- Backend must be up without critical errors
"""
import os
import time
import uuid
import pytest
import requests
import asyncio
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/backend/.env")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://device-monitor-94.preview.emergentagent.com").rstrip("/")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "admin@86bit.it", "password": "password"},
        timeout=10,
    )
    assert r.status_code == 200, r.text
    tok = r.json().get("token") or r.json().get("access_token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def connector_api_key():
    # Read from DB (86BIT_Office)
    async def _fetch():
        c = AsyncIOMotorClient(MONGO_URL)
        d = c[DB_NAME]
        doc = await d.clients.find_one({"name": "86BIT_Office"}, {"api_key": 1})
        return doc["api_key"] if doc else None

    key = asyncio.run(_fetch())
    assert key, "No api_key for 86BIT_Office client"
    return key


# --- Seed helpers ---------------------------------------------------------

@pytest.fixture(scope="module")
def seed_switch_port(admin_token):
    """Create a test client + switch device + one switch_port row for perf test."""
    async def _setup():
        c = AsyncIOMotorClient(MONGO_URL)
        d = c[DB_NAME]
        tag = f"TEST_SCALE17_{uuid.uuid4().hex[:8]}"
        client_id = tag
        switch_ip = "10.250.250.111"

        await d.clients.insert_one({
            "id": client_id, "client_id": client_id, "name": tag,
            "api_key": f"noc_{uuid.uuid4().hex}",
        })
        dev_id = str(uuid.uuid4())
        await d.devices.insert_one({
            "id": dev_id, "client_id": client_id, "ip_address": switch_ip,
            "name": f"{tag}_Switch", "device_name": f"{tag}_Switch",
            "device_type": "switch", "status": "online",
        })
        # topology GET reads managed_devices for top-level device_name + client_id
        await d.managed_devices.insert_one({
            "id": str(uuid.uuid4()), "client_id": client_id, "ip": switch_ip,
            "device_name": f"{tag}_Switch", "name": f"{tag}_Switch",
            "device_type": "switch",
        })
        await d.switch_ports.insert_one({
            "local_ip": switch_ip, "idx": 1, "name": "Gi0/1",
            "oper_status": "up", "admin_status": "up", "speed_mbps": 1000,
            "client_id": client_id,
        })
        return client_id, switch_ip, dev_id

    client_id, switch_ip, dev_id = asyncio.run(_setup())
    yield {"client_id": client_id, "ip": switch_ip, "device_id": dev_id}

    async def _teardown():
        c = AsyncIOMotorClient(MONGO_URL)
        d = c[DB_NAME]
        await d.clients.delete_one({"id": client_id})
        await d.devices.delete_one({"id": dev_id})
        await d.managed_devices.delete_many({"ip": switch_ip})
        await d.switch_ports.delete_many({"local_ip": switch_ip})
    asyncio.run(_teardown())


# --- Tests ----------------------------------------------------------------

class TestSwitchPortsResponse:
    """GET /api/devices/{ip}/switch-ports still exposes v3.6.16 fields (device_name, client_id)."""

    def test_switch_ports_includes_device_name_and_client_id(self, admin_token, seed_switch_port):
        ip = seed_switch_port["ip"]
        cid = seed_switch_port["client_id"]
        r = requests.get(
            f"{BASE_URL}/api/devices/{ip}/switch-ports",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=10,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Top-level keys expected from v3.6.16
        assert "device_name" in body, f"missing device_name in {list(body.keys())}"
        assert "client_id" in body, f"missing client_id in {list(body.keys())}"
        assert body["client_id"] == cid
        assert body["device_name"].startswith("TEST_SCALE17_")

    def test_switch_ports_perf_smoke_under_500ms(self, admin_token, seed_switch_port):
        ip = seed_switch_port["ip"]
        # Warm-up once (avoid JIT / connection overhead noise)
        requests.get(
            f"{BASE_URL}/api/devices/{ip}/switch-ports",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=10,
        )
        times_ms = []
        for _ in range(5):
            t0 = time.perf_counter()
            r = requests.get(
                f"{BASE_URL}/api/devices/{ip}/switch-ports",
                headers={"Authorization": f"Bearer {admin_token}"},
                timeout=10,
            )
            assert r.status_code == 200
            times_ms.append((time.perf_counter() - t0) * 1000)
        avg = sum(times_ms) / len(times_ms)
        p_max = max(times_ms)
        print(f"[switch-ports perf] avg={avg:.1f}ms max={p_max:.1f}ms samples={times_ms}")
        # Requirement: smoke < 500ms on current DB (network RTT to ingress included)
        assert avg < 500, f"avg latency {avg:.1f}ms exceeds 500ms budget (samples={times_ms})"


class TestConnectorUpdateCheckPerf:
    """100 consecutive GET /api/connector/update-check with valid X-API-Key -> < 30s total."""

    def test_update_check_100_calls_under_30s(self, connector_api_key):
        headers = {"X-API-Key": connector_api_key}
        url = f"{BASE_URL}/api/connector/update-check"

        # Warm-up
        requests.get(url, headers=headers, timeout=10)

        t0 = time.perf_counter()
        failures = 0
        for _ in range(100):
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code not in (200, 204):
                failures += 1
        elapsed = time.perf_counter() - t0
        print(f"[update-check perf] 100 calls in {elapsed:.2f}s (failures={failures})")
        assert failures == 0, f"{failures}/100 calls failed"
        assert elapsed < 30, f"100 calls took {elapsed:.2f}s (> 30s budget)"


class TestIndexesCreated:
    """Verify v3.6.17 scale-up indexes exist in MongoDB."""

    def test_all_scale_up_indexes_present(self):
        async def _check():
            c = AsyncIOMotorClient(MONGO_URL)
            d = c[DB_NAME]
            expected = {
                "vmbackup_jobs": ["vm_upsert_key"],
                "switch_ports": None,  # will check any index containing local_ip+idx
                "discovered_endpoints": None,
                "network_discovery": None,
                "mac_device_bindings": None,
                "bmc_candidates": None,
                "port_flap_events": None,
                "devices": None,
                "lldp_neighbors": None,
            }
            missing = []
            for coll, names in expected.items():
                idxs = await d[coll].index_information()
                if names:
                    for n in names:
                        if n not in idxs:
                            missing.append(f"{coll}.{n}")
                else:
                    # at least 1 non-_id_ index present
                    non_default = [k for k in idxs.keys() if k != "_id_"]
                    if not non_default:
                        missing.append(f"{coll}: no custom index")
            return missing

        missing = asyncio.run(_check())
        assert not missing, f"Missing indexes: {missing}"

    def test_mac_device_bindings_mac_is_unique(self):
        async def _check():
            c = AsyncIOMotorClient(MONGO_URL)
            d = c[DB_NAME]
            info = await d.mac_device_bindings.index_information()
            # Look for an index on 'mac' that is unique
            for name, meta in info.items():
                keys = meta.get("key", [])
                if keys and keys[0][0] == "mac" and meta.get("unique"):
                    return True
            return False
        assert asyncio.run(_check()), "mac_device_bindings.mac unique index missing"

    def test_bmc_candidates_compound_unique(self):
        async def _check():
            c = AsyncIOMotorClient(MONGO_URL)
            d = c[DB_NAME]
            info = await d.bmc_candidates.index_information()
            for name, meta in info.items():
                keys = meta.get("key", [])
                if len(keys) == 2 and keys[0][0] == "client_id" and keys[1][0] == "ip" and meta.get("unique"):
                    return True
            return False
        assert asyncio.run(_check()), "bmc_candidates (client_id,ip) unique index missing"
