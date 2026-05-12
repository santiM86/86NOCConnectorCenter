"""Unit tests for the live-polling pipeline introduced for the Go agent v4.

Covers:
  - `_build_poller_config` emits both `snmp` and `ping` blocks and the
    `ping.targets` list is the *union* of all enabled managed devices
    of the tenant (not only SNMP-eligible ones).
  - `_bridge_ping_poll` flips `managed_devices.status` to "offline" only
    after 3 consecutive failures and resets the counter on the next
    successful probe.
  - `push_config_to_client` returns 0 (no live agents) without raising
    when called on a tenant that has no WS session.

All scenarios run inside ONE async function on ONE event loop so the
shared `motor` client stays alive (function-scoped pytest-asyncio loops
would close it between cases).

Run from /app/backend:
    python -m pytest tests/test_agent_v4_live_polling.py -v
"""
import asyncio
import os
import uuid


MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


async def _build_tenant(db, cid: str):
    devices = [
        {"id": str(uuid.uuid4()), "client_id": cid, "ip": "10.0.0.1",
         "name": "core-switch", "device_type": "switch", "community": "public"},
        {"id": str(uuid.uuid4()), "client_id": cid, "ip": "10.0.0.2",
         "name": "fw", "device_type": "firewall"},
        {"id": str(uuid.uuid4()), "client_id": cid, "ip": "10.0.0.50",
         "name": "printer-hp", "device_type": "printer"},
        {"id": str(uuid.uuid4()), "client_id": cid, "ip": "10.0.0.99",
         "name": "windows-pc", "device_type": "workstation"},
        {"id": str(uuid.uuid4()), "client_id": cid, "ip": "10.0.0.200",
         "name": "disabled-host", "device_type": "switch", "disabled": True},
    ]
    for d in devices:
        await db.managed_devices.insert_one({**d, "_id": d["id"]})


async def _cleanup_tenant(db, cid: str):
    await db.managed_devices.delete_many({"client_id": cid})
    await db.device_poll_status.delete_many({"client_id": cid})


async def _scenario():
    from database import db
    from routes.agent_ws import _build_poller_config, _bridge_ping_poll, push_config_to_client

    cid = f"unit-poll-{uuid.uuid4().hex[:8]}"
    await _build_tenant(db, cid)
    try:
        # --- 1. _build_poller_config emits both blocks ----------------
        cfg = await _build_poller_config(cid)
        assert "snmp" in cfg and "ping" in cfg, cfg
        ping_ips = sorted(t["ip"] for t in cfg["ping"]["targets"])
        assert ping_ips == ["10.0.0.1", "10.0.0.2", "10.0.0.50", "10.0.0.99"], ping_ips
        assert cfg["ping"]["enabled"] is True
        assert cfg["ping"]["interval"] == "60s"
        snmp_ips = sorted(t["ip"] for t in cfg["snmp"]["targets"])
        assert snmp_ips == ["10.0.0.1", "10.0.0.2", "10.0.0.50"], snmp_ips
        assert cfg["snmp"]["enabled"] is True
        for blk in (cfg["snmp"]["targets"], cfg["ping"]["targets"]):
            assert all(t["ip"] != "10.0.0.200" for t in blk)
        print("[OK] _build_poller_config emits both blocks correctly")

        # --- 2. 3-consecutive-failure threshold ------------------------
        ip = "10.0.0.99"

        class FakeConn:
            agent_id = "agent-test"
            client_id = cid

        conn = FakeConn()

        await _bridge_ping_poll(conn, {
            "target": ip, "reachable": True, "latency_ns": 1_200_000,
        })
        dev = await db.managed_devices.find_one({"client_id": cid, "ip": ip}, {"_id": 0})
        assert dev["status"] == "online"
        assert dev["consecutive_ping_failures"] == 0

        await _bridge_ping_poll(conn, {"target": ip, "reachable": False})
        dev = await db.managed_devices.find_one({"client_id": cid, "ip": ip}, {"_id": 0})
        assert dev["consecutive_ping_failures"] == 1, dev
        assert dev["status"] == "online", dev["status"]
        assert dev.get("degraded") is True

        await _bridge_ping_poll(conn, {"target": ip, "reachable": False})
        dev = await db.managed_devices.find_one({"client_id": cid, "ip": ip}, {"_id": 0})
        assert dev["consecutive_ping_failures"] == 2
        assert dev["status"] == "online"

        await _bridge_ping_poll(conn, {"target": ip, "reachable": False, "error": "timeout"})
        dev = await db.managed_devices.find_one({"client_id": cid, "ip": ip}, {"_id": 0})
        assert dev["consecutive_ping_failures"] == 3
        assert dev["status"] == "offline", dev["status"]

        await _bridge_ping_poll(conn, {
            "target": ip, "reachable": True, "latency_ns": 800_000,
        })
        dev = await db.managed_devices.find_one({"client_id": cid, "ip": ip}, {"_id": 0})
        assert dev["consecutive_ping_failures"] == 0
        assert dev["status"] == "online"
        assert dev.get("degraded") is False

        ps = await db.device_poll_status.find_one({"client_id": cid, "ip": ip}, {"_id": 0})
        assert ps["ping_reachable"] is True
        assert abs(ps["ping_latency_ms"] - 0.8) < 0.05
        print("[OK] _bridge_ping_poll 3-failure threshold honoured")

        # --- 3. push_config_to_client with no live agents -------------
        notified = await push_config_to_client(cid)
        assert notified == 0
        print("[OK] push_config_to_client returns 0 with no live agents")

    finally:
        await _cleanup_tenant(db, cid)


def test_live_polling_pipeline():
    """Single sync entry-point; runs the whole async scenario."""
    asyncio.run(_scenario())
