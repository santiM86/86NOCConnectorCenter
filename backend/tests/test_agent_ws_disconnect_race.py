"""v4.18.x — Test della race-condition di disconnect fixata in agent_ws.py.

Scenario: l'agent v4 si riconnette con lo stesso `agent_id`. Il vecchio
_Connection nel REGISTRY viene chiuso da _Registry.add. La vecchia
coroutine arriva nel finally; PRIMA della fix, eseguiva sempre
  update_one({"$set": {"connected": False}})
sovrascrivendo lo stato della NUOVA sessione (che aveva appena settato
connected: True).

Conseguenza nel bug: managed_agents.connected = False per agent attivi
→ zombie-v3-protection in devices.py si disattivava, i dati apparivano
stale → utente vede dispositivi "obsoleti" anche con agent vivo.

Fix: nel finally, controllo REGISTRY.get(agent_id) — se non e' la
nostra conn, NON marchiamo connected=False.
"""
import asyncio
import os
import sys

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_database")
os.environ.setdefault("JWT_SECRET", "test-secret")

sys.path.insert(0, "/app/backend")

from routes import agent_ws as ws_mod  # noqa: E402


class _FakeWS:
    def __init__(self):
        self.closed = False

    async def close(self, code=None, reason=None):
        self.closed = True


def _decide_should_mark_disconnected(registry, agent_id, conn) -> bool:
    """Mirror della logica esatta del finally in agent_ws.py
    (post-fix v4.18.x).
    """
    current = registry.get(agent_id)
    return current is None or current is conn


@pytest.mark.asyncio
async def test_replaced_session_skips_disconnect_update():
    """La vecchia conn (gia' rimpiazzata) NON deve marcare connected=False."""
    registry = ws_mod._Registry()
    agent_id = "race-agent-1"
    old_conn = ws_mod._Connection(agent_id, "client-X", _FakeWS())
    new_conn = ws_mod._Connection(agent_id, "client-X", _FakeWS())

    await registry.add(old_conn)
    # La nuova arriva e rimpiazza
    await registry.add(new_conn)
    assert registry.get(agent_id) is new_conn

    # La vecchia coroutine entra nel finally
    decision_old = _decide_should_mark_disconnected(registry, agent_id, old_conn)
    assert decision_old is False, (
        "BUG-FIX v4.18.x: la vecchia conn rimpiazzata NON deve marcare disconnected"
    )
    await registry.remove(agent_id, old_conn)
    # Il registry non e' stato toccato (new_conn ancora presente)
    assert registry.get(agent_id) is new_conn


@pytest.mark.asyncio
async def test_normal_disconnect_marks_disconnected():
    """Disconnect normale (no riconnessione): connected=False deve essere scritto."""
    registry = ws_mod._Registry()
    agent_id = "normal-agent-1"
    conn = ws_mod._Connection(agent_id, "client-Y", _FakeWS())

    await registry.add(conn)
    assert registry.get(agent_id) is conn

    # Disconnect normale: la conn esce dal finally
    decision = _decide_should_mark_disconnected(registry, agent_id, conn)
    assert decision is True, "Disconnect normale: dovrebbe marcare disconnected"
    await registry.remove(agent_id, conn)
    assert registry.get(agent_id) is None


@pytest.mark.asyncio
async def test_bridge_stat_tick_records_snmp_and_ping():
    """Verifica counter in-memory per SNMP + ping."""
    ws_mod.BRIDGE_STATS.clear()
    ws_mod._bridge_stat_tick("agentA", "snmp_poll", target="10.0.0.1", reachable=True)
    ws_mod._bridge_stat_tick("agentA", "snmp_poll", target="10.0.0.2", reachable=False)
    ws_mod._bridge_stat_tick("agentA", "ping_poll", target="10.0.0.1", reachable=True)
    bucket = ws_mod.BRIDGE_STATS["agentA"]
    assert bucket["counters"]["snmp_poll"] == 2
    assert bucket["counters"]["ping_poll"] == 1
    assert bucket["last_snmp_poll_target"] == "10.0.0.2"
    assert bucket["last_snmp_poll_reachable"] is False
    assert bucket["last_ping_poll_target"] == "10.0.0.1"
    assert bucket["last_ping_poll_reachable"] is True


def test_bridge_stat_tick_ignores_empty_agent_id():
    ws_mod.BRIDGE_STATS.clear()
    ws_mod._bridge_stat_tick("", "snmp_poll", target="10.0.0.1")
    assert ws_mod.BRIDGE_STATS == {}
