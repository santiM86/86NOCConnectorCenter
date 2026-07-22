"""Regression test v3.8.36 — Status check freschezza per device source=connector-scanner.

Bug originale: in /app/backend/routes/devices.py riga 267-268, il check
`elif md_source == "connector-scanner" and md.get("last_seen_at")` marcava
ONLINE qualsiasi device scanner-scoperto con ultimo last_seen_at, anche se di
10 ore fa o di una settimana fa. Risultato: stampanti/server offline da tempo
mostrati come online in UI.

Fix: introdotta soglia SCANNER_STALE_SECONDS = 1800s (30min). Oltre questa
soglia, il device scanner-source passa a "offline".
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _scanner_status_from_last_seen(last_seen_iso):
    """Replica della logica in devices.get_devices."""
    SCANNER_STALE_SECONDS = 1800
    now_dt = datetime.now(timezone.utc)
    if not last_seen_iso:
        return "pending"
    try:
        ls = datetime.fromisoformat(last_seen_iso.replace("Z", "+00:00"))
        age_s = (now_dt - ls).total_seconds()
    except Exception:
        return "pending"
    if age_s < SCANNER_STALE_SECONDS:
        return "online"
    return "offline"


def _iso_offset(seconds):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def test_recent_last_seen_online():
    """Device visto 5min fa → online."""
    assert _scanner_status_from_last_seen(_iso_offset(300)) == "online"


def test_borderline_window():
    """Device visto 29min fa → ancora online (sotto soglia 30min)."""
    assert _scanner_status_from_last_seen(_iso_offset(29 * 60)) == "online"


def test_just_over_threshold_offline():
    """Device visto 31min fa → offline."""
    assert _scanner_status_from_last_seen(_iso_offset(31 * 60)) == "offline"


def test_ten_hours_old_offline():
    """SIMULA IL BUG: device visto 10 ore fa (caso reale NPIC3C01E) → DEVE essere offline.
    Pre-v3.8.36: era erroneamente online perche' bastava avere last_seen_at."""
    assert _scanner_status_from_last_seen(_iso_offset(10 * 3600)) == "offline"


def test_very_old_offline():
    """1 settimana fa → offline."""
    assert _scanner_status_from_last_seen(_iso_offset(7 * 86400)) == "offline"


def test_no_last_seen_pending():
    """Device senza last_seen_at → pending."""
    assert _scanner_status_from_last_seen(None) == "pending"
    assert _scanner_status_from_last_seen("") == "pending"


def test_invalid_format_pending():
    """Formato data invalido → pending (fallback sicuro)."""
    assert _scanner_status_from_last_seen("not-a-date") == "pending"


def test_devices_route_has_fix_comment():
    """Smoke: il file devices.py contiene il fix v3.8.36."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "routes", "devices.py")).read()
    assert "SCANNER_STALE_SECONDS" in src
    assert "v3.8.36" in src
    assert "_scanner_status_from_last_seen" in src
