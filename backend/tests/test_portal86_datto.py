"""Test di regressione per /api/portal86-datto integration.

Copre:
  - encrypt/decrypt round-trip delle credenziali
  - vault_mismatch tolerance se la chiave AES-GCM e' ruotata
  - _load_decrypted_config solleva HTTPException chiaro su decrypt fail
  - _fetch_sites parsa correttamente la risposta upstream

Non chiama portal.86bit.it: tutti i client HTTP sono mockati.
"""
import sys
import asyncio
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.mark.asyncio
async def test_load_config_raises_vault_mismatch_on_decrypt_failure():
    """Se decrypt fallisce, _load_decrypted_config solleva 500 vault_mismatch
    e disabilita la config (enabled=False) per evitare loop di chiamate."""
    from routes import portal86_datto as mod
    from fastapi import HTTPException

    fake_cfg = {
        "_id": "global",
        "api_url": mod.DEFAULT_API_URL,
        "api_key_enc": "v2:corrupted",
        "user_id_enc": "v2:corrupted",
        "enabled": True,
    }
    update_mock = AsyncMock()
    fake_db = MagicMock()
    fake_db.portal86_datto_config.find_one = AsyncMock(return_value=fake_cfg)
    fake_db.portal86_datto_config.update_one = update_mock

    fake_sm = MagicMock()
    fake_sm.decrypt_credential = MagicMock(side_effect=ValueError("InvalidTag"))

    with patch.object(mod, "db", fake_db), \
         patch.object(mod, "security_manager", fake_sm):
        with pytest.raises(HTTPException) as exc:
            await mod._load_decrypted_config()

    assert exc.value.status_code == 500
    assert "vault_mismatch" in exc.value.detail
    # Config disabilitata per evitare loop
    update_mock.assert_awaited_once()
    set_doc = update_mock.await_args.args[1]["$set"]
    assert set_doc["last_poll_status"] == "vault_mismatch"
    assert set_doc["enabled"] is False


@pytest.mark.asyncio
async def test_load_config_raises_400_if_not_configured():
    """Se la config non esiste in DB, _load_decrypted_config solleva 400."""
    from routes import portal86_datto as mod
    from fastapi import HTTPException

    fake_db = MagicMock()
    fake_db.portal86_datto_config.find_one = AsyncMock(return_value=None)
    with patch.object(mod, "db", fake_db):
        with pytest.raises(HTTPException) as exc:
            await mod._load_decrypted_config()
    assert exc.value.status_code == 400
    assert "non configurato" in exc.value.detail


@pytest.mark.asyncio
async def test_load_config_raises_400_if_disabled():
    """Config valida ma enabled=False → 400."""
    from routes import portal86_datto as mod
    from fastapi import HTTPException

    fake_cfg = {
        "_id": "global",
        "api_url": mod.DEFAULT_API_URL,
        "api_key_enc": "v2:x",
        "user_id_enc": "v2:y",
        "enabled": False,
    }
    fake_db = MagicMock()
    fake_db.portal86_datto_config.find_one = AsyncMock(return_value=fake_cfg)
    with patch.object(mod, "db", fake_db):
        with pytest.raises(HTTPException) as exc:
            await mod._load_decrypted_config()
    assert exc.value.status_code == 400
    assert "disabilitato" in exc.value.detail


@pytest.mark.asyncio
async def test_fetch_sites_parses_json_response():
    """_fetch_sites ritorna (status, parsed_json) quando upstream serve JSON."""
    from routes import portal86_datto as mod

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.json = MagicMock(return_value={"success": True, "sites": {"pageDetails": {"count": 5}, "sites": []}})

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, params=None): return fake_response

    with patch.object(mod.httpx, "AsyncClient", FakeClient):
        code, body = await mod._fetch_sites(mod.DEFAULT_API_URL, "k", "u")

    assert code == 200
    assert isinstance(body, dict)
    assert body["success"] is True
    assert body["sites"]["pageDetails"]["count"] == 5


def test_mask_helper():
    """Funzione _mask non rivela il segreto ma mostra suffisso ultimo N char."""
    from routes.portal86_datto import _mask
    assert _mask("") == "(non configurato)"
    assert _mask("abc") == "***"  # len <= keep default 4 → tutto mascherato
    assert _mask("abcdefghij", keep=4) == "******ghij"
    assert _mask("5ec7affa4cdcd40b443d5c38", keep=6) == "******************3d5c38"  # solo ultimi 6 visibili


def test_encrypt_decrypt_roundtrip():
    """SecurityManager round-trip: encrypt poi decrypt restituisce plaintext.

    Garanzia: il vault non corrompe credenziali. Se questo test fallisce, c'e'
    un problema di vault key tra encrypt e decrypt (caso vault_mismatch).
    """
    from security import security_manager
    secrets = [
        "f34ASDF2SADF2344SDDFsdfasSDF",
        "5ec7affa4cdcd40b443d5c38",
        "very-long-api-key-" + "x" * 256,
        "a",  # short
    ]
    for s in secrets:
        enc = security_manager.encrypt_credential(s)
        assert enc != s, "encryption must change the plaintext"
        assert enc.startswith("v2:"), f"unexpected vault format prefix: {enc[:5]}"
        dec = security_manager.decrypt_credential(enc)
        assert dec == s, f"round-trip failed for {s!r}: got {dec!r}"
