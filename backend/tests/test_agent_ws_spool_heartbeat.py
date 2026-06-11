"""
Test: _on_heartbeat persiste anche i nuovi campi spool_* (v4.23 store-and-forward)
nel documento managed_agents. La UI Connector legge questi per rendere lo
stato del buffer locale (frames pending, dropped, oldest).
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_on_heartbeat_persists_spool_fields():
    from routes import agent_ws as aw

    conn = MagicMock()
    conn.agent_id = "agent-abc"

    update_one_mock = AsyncMock()

    hb_payload = {
        "uptime_ns": 12345,
        "goroutines": 10,
        "mem_alloc_bytes": 200000,
        "cpu_percent": 1.2,
        "errors_last_5min": 0,
        "modules_alive": ["snmp", "ping"],
        "modules_stuck": [],
        "last_scan_at": "2026-06-11T10:00:00Z",
        "last_poll_at": "2026-06-11T10:01:00Z",
        # v4.23 fields
        "spool_depth": 42,
        "spool_oldest_at": "2026-06-11T09:55:00Z",
        "spool_dropped_total": 3,
        "spool_acked_total": 1500,
    }

    with patch.object(aw.db, "managed_agents", MagicMock(update_one=update_one_mock)):
        await aw._on_heartbeat(conn, hb_payload)

    assert update_one_mock.await_count == 1
    args, kwargs = update_one_mock.await_args
    update_doc = args[1]["$set"] if len(args) > 1 else kwargs["update"]["$set"]

    # legacy fields still present
    assert update_doc["uptime_ns"] == 12345
    assert update_doc["modules_alive"] == ["snmp", "ping"]

    # v4.23 spool fields
    assert update_doc["spool_depth"] == 42
    assert update_doc["spool_oldest_at"] == "2026-06-11T09:55:00Z"
    assert update_doc["spool_dropped_total"] == 3
    assert update_doc["spool_acked_total"] == 1500


@pytest.mark.asyncio
async def test_on_heartbeat_defaults_when_spool_fields_missing():
    """Legacy agent (v4.22) non manda spool_*: i campi devono essere
    persistiti come 0/None invece di crashare con KeyError."""
    from routes import agent_ws as aw

    conn = MagicMock()
    conn.agent_id = "agent-legacy"
    update_one_mock = AsyncMock()

    hb_payload = {  # no spool_* keys (v4.22)
        "uptime_ns": 12345,
        "goroutines": 5,
        "modules_alive": ["snmp"],
    }

    with patch.object(aw.db, "managed_agents", MagicMock(update_one=update_one_mock)):
        await aw._on_heartbeat(conn, hb_payload)

    args, kwargs = update_one_mock.await_args
    update_doc = args[1]["$set"] if len(args) > 1 else kwargs["update"]["$set"]

    assert update_doc["spool_depth"] == 0
    assert update_doc["spool_oldest_at"] is None
    assert update_doc["spool_dropped_total"] == 0
    assert update_doc["spool_acked_total"] == 0
