"""
Test: la funzione _effective_reachable di /api/devices DEVE considerare
ONLINE anche un device che ha snmp_reachable=True con poll recente,
anche se il ping ICMP fallisce. Era il bug "switch HP Comware / server
Windows con ICMP bloccato sempre offline" segnalato il 12/06/2026.

Pattern Zabbix: "Available via SNMP" è una liveness valida quanto ICMP.
"""
from datetime import datetime, timedelta, timezone

import pytest


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat()


@pytest.mark.asyncio
async def test_effective_reachable_snmp_ok_ping_fail_is_online():
    """SNMP fresco + reachable=True ⇒ device ONLINE anche se ping fallisce."""
    from routes import devices as mod

    # Simula un ciclo di get_devices senza chiamare l'endpoint completo:
    # estraiamo la chiusura interna importando l'AST. Più semplice:
    # ricreiamo lo stesso predicato qui per validare il comportamento atteso.
    # In alternativa, possiamo testare l'endpoint end-to-end con mock — ma
    # _effective_reachable è una closure interna di get_devices, quindi qui
    # testiamo il **comportamento osservabile** via mock del DB.
    pass  # placeholder — la closure non è direttamente importabile


@pytest.mark.asyncio
async def test_get_devices_marks_snmp_only_host_as_online(monkeypatch):
    """End-to-end con mock: un device con ping_reachable=False ma
    snmp_reachable=True (poll < 10 min fa) deve apparire come status=online
    nella risposta dell'endpoint /api/devices."""
    from routes import devices as mod
    from unittest.mock import AsyncMock, MagicMock

    client_id = "c-test"
    ip = "10.10.41.220"

    pd = {
        "client_id": client_id,
        "device_ip": ip,
        "reachable": False,         # PING fallisce (ICMP bloccato)
        "ping_reachable": False,
        "snmp_reachable": True,     # SNMP risponde
        "snmp_last_check_at": _iso(_now() - timedelta(minutes=2)),
        "last_poll_at": _iso(_now() - timedelta(minutes=2)),
        "last_ping_at": _iso(_now() - timedelta(minutes=1)),
        "source": "agent_v4",
        "consecutive_failures": 7,
        "last_reachable_at": _iso(_now() - timedelta(hours=12)),  # vecchio
    }

    md = {
        "client_id": client_id,
        "ip": ip,
        "hostname": "switch01",
        "vendor": "HPE",
        "device_type": "switch",
    }

    class _AsyncIterEmpty:
        def __aiter__(self): return self
        async def __anext__(self): raise StopAsyncIteration

    class _AsyncList:
        def __init__(self, data): self._d = data
        def __aiter__(self):
            self._i = iter(self._d); return self
        async def __anext__(self):
            try: return next(self._i)
            except StopIteration: raise StopAsyncIteration

    async def _to_list_empty(_n=None): return []

    def _coll_find_returning(docs):
        cur = MagicMock()
        cur.to_list = AsyncMock(return_value=docs)
        cur.__aiter__ = lambda self: iter(docs).__iter__()
        return cur

    devices_coll = MagicMock()
    devices_coll.find = MagicMock(return_value=_coll_find_returning([]))

    poll_coll = MagicMock()
    poll_coll.find = MagicMock(return_value=_coll_find_returning([pd]))

    managed_coll = MagicMock()
    managed_coll.find = MagicMock(return_value=_coll_find_returning([md]))

    # find_one per managed_agents (v4_master_alive check)
    managed_agents_coll = MagicMock()
    managed_agents_coll.find_one = AsyncMock(return_value={
        "agent_id": "a1", "role": "master",
        "last_heartbeat_at": _iso(_now() - timedelta(seconds=30)),
    })
    managed_agents_coll.find = MagicMock(return_value=_AsyncIterEmpty())

    discovered_coll = MagicMock()
    discovered_coll.find = MagicMock(return_value=_AsyncIterEmpty())

    monkeypatch.setattr(mod.db, "devices", devices_coll)
    monkeypatch.setattr(mod.db, "device_poll_status", poll_coll)
    monkeypatch.setattr(mod.db, "managed_devices", managed_coll)
    monkeypatch.setattr(mod.db, "managed_agents", managed_agents_coll)
    monkeypatch.setattr(mod.db, "discovered_endpoints", discovered_coll)

    # current_user è un dict qualsiasi (la dependency è bypassata)
    out = await mod.get_devices(client_id=client_id, current_user={"id": "u1"})

    assert isinstance(out, list)
    matching = [d for d in out if d.get("ip_address") == ip]
    assert matching, f"device {ip} non trovato nel risultato: {out}"
    assert matching[0]["status"] == "online", (
        f"Atteso ONLINE (SNMP fresco reachable=True), ottenuto: "
        f"{matching[0].get('status')} — pd={pd}"
    )
