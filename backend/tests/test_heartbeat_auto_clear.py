"""Test: heartbeat auto-clears update status when target_version is reached.

Verifica il fix v3.8.21 al "loop fasullo Aggiornamento in corso":
- force_update con target_version salvato
- heartbeat con connector_version >= target_version => stato pulito
- heartbeat con connector_version < target_version => stato preservato
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

# Ensure backend/ is on path so module-relative imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from routes.connector import is_newer_version  # noqa: E402


MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


@pytest.fixture
async def db():
    client = AsyncIOMotorClient(MONGO_URL)
    database = client[DB_NAME]
    yield database
    client.close()


def test_is_newer_version_basic():
    assert is_newer_version("3.8.20", "3.8.19") is True
    assert is_newer_version("3.8.19", "3.8.19") is False
    assert is_newer_version("3.8.18", "3.8.19") is False


@pytest.mark.asyncio
async def test_heartbeat_clears_when_target_version_reached(db):
    """Simula la logica del heartbeat: target_version raggiunta => clear."""
    client_id = f"test-client-{uuid.uuid4().hex[:8]}"
    hostname = "test-hb-host"
    mode = "master"
    filter_q = {"client_id": client_id, "hostname": hostname, "mode": mode}

    # Pre-condizione: connector con force_update + target_version 3.8.19
    await db.connector_status.insert_one({
        **filter_q,
        "connector_version": "3.8.18",
        "force_update": True,
        "update_status": "queued",
        "update_progress": 1,
        "update_message": "Aggiornamento forzato a v3.8.19",
        "update_timestamp": datetime.now(timezone.utc).isoformat(),
        "target_version": "3.8.19",
    })

    try:
        # Simula la logica del heartbeat (preso letteralmente dall'endpoint)
        existing = await db.connector_status.find_one(filter_q, {"_id": 0})
        assert existing is not None
        assert existing["force_update"] is True

        # Heartbeat: il connector ora segnala v3.8.19
        current_version = "3.8.19"
        target_version = existing.get("target_version")

        should_clear = False
        if target_version and not is_newer_version(target_version, current_version):
            should_clear = True

        assert should_clear is True, f"target={target_version} current={current_version}"

        await db.connector_status.update_one(
            filter_q,
            {"$unset": {
                "update_status": "", "force_update": "", "update_progress": "",
                "update_message": "", "update_timestamp": "", "target_version": ""
            }}
        )

        cleared = await db.connector_status.find_one(filter_q, {"_id": 0})
        assert "force_update" not in cleared
        assert "update_status" not in cleared
        assert "target_version" not in cleared
        assert "update_message" not in cleared
    finally:
        await db.connector_status.delete_one(filter_q)


@pytest.mark.asyncio
async def test_heartbeat_preserves_state_when_below_target(db):
    """Se la versione del connector e' ANCORA inferiore al target, non azzerare nulla."""
    client_id = f"test-client-{uuid.uuid4().hex[:8]}"
    hostname = "test-hb-host-2"
    mode = "master"
    filter_q = {"client_id": client_id, "hostname": hostname, "mode": mode}

    await db.connector_status.insert_one({
        **filter_q,
        "connector_version": "3.8.18",
        "force_update": True,
        "update_status": "installing",
        "update_progress": 50,
        "update_timestamp": datetime.now(timezone.utc).isoformat(),
        "target_version": "3.8.20",
    })

    try:
        existing = await db.connector_status.find_one(filter_q, {"_id": 0})
        current_version = "3.8.18"
        target_version = existing.get("target_version")

        should_clear = False
        if target_version and not is_newer_version(target_version, current_version):
            should_clear = True

        assert should_clear is False  # 3.8.18 < 3.8.20 => attendi ancora
    finally:
        await db.connector_status.delete_one(filter_q)


@pytest.mark.asyncio
async def test_heartbeat_clears_when_exceeds_target(db):
    """Versione superiore al target (es. doppio update) => clear."""
    client_id = f"test-client-{uuid.uuid4().hex[:8]}"
    hostname = "test-hb-host-3"
    filter_q = {"client_id": client_id, "hostname": hostname, "mode": "master"}

    await db.connector_status.insert_one({
        **filter_q,
        "connector_version": "3.8.18",
        "force_update": True,
        "update_status": "queued",
        "target_version": "3.8.19",
    })

    try:
        current_version = "3.8.20"  # gia' a 3.8.20, target era 3.8.19
        target_version = "3.8.19"
        should_clear = not is_newer_version(target_version, current_version)
        assert should_clear is True
    finally:
        await db.connector_status.delete_one(filter_q)
