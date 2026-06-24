"""Regressione: il poller VM Backup NON deve crashare quando la chiave AES-GCM
e' stata ruotata (decrypt fallisce con InvalidTag).

Prima del fix il job apscheduler crashava ogni minuto loggando un traceback
completo (`cryptography.exceptions.InvalidTag` → `ValueError: Decryption failed`)
inquinando i log di produzione.

Dopo il fix:
  - status diventa "vault_mismatch"
  - enabled viene messo a False (il job smette di provare)
  - return value contiene "vault_mismatch" e l'istruzione di re-save
"""
import sys
import asyncio
import importlib
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

# Ensure backend/ importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.mark.asyncio
async def test_vmbackup_tick_handles_vault_mismatch_gracefully():
    """run_vmbackup_tick non solleva eccezioni quando decrypt fallisce."""
    from services import hornetsecurity_vmbackup_poller as poller

    fake_cfg = {
        "_id": poller.GLOBAL_CONFIG_ID,
        "api_url": "https://example/api",
        "user_id": "u1",
        "api_key_enc": "v2:somecorruptedciphertext",
        "polling_interval_minutes": 10,
        "enabled": True,
    }

    # Mock db
    update_mock = AsyncMock()
    fake_db = MagicMock()
    fake_db.hornetsecurity_vmbackup_config.find_one = AsyncMock(return_value=fake_cfg)
    fake_db.hornetsecurity_vmbackup_config.update_one = update_mock

    # Mock decrypt to raise (vault rotated)
    fake_sm = MagicMock()
    fake_sm.decrypt_credential = MagicMock(side_effect=ValueError("InvalidTag"))

    with patch.object(poller, "db", fake_db), \
         patch.object(poller, "security_manager", fake_sm):
        result = await poller.run_vmbackup_tick(force=True)

    # 1) Nessuna eccezione propagata fuori dalla funzione
    # 2) Risposta strutturata con vault_mismatch
    assert isinstance(result, dict)
    assert "error" in result
    assert "vault_mismatch" in result["error"].lower()

    # 3) update_one chiamato 2 volte: una per status, una per enabled=False
    assert update_mock.await_count == 2

    # Primo update: status vault_mismatch
    first_call = update_mock.await_args_list[0]
    set_doc_1 = first_call.args[1]["$set"]
    assert set_doc_1["last_poll_status"] == "vault_mismatch"
    assert "Re-save the API key" in set_doc_1["last_poll_error"]

    # Secondo update: enabled=False
    second_call = update_mock.await_args_list[1]
    set_doc_2 = second_call.args[1]["$set"]
    assert set_doc_2["enabled"] is False
