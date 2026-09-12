"""Regressione: il sync Datto non deve crashare con HTTP 500 quando un singolo
device causa eccezione, e il match-debug endpoint deve identificare la causa
del "N device persisted ma 0 match"."""
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.mark.asyncio
async def test_match_debug_diagnoses_zero_endpoints():
    """Caso A: il connector LAN scanner non vede device → diagnosi specifica."""
    from routes import datto_rmm as mod
    from routes.datto_rmm import datto_match_debug

    persisted = [
        {"uid": "u1", "name": "PC1", "mac": "AA:BB:CC:DD:EE:01", "ip": "192.168.1.10",
         "mac_list": ["AA:BB:CC:DD:EE:01"], "ip_list": ["192.168.1.10"]},
    ]
    fake_db = MagicMock()
    fake_db.datto_devices.find = MagicMock(return_value=MagicMock(to_list=AsyncMock(return_value=persisted)))
    fake_db.discovered_endpoints.find = MagicMock(return_value=MagicMock(to_list=AsyncMock(return_value=[])))

    admin = {"id": "u1", "email": "x@86bit.it", "role": "admin"}
    with patch.object(mod, "db", fake_db):
        out = await datto_match_debug("client-abc", current_user=admin)

    assert out["datto_devices_persisted"] == 1
    assert out["discovered_endpoints_total"] == 0
    assert "(A)" in out["diagnosis"]
    assert "LAN scanner" in out["diagnosis"]


@pytest.mark.asyncio
async def test_match_debug_diagnoses_no_mac_in_datto():
    """Caso C: device Datto persistiti ma nessuno ha MAC (audit endpoint vuoto)."""
    from routes import datto_rmm as mod
    from routes.datto_rmm import datto_match_debug

    persisted = [
        {"uid": "u1", "name": "PC1", "mac": "", "ip": "192.168.1.10", "mac_list": [], "ip_list": ["192.168.1.10"]},
        {"uid": "u2", "name": "PC2", "mac": "", "ip": "192.168.1.11", "mac_list": [], "ip_list": ["192.168.1.11"]},
    ]
    eps = [
        {"mac": "AA:BB:CC:DD:EE:99", "ip": "192.168.1.50", "switch_ip": "10.0.0.1", "port": 5},
    ]
    fake_db = MagicMock()
    fake_db.datto_devices.find = MagicMock(return_value=MagicMock(to_list=AsyncMock(return_value=persisted)))
    fake_db.discovered_endpoints.find = MagicMock(return_value=MagicMock(to_list=AsyncMock(return_value=eps)))

    admin = {"id": "u1", "email": "x@86bit.it", "role": "admin"}
    with patch.object(mod, "db", fake_db):
        out = await datto_match_debug("client-abc", current_user=admin)

    assert out["datto_devices_persisted"] == 2
    assert out["datto_devices_with_mac"] == 0
    assert "(C)" in out["diagnosis"]
    assert "audit" in out["diagnosis"].lower()


@pytest.mark.asyncio
async def test_match_debug_diagnoses_intersection_ok():
    """Caso ✅: c'e' intersezione MAC, basta ri-syncare."""
    from routes import datto_rmm as mod
    from routes.datto_rmm import datto_match_debug

    persisted = [
        {"uid": "u1", "name": "PC1", "mac": "AA:BB:CC:DD:EE:01", "ip": "192.168.1.10",
         "mac_list": ["AA:BB:CC:DD:EE:01"], "ip_list": ["192.168.1.10"]},
    ]
    eps = [
        {"mac": "AA:BB:CC:DD:EE:01", "ip": "192.168.1.10", "switch_ip": "10.0.0.1", "port": 5},
    ]
    fake_db = MagicMock()
    fake_db.datto_devices.find = MagicMock(return_value=MagicMock(to_list=AsyncMock(return_value=persisted)))
    fake_db.discovered_endpoints.find = MagicMock(return_value=MagicMock(to_list=AsyncMock(return_value=eps)))

    admin = {"id": "u1", "email": "x@86bit.it", "role": "admin"}
    with patch.object(mod, "db", fake_db):
        out = await datto_match_debug("client-abc", current_user=admin)

    assert out["intersection_mac"] == 1
    assert "✅" in out["diagnosis"]
