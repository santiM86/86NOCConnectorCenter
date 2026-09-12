"""Regression test v3.8.29: PUT /api/external-monitor/targets/{id} permette di
riassegnare il client_id, modificare device_type/label/ip/porte. Valida client_id
esistente e device_type ammessi.
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.mark.asyncio
async def test_update_target_reassign_client(monkeypatch):
    from routes import external_monitor as em

    fake_db = MagicMock()
    fake_db.clients.find_one = AsyncMock(return_value={"id": "client-galvan"})
    fake_db.wan_targets.update_one = AsyncMock(return_value=MagicMock(matched_count=1))
    fake_db.wan_probe_results.update_many = AsyncMock(return_value=MagicMock(modified_count=1))
    monkeypatch.setattr(em, "db", fake_db)
    monkeypatch.setattr(em, "require_admin", lambda u: None)

    update = em.WanTargetUpdate(client_id="client-galvan", label="New Label")
    res = await em.update_target("target-1", update, current_user={"id": "u1", "email": "a@b"})
    assert res == {"status": "ok"}
    fake_db.wan_targets.update_one.assert_called_once()
    fake_db.wan_probe_results.update_many.assert_called_once()


@pytest.mark.asyncio
async def test_update_target_invalid_client(monkeypatch):
    from routes import external_monitor as em

    fake_db = MagicMock()
    fake_db.clients.find_one = AsyncMock(return_value=None)  # client non esiste
    monkeypatch.setattr(em, "db", fake_db)
    monkeypatch.setattr(em, "require_admin", lambda u: None)

    update = em.WanTargetUpdate(client_id="invalid-id")
    with pytest.raises(HTTPException) as exc:
        await em.update_target("target-1", update, current_user={"id": "u1", "email": "a@b"})
    assert exc.value.status_code == 400
    assert "Cliente non trovato" in exc.value.detail


@pytest.mark.asyncio
async def test_update_target_invalid_device_type(monkeypatch):
    from routes import external_monitor as em

    fake_db = MagicMock()
    monkeypatch.setattr(em, "db", fake_db)
    monkeypatch.setattr(em, "require_admin", lambda u: None)

    update = em.WanTargetUpdate(device_type="INVALID")
    with pytest.raises(HTTPException) as exc:
        await em.update_target("target-1", update, current_user={"id": "u1", "email": "a@b"})
    assert exc.value.status_code == 400
    assert "device_type" in exc.value.detail


@pytest.mark.asyncio
async def test_update_target_label_only_does_not_touch_probe_results(monkeypatch):
    from routes import external_monitor as em

    fake_db = MagicMock()
    fake_db.wan_targets.update_one = AsyncMock(return_value=MagicMock(matched_count=1))
    fake_db.wan_probe_results.update_many = AsyncMock()
    monkeypatch.setattr(em, "db", fake_db)
    monkeypatch.setattr(em, "require_admin", lambda u: None)

    update = em.WanTargetUpdate(label="only label")
    res = await em.update_target("target-1", update, current_user={"id": "u1", "email": "a@b"})
    assert res == {"status": "ok"}
    fake_db.wan_probe_results.update_many.assert_not_called()
