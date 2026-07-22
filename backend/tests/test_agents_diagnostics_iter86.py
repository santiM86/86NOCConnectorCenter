"""v4.18.x: tests for GET /api/agents/diagnostics + ping_poll upsert filter fix.

Run with:
    cd /app/backend && set -a && source .env && set +a && \
        python3 -m pytest tests/test_agents_diagnostics_iter86.py -v
"""
import os
import asyncio
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # backend/.env doesn't carry the FE url, fall back to the well-known value
    BASE_URL = "https://noc-monitor-4.preview.emergentagent.com"

ADMIN_EMAIL = "info@86bit.it"
ADMIN_PASSWORD = "Ariel17051986@!@86"


@pytest.fixture(scope="module")
def admin_token() -> str:
    """Login as admin and return bearer token."""
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    tok = data.get("access_token") or data.get("token")
    assert tok, f"no token in login response: {data}"
    return tok


@pytest.fixture(scope="module")
def admin_headers(admin_token: str) -> dict:
    return {"Authorization": f"Bearer {admin_token}"}


# ---- Auth gating on /api/agents/diagnostics --------------------------------
class TestDiagnosticsAuth:
    def test_no_token_rejected(self):
        r = requests.get(f"{BASE_URL}/api/agents/diagnostics", timeout=10)
        assert r.status_code in (401, 403), (
            f"expected 401/403 without token, got {r.status_code}"
        )

    def test_invalid_token_rejected(self):
        r = requests.get(
            f"{BASE_URL}/api/agents/diagnostics",
            headers={"Authorization": "Bearer not-a-real-token"},
            timeout=10,
        )
        assert r.status_code in (401, 403), (
            f"expected 401/403 with bad token, got {r.status_code}"
        )


# ---- Shape of the diagnostics response -------------------------------------
class TestDiagnosticsShape:
    def test_basic_shape(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/agents/diagnostics",
            headers=admin_headers,
            timeout=20,
        )
        assert r.status_code == 200, f"got {r.status_code}: {r.text}"
        data = r.json()
        # Top-level
        assert isinstance(data, dict)
        for k in ("agents", "live_count", "total_count"):
            assert k in data, f"missing top-level field {k}"
        assert isinstance(data["agents"], list)
        assert isinstance(data["live_count"], int)
        assert isinstance(data["total_count"], int)
        assert data["total_count"] == len(data["agents"])
        assert data["live_count"] <= data["total_count"]
        # Per-agent fields
        required = [
            "agent_id", "client_id", "hostname", "role", "live",
            "connected_db", "last_snmp_poll_received_at",
            "last_ping_poll_received_at", "last_discovery_received_at",
            "bridge_counters", "poller_config",
        ]
        for ag in data["agents"]:
            for k in required:
                assert k in ag, (
                    f"agent missing field {k} (agent_id={ag.get('agent_id')})"
                )
            # bridge_counters must be a dict (possibly empty)
            assert isinstance(ag["bridge_counters"], dict), (
                f"bridge_counters not dict for {ag.get('agent_id')}"
            )
            # poller_config must be a dict containing both target counts
            pc = ag["poller_config"]
            assert isinstance(pc, dict)
            assert "snmp_targets" in pc and "ping_targets" in pc
            assert isinstance(pc["snmp_targets"], int)
            assert isinstance(pc["ping_targets"], int)

    def test_client_id_filter(self, admin_headers):
        """client_id filter must shrink (or keep equal) the result set."""
        r_all = requests.get(
            f"{BASE_URL}/api/agents/diagnostics",
            headers=admin_headers,
            timeout=15,
        ).json()
        if not r_all["agents"]:
            pytest.skip("no agents in DB - cannot test client_id filter")
        cid = r_all["agents"][0]["client_id"]
        if not cid:
            pytest.skip("first agent has no client_id")
        r_f = requests.get(
            f"{BASE_URL}/api/agents/diagnostics",
            params={"client_id": cid},
            headers=admin_headers,
            timeout=15,
        )
        assert r_f.status_code == 200
        for ag in r_f.json()["agents"]:
            assert ag["client_id"] == cid


# ---- Regression: /api/agents still returns list ----------------------------
class TestAgentsRegression:
    def test_list_agents(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/agents", headers=admin_headers, timeout=15
        )
        assert r.status_code == 200
        body = r.json()
        # Endpoint may return either a list or {"agents": [...]} — accept both
        items = body if isinstance(body, list) else body.get("agents")
        assert isinstance(items, list)


# ---- Regression: /api/devices still works ----------------------------------
class TestDevicesRegression:
    def test_list_devices(self, admin_headers):
        r = requests.get(
            f"{BASE_URL}/api/devices", headers=admin_headers, timeout=20
        )
        assert r.status_code == 200, f"GET /api/devices -> {r.status_code}"
        body = r.json()
        items = body if isinstance(body, list) else body.get("devices") or body.get("items")
        assert isinstance(items, list), f"unexpected body: {type(body)}"


# ---- ping_poll filter fix (DB-level) ---------------------------------------
# Verifies that two _bridge_ping_poll invocations for the same (client_id,
# device_ip) but with DIFFERENT agent_id update the SAME row instead of
# crashing on a DuplicateKey.  This is the v4.18.x bug-fix.
class TestPingPollFilterFix:
    def test_two_agents_same_target_upserts_once(self):
        async def _run():
            from motor.motor_asyncio import AsyncIOMotorClient
            mongo_url = os.environ["MONGO_URL"]
            db_name = os.environ["DB_NAME"]
            client = AsyncIOMotorClient(mongo_url)
            db = client[db_name]

            cid = "TEST_ITER86_CLIENT"
            ip = "10.255.99.250"
            try:
                # Ensure clean slate
                await db.device_poll_status.delete_many(
                    {"client_id": cid, "device_ip": ip}
                )

                # Build a fake _Connection-like obj for the bridge.
                from routes.agent_ws import _bridge_ping_poll

                class _Conn:
                    def __init__(self, aid):
                        self.agent_id = aid
                        self.client_id = cid
                        self.last_ip = "127.0.0.1"

                # First ping_poll: agent A, reachable=True
                await _bridge_ping_poll(_Conn("AGENT_A"), {
                    "target": ip, "reachable": True,
                    "latency_ns": 1_500_000, "loss_pct": 0.0,
                })
                # Second ping_poll: agent B (different!), reachable=False
                await _bridge_ping_poll(_Conn("AGENT_B"), {
                    "target": ip, "reachable": False,
                    "latency_ns": 0, "loss_pct": 100.0, "error": "timeout",
                })

                docs = await db.device_poll_status.find(
                    {"client_id": cid, "device_ip": ip}
                ).to_list(length=10)

                # Exactly one row should exist (no DuplicateKey duplication)
                assert len(docs) == 1, (
                    f"expected 1 row after 2 agents pinging same target, "
                    f"got {len(docs)}: {docs}"
                )
                doc = docs[0]
                # Most recent agent_id should win (AGENT_B)
                assert doc.get("agent_id") == "AGENT_B", doc
                assert doc.get("ping_reachable") is False, doc
                assert doc.get("reachable") is False, doc  # legacy field
            finally:
                await db.device_poll_status.delete_many(
                    {"client_id": cid, "device_ip": ip}
                )
                client.close()

        asyncio.run(_run())
