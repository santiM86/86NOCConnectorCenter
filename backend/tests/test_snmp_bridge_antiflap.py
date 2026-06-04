"""
Test critico: il bridge SNMP deve azzerare `consecutive_ping_failures`
quando `reachable=True`, altrimenti il flapping ping-vs-snmp marca i
device ONLINE/OFFLINE in continuazione e la UI mostra device offline
nonostante poll SNMP freschi.

Ref: bug Zitac/Galvan 2026-06-04 — 38 device tutti offline con SNMP fresco.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_snmp_bridge_resets_ping_failure_counter_on_reachable():
    """Quando SNMP dice reachable=True deve scrivere status=online E
    azzerare consecutive_ping_failures (anti-flap)."""
    from routes import agent_ws

    captured = {}

    async def fake_update_many(filter_q, update_doc):
        captured["filter"] = filter_q
        captured["update"] = update_doc
        return MagicMock(matched_count=1, modified_count=1)

    async def fake_update_one(*args, **kwargs):
        return MagicMock(matched_count=1)

    conn = MagicMock()
    conn.client_id = "client-x"
    conn.agent_id = "agent-1"

    snmp_result = {
        "target": "10.0.0.1",
        "reachable": True,
        "sys_name": "switch1",
        "oids": {"cpu": 25},
    }

    with patch.object(agent_ws.db, "managed_devices", MagicMock(update_many=fake_update_many)), \
         patch.object(agent_ws.db, "device_poll_status", MagicMock(update_one=AsyncMock())), \
         patch.object(agent_ws.db, "managed_agents", MagicMock(update_one=AsyncMock())):
        await agent_ws._bridge_snmp_poll(conn, snmp_result)

    assert "update" in captured, "update_many non chiamato"
    set_doc = captured["update"]["$set"]
    assert set_doc.get("status") == "online", "SNMP reachable=True deve promuovere a online"
    assert set_doc.get("consecutive_ping_failures") == 0, (
        "BUG CRITICO: SNMP reachable=True DEVE azzerare consecutive_ping_failures, "
        "altrimenti il prossimo ping fallito ri-marca il device OFFLINE causando flapping."
    )
    assert set_doc.get("degraded") is False
    assert set_doc.get("last_seen_at") is not None


@pytest.mark.asyncio
async def test_snmp_bridge_does_not_touch_status_when_unreachable():
    """Quando SNMP dice reachable=False NON deve toccare status né counter
    (ping_poll resta autoritativo)."""
    from routes import agent_ws

    captured = {}

    async def fake_update_many(filter_q, update_doc):
        captured["update"] = update_doc
        return MagicMock(matched_count=1, modified_count=1)

    conn = MagicMock()
    conn.client_id = "client-x"
    conn.agent_id = "agent-1"

    snmp_result = {"target": "10.0.0.2", "reachable": False, "error": "timeout"}

    with patch.object(agent_ws.db, "managed_devices", MagicMock(update_many=fake_update_many)), \
         patch.object(agent_ws.db, "device_poll_status", MagicMock(update_one=AsyncMock())), \
         patch.object(agent_ws.db, "managed_agents", MagicMock(update_one=AsyncMock())):
        await agent_ws._bridge_snmp_poll(conn, snmp_result)

    set_doc = captured["update"]["$set"]
    assert "status" not in set_doc, "SNMP fallito non deve forzare status (ping autoritativo)"
    assert "consecutive_ping_failures" not in set_doc, "SNMP fallito non deve toccare counter ping"
    assert "last_seen_at" not in set_doc
    # ma snmp_last_check_at sì
    assert set_doc.get("snmp_last_check_at") is not None
    assert set_doc.get("snmp_reachable") is False
