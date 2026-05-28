"""v2026-02-28: test della logica vital/non-vital nell'alert_filter.

Verifica che `is_device_silenced` rispetti la matrice:
  - is_vital=True   → NON silenziato (anche se alerts_silenced=True)
  - is_vital=False  → silenziato (best-effort)
  - is_vital=None / assente → backward compat (alerts_silenced wins)
  - alerts_silenced=True + is_vital missing → silenziato

NB: usiamo mock di `db.managed_devices.find_one` per evitare problemi di
event-loop binding (motor crea client legato al primo loop).
"""
import os
import sys
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_database")
os.environ.setdefault("JWT_SECRET", "test-secret")

sys.path.insert(0, "/app/backend")

from alert_filter import is_device_silenced, invalidate_silence_cache  # noqa: E402
import alert_filter as af_mod  # noqa: E402


class _FakeColl:
    def __init__(self, doc):
        self._doc = doc

    async def find_one(self, *args, **kwargs):
        return self._doc


class _FakeDB:
    def __init__(self, doc):
        self.managed_devices = _FakeColl(doc)


@pytest.mark.asyncio
async def test_vital_true_never_silenced():
    """is_vital=True ha precedenza assoluta: alert sempre emessi."""
    invalidate_silence_cache()
    fake_db = _FakeDB({"is_vital": True, "alerts_silenced": True})
    silenced = await is_device_silenced(fake_db, "client-X", "10.99.0.1")
    assert silenced is False, "VITAL deve avere precedenza su alerts_silenced"


@pytest.mark.asyncio
async def test_vital_false_is_silenced():
    """is_vital=False = best-effort → alert silenziati di default."""
    invalidate_silence_cache()
    fake_db = _FakeDB({"is_vital": False})
    silenced = await is_device_silenced(fake_db, "client-X", "10.99.0.2")
    assert silenced is True


@pytest.mark.asyncio
async def test_is_vital_missing_backward_compat():
    """is_vital assente + alerts_silenced assente → NON silenziato."""
    invalidate_silence_cache()
    fake_db = _FakeDB({})
    silenced = await is_device_silenced(fake_db, "client-X", "10.99.0.3")
    assert silenced is False


@pytest.mark.asyncio
async def test_alerts_silenced_only():
    """is_vital assente + alerts_silenced=True → silenziato (vecchio comportamento)."""
    invalidate_silence_cache()
    fake_db = _FakeDB({"alerts_silenced": True})
    silenced = await is_device_silenced(fake_db, "client-X", "10.99.0.4")
    assert silenced is True


@pytest.mark.asyncio
async def test_device_not_found_not_silenced():
    """Device sconosciuto → NON silenziato (alert vanno avanti per safety)."""
    invalidate_silence_cache()
    fake_db = _FakeDB(None)
    silenced = await is_device_silenced(fake_db, "client-X", "10.99.0.9999")
    assert silenced is False


@pytest.mark.asyncio
async def test_vital_true_overrides_alerts_silenced():
    """Anche con alerts_silenced=True esplicito, is_vital=True vince."""
    invalidate_silence_cache()
    fake_db = _FakeDB({"is_vital": True, "alerts_silenced": True})
    silenced = await is_device_silenced(fake_db, "client-X", "10.99.0.5")
    assert silenced is False


def test_endpoint_set_vital_registered():
    """Smoke: endpoint /devices/by-ip/{ip}/vital deve essere registrato nel router."""
    from routes.device_info_card import router
    paths = [r.path for r in router.routes]
    assert "/api/devices/by-ip/{device_ip}/vital" in paths


def test_cache_invalidation_per_device():
    """Invalidare cache singolo device non deve toccare gli altri."""
    invalidate_silence_cache()
    af_mod._SILENCE_CACHE[("c1", "1.1.1.1")] = (True, 9999999999)
    af_mod._SILENCE_CACHE[("c1", "1.1.1.2")] = (False, 9999999999)
    invalidate_silence_cache(client_id="c1", device_ip="1.1.1.1")
    assert ("c1", "1.1.1.1") not in af_mod._SILENCE_CACHE
    assert ("c1", "1.1.1.2") in af_mod._SILENCE_CACHE

