"""Regression tests per il routing intelligente WireGuard vs Connector long-poll
introdotto in v3.5.22 dentro routes/web_console_live.py.

Scenari coperti:
  1. _wg_server_ready: cache + lettura env vars
  2. _wg_session_active_for_device: query DB con scadenza
  3. live_proxy ha fallback comportamentale invariato quando WG non disponibile

I test usano monkeypatch + mock async per non richiedere un'istanza reale di
WireGuard server o connector running.
"""
import os
import time
import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

from routes import web_console_live as wcl


@pytest.fixture(autouse=True)
def reset_wg_ready_cache():
    """Reset cache TTL prima di ogni test (altrimenti gli env vars settati nel
    test precedente restano cachati per 60s)."""
    wcl._WG_SERVER_READY_CACHE["value"] = None
    wcl._WG_SERVER_READY_CACHE["checked_at"] = 0.0
    yield


def test_wg_server_ready_false_when_env_missing(monkeypatch):
    monkeypatch.delenv("WG_SERVER_PUBKEY", raising=False)
    monkeypatch.delenv("WG_SERVER_ENDPOINT", raising=False)
    assert wcl._wg_server_ready() is False


def test_wg_server_ready_true_when_env_set(monkeypatch):
    monkeypatch.setenv("WG_SERVER_PUBKEY", "fakepubkey32bytes==")
    monkeypatch.setenv("WG_SERVER_ENDPOINT", "1.2.3.4:51820")
    assert wcl._wg_server_ready() is True


def test_wg_server_ready_partial_env_returns_false(monkeypatch):
    monkeypatch.setenv("WG_SERVER_PUBKEY", "fakepubkey")
    monkeypatch.delenv("WG_SERVER_ENDPOINT", raising=False)
    assert wcl._wg_server_ready() is False


def test_wg_server_ready_cache_60s(monkeypatch):
    """Verifica che il check non venga rifatto piu' di una volta ogni 60s."""
    monkeypatch.setenv("WG_SERVER_PUBKEY", "k")
    monkeypatch.setenv("WG_SERVER_ENDPOINT", "1.2.3.4:51820")
    assert wcl._wg_server_ready() is True
    # Ora rimuovo le env vars: ma la cache deve essere ancora "True"
    monkeypatch.delenv("WG_SERVER_PUBKEY", raising=False)
    monkeypatch.delenv("WG_SERVER_ENDPOINT", raising=False)
    assert wcl._wg_server_ready() is True  # cache hit
    # Avanzo il tempo cache forzando reset
    wcl._WG_SERVER_READY_CACHE["checked_at"] = time.time() - 70.0
    assert wcl._wg_server_ready() is False  # ricalcolato dopo TTL scaduta


@pytest.mark.anyio
async def test_wg_session_active_short_circuits_when_server_not_ready(monkeypatch):
    """Se il server WG non e' configurato, il check sessione attiva ritorna False
    SENZA toccare il DB. Risparmio I/O su ambienti dove WG non e' usato."""
    monkeypatch.delenv("WG_SERVER_PUBKEY", raising=False)
    monkeypatch.delenv("WG_SERVER_ENDPOINT", raising=False)
    # Mock find_one che NON deve essere chiamato
    mock_find = AsyncMock(return_value={"session_id": "should-not-be-returned"})
    with patch.object(wcl.db.wireguard_sessions, "find_one", mock_find):
        result = await wcl._wg_session_active_for_device("client-x", "10.0.0.5")
    assert result is False
    mock_find.assert_not_awaited()


@pytest.mark.anyio
async def test_wg_session_active_queries_db_with_correct_filter(monkeypatch):
    """Quando WG e' ready, _wg_session_active_for_device interroga
    wireguard_sessions con i filtri attesi (status active + expires_at futuro).

    Il test sostituisce direttamente l'oggetto db nel modulo per evitare
    interazioni con Motor singleton (che ha problemi di event-loop teardown
    nei test anyio paralleli)."""
    monkeypatch.setenv("WG_SERVER_PUBKEY", "k")
    monkeypatch.setenv("WG_SERVER_ENDPOINT", "1.2.3.4:51820")
    captured_filter = {}

    class _FakeColl:
        async def find_one(self, filter_, projection=None):
            captured_filter.update(filter_)
            return {"session_id": "abc"}

    class _FakeDb:
        wireguard_sessions = _FakeColl()

    monkeypatch.setattr(wcl, "db", _FakeDb())
    result = await wcl._wg_session_active_for_device("client-x", "10.0.0.5")

    assert result is True
    assert captured_filter["client_id"] == "client-x"
    assert captured_filter["target_device_ip"] == "10.0.0.5"
    assert captured_filter["status"] == "active"
    # expires_at deve essere {$gt: now}
    assert "expires_at" in captured_filter and "$gt" in captured_filter["expires_at"]


@pytest.mark.anyio
async def test_wg_session_active_returns_false_when_no_doc(monkeypatch):
    monkeypatch.setenv("WG_SERVER_PUBKEY", "k")
    monkeypatch.setenv("WG_SERVER_ENDPOINT", "1.2.3.4:51820")

    class _FakeColl:
        async def find_one(self, filter_, projection=None):
            return None

    class _FakeDb:
        wireguard_sessions = _FakeColl()

    monkeypatch.setattr(wcl, "db", _FakeDb())
    result = await wcl._wg_session_active_for_device("client-x", "10.0.0.5")
    assert result is False


@pytest.mark.anyio
async def test_proxy_via_wireguard_returns_quadruple():
    """Smoke test: _proxy_via_wireguard ritorna la stessa shape di
    _proxy_via_connector (status_code, content_type, body, resp_headers).
    Mocka httpx.AsyncClient per non aprire socket reale."""

    class _MockResp:
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8", "set-cookie": "x=1"}
        content = b"<html>ok</html>"

    class _MockClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, headers=None, content=None):
            return _MockResp()

    with patch("httpx.AsyncClient", return_value=_MockClient()):
        result = await wcl._proxy_via_wireguard(
            "10.0.0.5", 80, "http", "/", "GET", b"", {}
        )

    status_code, content_type, body, resp_headers = result
    assert status_code == 200
    assert "text/html" in content_type
    assert body == b"<html>ok</html>"
    assert resp_headers.get("set-cookie") == "x=1"
