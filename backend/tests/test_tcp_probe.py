"""Tests for TCP probe distinguishing open / closed / filtered / unreachable."""
import sys
import os
import asyncio
import socket
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routes.external_monitor import check_tcp_port


# Helper per avere una porta libera nota
def _get_free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.mark.asyncio
async def test_open_port_returns_open():
    """Una porta in ascolto deve ritornare status=open."""
    # Avvia un server fittizio
    server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        result = await check_tcp_port("127.0.0.1", port, timeout=3)
        assert result["open"] is True
        assert result["status"] == "open"
        assert isinstance(result["response_ms"], (int, float))
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_closed_port_returns_closed():
    """Porta senza ascoltatore (RST esplicito) → status=closed."""
    # Usa porta libera (nessuno in ascolto) su localhost
    free = _get_free_port()
    result = await check_tcp_port("127.0.0.1", free, timeout=3)
    assert result["open"] is False
    assert result["status"] == "closed"
    assert result["response_ms"] is None


@pytest.mark.asyncio
async def test_filtered_port_returns_filtered():
    """IP non routable / firewall droppa → timeout → status=filtered."""
    # 10.255.255.1 è un IP TEST-NET, non routable → timeout
    result = await check_tcp_port("10.255.255.1", 443, timeout=2)
    # Può essere "filtered" (timeout) o "unreachable" (ENETUNREACH)
    # dipende dalla configurazione del container. Entrambi accettabili.
    assert result["open"] is False
    assert result["status"] in ("filtered", "unreachable")


@pytest.mark.asyncio
async def test_invalid_host_returns_error_or_unreachable():
    """Host non risolvibile → error."""
    result = await check_tcp_port("host-non-esistente-12345.invalid", 443, timeout=2)
    assert result["open"] is False
    assert result["status"] in ("error", "unreachable", "filtered")
