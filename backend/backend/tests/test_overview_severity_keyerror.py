"""Regression test: overview endpoint deve gestire severity 'info' o sconosciute
senza crashare con KeyError.

Bug originale (v3.8.28): /api/overview/clients restituiva 500 Internal Server Error
quando un alert aveva severity == "info" (o qualsiasi valore diverso da
critical/high/medium/low). Il dict alerts_by_client[cid] veniva inizializzato solo
con quelle 4 chiavi + total.

Fix v3.8.29: aggiunta dinamica della chiave se la severity non e' nel dict.
"""
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure backend importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _make_async_cursor(items):
    cur = MagicMock()
    cur.to_list = AsyncMock(return_value=items)

    async def _aiter(self):
        for it in items:
            yield it

    cur.__aiter__ = _aiter
    return cur


@pytest.mark.asyncio
async def test_get_clients_overview_handles_info_severity(monkeypatch):
    from routes import overview as overview_mod

    # Fake DB with one client and one alert with severity "info"
    fake_clients = [{"id": "c1", "name": "Galvan"}]
    fake_alerts = [
        {"client_id": "c1", "severity": "info", "title": "test", "device_name": "dev1",
         "created_at": "2026-01-01T00:00:00+00:00", "id": "a1"},
        {"client_id": "c1", "severity": "critical", "title": "boom", "device_name": "dev2",
         "created_at": "2026-01-01T00:00:00+00:00", "id": "a2"},
        # severity null
        {"client_id": "c1", "severity": None, "title": "null sev", "device_name": "dev3",
         "created_at": "2026-01-01T00:00:00+00:00", "id": "a3"},
    ]

    fake_db = MagicMock()
    fake_db.clients.find = MagicMock(return_value=_make_async_cursor(fake_clients))
    fake_db.wan_targets.find = MagicMock(return_value=_make_async_cursor([]))
    fake_db.wan_probe_results.find = MagicMock(return_value=_make_async_cursor([]))
    fake_db.alerts.find = MagicMock(return_value=_make_async_cursor(fake_alerts))
    fake_db.devices.find = MagicMock(return_value=_make_async_cursor([]))
    fake_db.device_poll_status.find = MagicMock(return_value=_make_async_cursor([]))
    fake_db.managed_devices.find = MagicMock(return_value=_make_async_cursor([]))
    fake_db.discovered_endpoints.find = MagicMock(return_value=_make_async_cursor([]))
    fake_db.backup_status.find = MagicMock(return_value=_make_async_cursor([]))
    fake_db.backup_job_status.find = MagicMock(return_value=_make_async_cursor([]))
    fake_db.vmbackup_jobs.find = MagicMock(return_value=_make_async_cursor([]))
    fake_db.printers.find = MagicMock(return_value=_make_async_cursor([]))
    fake_db.connector_status.find = MagicMock(return_value=_make_async_cursor([]))

    monkeypatch.setattr(overview_mod, "db", fake_db)

    # Should NOT raise KeyError
    result = await overview_mod.get_clients_overview(current_user={"id": "admin", "role": "admin"})

    assert isinstance(result, dict)
    clients = result.get("clients") or []
    assert len(clients) == 1
    galvan = clients[0]
    assert galvan["name"] == "Galvan"
    alerts = galvan["alerts"]
    assert alerts["total"] == 3
    assert alerts["critical"] == 1
    # severity "info" e null vanno entrambe contate (info nel dynamic field, null normalized to low)
    assert alerts.get("info") == 1
    assert alerts["low"] == 1


if __name__ == "__main__":
    asyncio.run(test_get_clients_overview_handles_info_severity(pytest.MonkeyPatch()))
