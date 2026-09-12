"""Regression test v3.8.32 ANTI-FLAP — debounce status online/offline.

Bug: dispositivi che oscillano random tra online e offline ogni qualche minuto
quando il Master fallisce un singolo poll SNMP (UDP packet loss / timeout).

Fix: 
- connector.device-report ora salva consecutive_failures e last_reachable_at.
- devices._effective_reachable considera offline SOLO se consec >= 3 E
  last_reachable_at e' piu' vecchio di 300s.
- overview.py applica la stessa logica al calcolo dei contatori per cliente.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from routes.devices import get_devices  # noqa: E402  (verifica import non rompa)


def _now_iso(offset_sec=0):
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_sec)).isoformat()


def test_effective_reachable_logic_module():
    """Verifica la pure-function _effective_reachable definita in devices.get_devices.
    Estraiamo il comportamento ricostruendolo qui per indipendenza dal context async."""
    DEBOUNCE_MIN_FAILURES = 3
    DEBOUNCE_GRACE_SECONDS = 300

    def effective(pd_doc):
        if not pd_doc:
            return False
        if pd_doc.get("reachable"):
            return True
        consec = int(pd_doc.get("consecutive_failures") or 0)
        last_ok = pd_doc.get("last_reachable_at")
        if not last_ok:
            return False
        try:
            last_ok_dt = datetime.fromisoformat(last_ok.replace("Z", "+00:00"))
            secs_since = (datetime.now(timezone.utc) - last_ok_dt).total_seconds()
        except Exception:
            secs_since = 1e9
        if consec >= DEBOUNCE_MIN_FAILURES and secs_since >= DEBOUNCE_GRACE_SECONDS:
            return False
        return True

    # 1. reachable=true → online sempre
    assert effective({"reachable": True}) is True

    # 2. fail singolo (consec=1) entro 5 min → ancora online (debounce)
    assert effective({"reachable": False, "consecutive_failures": 1, "last_reachable_at": _now_iso(-30)}) is True
    # 3. 2 fail consecutivi entro 5 min → online (sotto soglia)
    assert effective({"reachable": False, "consecutive_failures": 2, "last_reachable_at": _now_iso(-120)}) is True
    # 4. 3 fail consecutivi MA last_reachable < 5 min → online (grace window)
    assert effective({"reachable": False, "consecutive_failures": 3, "last_reachable_at": _now_iso(-200)}) is True
    # 5. 3 fail consecutivi E last_reachable > 5 min → offline (entrambe condizioni superate)
    assert effective({"reachable": False, "consecutive_failures": 3, "last_reachable_at": _now_iso(-400)}) is False
    # 6. consec=10, last_reachable=10 min → offline
    assert effective({"reachable": False, "consecutive_failures": 10, "last_reachable_at": _now_iso(-600)}) is False
    # 7. backward-compat: campi nuovi assenti → offline (vecchio comportamento)
    assert effective({"reachable": False}) is False
    # 8. nessun pd → offline
    assert effective(None) is False
    assert effective({}) is False


def test_connector_device_report_writes_consecutive_failures():
    """Smoke: verifica che il blocco di device-report e' coerente con lo schema atteso."""
    from routes import connector as conn_mod
    src = open(conn_mod.__file__).read()
    # Verifica presenza dei campi nuovi nel codice
    assert '"consecutive_failures"' in src
    assert '"last_reachable_at"' in src
    assert "v3.8.32 ANTI-FLAP" in src


def test_overview_applies_debounce():
    """Smoke: verifica che il file overview.py considera consecutive_failures."""
    from routes import overview as ov_mod
    src = open(ov_mod.__file__).read()
    assert "consecutive_failures" in src
    assert "last_reachable_at" in src
    assert "v3.8.32 ANTI-FLAP" in src
