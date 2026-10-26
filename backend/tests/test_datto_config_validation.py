"""Validation di hardening per PUT /api/admin/datto/config.

Evita gli errori di compilazione del form (USER ID con email,
BASE URL con query string) che causavano 401 silenziosi a runtime.
"""
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _make_fake_admin():
    return {"id": "u1", "email": "test@86bit.it", "role": "admin"}


@pytest.mark.asyncio
async def test_user_id_with_email_rejected_with_clear_message():
    """USER ID = 'info@86bit.it' deve essere rifiutato con messaggio chiaro
    invece di propagare un 401 dal portal a runtime."""
    from routes import datto_rmm as mod
    from routes.datto_rmm import DattoConfigIn, put_datto_config
    from fastapi import HTTPException

    payload = DattoConfigIn(
        api_key="f34ASDF2SADF2344",
        user_id="info@86bit.it",  # BUG: e' un'email
        base_url=mod.DEFAULT_BASE_URL,
    )

    with patch.object(mod, "security_manager", MagicMock(encrypt_credential=lambda x: "enc")), \
         patch.object(mod, "db", MagicMock()):
        with pytest.raises(HTTPException) as exc:
            await put_datto_config(payload, current_user=_make_fake_admin())
    assert exc.value.status_code == 400
    assert "USER ID" in exc.value.detail
    assert "email" in exc.value.detail.lower()
    assert "ObjectId" in exc.value.detail


@pytest.mark.asyncio
async def test_base_url_with_query_string_rejected():
    """BASE URL con `?api_key=...&userId=...` deve essere rifiutata: i parametri
    vengono aggiunti dal backend, includerli causa duplicazione/URL invalido."""
    from routes import datto_rmm as mod
    from routes.datto_rmm import DattoConfigIn, put_datto_config
    from fastapi import HTTPException

    payload = DattoConfigIn(
        api_key="f34ASDF2SADF2344",
        user_id="5ec7affa4cdcd40b443d5c38",
        base_url="https://portal.86bit.it/api/v1/reports/datto/getDattoSites?api_key=XXX&userId=YYY",
    )

    with patch.object(mod, "security_manager", MagicMock(encrypt_credential=lambda x: "enc")), \
         patch.object(mod, "db", MagicMock()):
        with pytest.raises(HTTPException) as exc:
            await put_datto_config(payload, current_user=_make_fake_admin())
    assert exc.value.status_code == 400
    assert "BASE URL" in exc.value.detail
    assert "parametri" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_valid_payload_accepted():
    """Payload valido (USER ID = ObjectId, BASE URL senza query) → accettato."""
    from routes import datto_rmm as mod
    from routes.datto_rmm import DattoConfigIn, put_datto_config

    payload = DattoConfigIn(
        api_key="f34ASDF2SADF2344",
        user_id="5ec7affa4cdcd40b443d5c38",
        base_url="https://portal.86bit.it/api/v1/reports/datto/getDattoDevices",
    )

    fake_db = MagicMock()
    fake_db.datto_settings.update_one = AsyncMock()

    with patch.object(mod, "security_manager", MagicMock(encrypt_credential=lambda x: "v2:enc")), \
         patch.object(mod, "db", fake_db):
        result = await put_datto_config(payload, current_user=_make_fake_admin())

    assert result.configured is True
    assert result.user_id == "5ec7affa4cdcd40b443d5c38"
    assert "?" not in result.base_url
    fake_db.datto_settings.update_one.assert_awaited_once()


@pytest.mark.asyncio
async def test_user_id_with_invalid_chars_rejected():
    """USER ID con spazi/caratteri speciali viene rifiutato."""
    from routes import datto_rmm as mod
    from routes.datto_rmm import DattoConfigIn, put_datto_config
    from fastapi import HTTPException

    payload = DattoConfigIn(
        api_key="f34ASDF2SADF2344",
        user_id="utente con spazi!",
        base_url=mod.DEFAULT_BASE_URL,
    )
    with patch.object(mod, "security_manager", MagicMock(encrypt_credential=lambda x: "enc")), \
         patch.object(mod, "db", MagicMock()):
        with pytest.raises(HTTPException) as exc:
            await put_datto_config(payload, current_user=_make_fake_admin())
    assert exc.value.status_code == 400
    assert "USER ID" in exc.value.detail
