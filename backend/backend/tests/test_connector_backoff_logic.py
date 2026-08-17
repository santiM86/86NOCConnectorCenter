"""Test logica backoff esponenziale (replica PowerShell in Python).

Verifica i delay e il behavior del backoff implementato in connector.ps1 v3.8.22.
"""
from datetime import datetime, timedelta


class BackoffState:
    """Replica della struttura PowerShell hashtable $global:BackoffState[$endpoint]."""

    def __init__(self):
        self.failures = 0
        self.next_retry_at = datetime.now()


class BackoffManager:
    """Replica delle 3 funzioni PowerShell: Test-BackoffSkip / Register-BackoffFailure / Reset-BackoffState."""

    DELAYS = [5, 10, 20, 40, 60]  # in secondi (1°, 2°, 3°, 4°, 5°+ fail)

    def __init__(self):
        self.state = {}

    def test_skip(self, endpoint, now=None):
        if now is None:
            now = datetime.now()
        st = self.state.get(endpoint)
        if not st:
            return False
        return now < st.next_retry_at

    def register_failure(self, endpoint, now=None):
        if now is None:
            now = datetime.now()
        st = self.state.get(endpoint) or BackoffState()
        st.failures += 1
        idx = min(st.failures - 1, len(self.DELAYS) - 1)
        delay = self.DELAYS[idx]
        st.next_retry_at = now + timedelta(seconds=delay)
        self.state[endpoint] = st
        return delay

    def reset(self, endpoint):
        self.state.pop(endpoint, None)


def test_first_failure_5s_cooldown():
    bo = BackoffManager()
    delay = bo.register_failure("connector/heartbeat")
    assert delay == 5


def test_progressive_backoff_5_10_20_40_60():
    bo = BackoffManager()
    delays = [bo.register_failure("connector/network-discovery") for _ in range(7)]
    # Schema atteso: 5, 10, 20, 40, 60, 60, 60 (cap)
    assert delays == [5, 10, 20, 40, 60, 60, 60]


def test_skip_during_cooldown():
    bo = BackoffManager()
    now = datetime(2026, 5, 6, 14, 0, 0)
    bo.register_failure("connector/heartbeat", now=now)
    # 1s dopo dovrebbe ancora skippare (5s di cooldown)
    assert bo.test_skip("connector/heartbeat", now=now + timedelta(seconds=1)) is True
    assert bo.test_skip("connector/heartbeat", now=now + timedelta(seconds=4)) is True
    # 5s dopo dovrebbe smettere di skippare
    assert bo.test_skip("connector/heartbeat", now=now + timedelta(seconds=6)) is False


def test_skip_returns_false_for_unknown_endpoint():
    bo = BackoffManager()
    assert bo.test_skip("never-failed-endpoint") is False


def test_reset_clears_state():
    bo = BackoffManager()
    bo.register_failure("connector/heartbeat")
    bo.register_failure("connector/heartbeat")
    bo.register_failure("connector/heartbeat")
    bo.reset("connector/heartbeat")
    assert bo.test_skip("connector/heartbeat") is False
    # Dopo reset, il prossimo failure ricomincia da 5s
    delay = bo.register_failure("connector/heartbeat")
    assert delay == 5


def test_per_endpoint_isolation():
    """Cooldown per /heartbeat NON deve toccare /device-report."""
    bo = BackoffManager()
    bo.register_failure("connector/heartbeat")
    assert bo.test_skip("connector/heartbeat") is True
    assert bo.test_skip("connector/device-report") is False  # isolato


def test_realistic_scenario_backend_500_then_recovers():
    """Scenario reale: backend va giu' per 90s, connector smette di tempestare."""
    bo = BackoffManager()
    now = datetime(2026, 5, 6, 14, 0, 0)

    # 4 fallimenti in 30s (5s, 10s, 20s) - dopo l'ultimo siamo bloccati per 40s
    bo.register_failure("connector/network-discovery", now=now)
    bo.register_failure("connector/network-discovery", now=now + timedelta(seconds=6))
    bo.register_failure("connector/network-discovery", now=now + timedelta(seconds=17))
    bo.register_failure("connector/network-discovery", now=now + timedelta(seconds=39))

    # Tra t=39 e t=79 dobbiamo essere in cooldown di 40s
    assert bo.test_skip("connector/network-discovery", now=now + timedelta(seconds=50)) is True
    assert bo.test_skip("connector/network-discovery", now=now + timedelta(seconds=78)) is True

    # Il backend torna online alle 14:01:30 (90s). Il connector ritenta.
    bo.reset("connector/network-discovery")
    # Ora chiamate libere
    assert bo.test_skip("connector/network-discovery") is False
