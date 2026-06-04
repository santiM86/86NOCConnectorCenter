"""
Test: il poller Hornetsecurity NON deve crashare quando la credenziale cifrata
non è decifrabile col vault corrente. Deve marcare la config come
'vault_mismatch' e NON ritentare la decifrazione finché la chiave non
viene re-salvata dall'utente.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_global_tick_vault_mismatch_marks_status_without_crash():
    from services import hornetsecurity_poller as hp

    now = datetime.now(timezone.utc)
    fake_cfg = {
        "_id": hp.GLOBAL_CONFIG_ID,
        "enabled": True,
        "api_url": "https://api.example",
        "api_key_enc": "v2:CORRUPTED_BASE64",
        "poll_interval_minutes": 30,
        "last_polled_at": None,
    }

    update_one_mock = AsyncMock()
    find_one_mock = AsyncMock(return_value=fake_cfg)

    with patch.object(hp.db, "hornetsecurity_global_config",
                      MagicMock(find_one=find_one_mock, update_one=update_one_mock)), \
         patch.object(hp.security_manager, "decrypt_credential",
                      side_effect=ValueError("Decryption failed: bad tag")), \
         patch.object(hp, "_fetch_backup_report", new=AsyncMock()) as fetch_mock:
        # Non deve sollevare
        await hp._tick_global(now)

        # _fetch_backup_report NON deve essere chiamato se la decryption fallisce
        fetch_mock.assert_not_called()

        # update_one deve essere chiamato con status vault_mismatch
        assert update_one_mock.await_count == 1
        args, kwargs = update_one_mock.await_args
        payload = args[1]["$set"] if len(args) > 1 else kwargs["update"]["$set"]
        assert payload["last_poll_status"] == "vault_mismatch"
        assert "Decryption failed" in payload["last_poll_error"]


@pytest.mark.asyncio
async def test_per_client_tick_vault_mismatch_skips_client_without_crash():
    from services import hornetsecurity_poller as hp

    now = datetime.now(timezone.utc)
    fake_cfg = {
        "client_id": "client-xyz",
        "enabled": True,
        "api_url": "https://api.example",
        "api_key_enc": "v2:CORRUPTED",
        "poll_interval_minutes": 30,
        "last_polled_at": None,
    }

    class _AsyncIter:
        def __init__(self, items): self._items = list(items)
        def __aiter__(self): return self
        async def __anext__(self):
            if not self._items:
                raise StopAsyncIteration
            return self._items.pop(0)

    update_one_mock = AsyncMock()
    coll_mock = MagicMock()
    coll_mock.find = MagicMock(return_value=_AsyncIter([fake_cfg]))
    coll_mock.update_one = update_one_mock

    with patch.object(hp.db, "hornetsecurity_configs", coll_mock), \
         patch.object(hp.security_manager, "decrypt_credential",
                      side_effect=ValueError("Decryption failed: bad tag")), \
         patch.object(hp, "_fetch_backup_report", new=AsyncMock()) as fetch_mock:
        await hp._tick_per_client(now)
        fetch_mock.assert_not_called()
        assert update_one_mock.await_count == 1
        args, kwargs = update_one_mock.await_args
        payload = args[1]["$set"] if len(args) > 1 else kwargs["update"]["$set"]
        assert payload["last_poll_status"] == "vault_mismatch"
