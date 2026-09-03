"""Verifica: guasto hardware iLO (PSU) → Telegram ISTANTANEO.

Copre il gap trovato: redfish._check_alerts non inviava Telegram; e le quiet
hours/manutenzione non devono sopprimere i guasti fisici (instant=True).
"""
import asyncio
import types
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import alert_engine
import redfish


class FakeCursor:
    async def to_list(self, n):
        return []


class FakeColl:
    def __init__(self):
        self.inserted = []
    async def find_one(self, *a, **k):
        return None
    async def insert_one(self, doc):
        self.inserted.append(doc)
        return types.SimpleNamespace(inserted_id="x")
    async def update_one(self, *a, **k):
        return None


class FakeDB:
    def __init__(self):
        self.alerts = FakeColl()
        self.clients = FakeColl()


TG_CALLS = []


async def fake_send_alert_telegram(db, **kwargs):
    TG_CALLS.append(kwargs)
    return True


async def fake_get_config(db):
    return {
        "channels": ["push", "telegram"],
        "telegram_enabled": True,
        "telegram_min_severity": "critical",
        "telegram_quiet_enabled": True,
        "telegram_quiet_start": "00:00",   # quiet SEMPRE attivo per il test
        "telegram_quiet_end": "23:59",
        "telegram_chat_id": "123",
        "telegram_bot_token": "abc",
    }


def _patch():
    # intercetta l'invio reale
    import telegram_notifier
    telegram_notifier.send_alert_telegram = fake_send_alert_telegram
    alert_engine.get_config = fake_get_config
    # manutenzione sempre attiva → deve comunque passare per instant
    import maintenance_gate
    async def _in_maint(db, cid, ip):
        return True
    maintenance_gate.is_in_maintenance = _in_maint


async def run():
    _patch()
    db = FakeDB()

    # 1) notify_alert_telegram diretto con alert PSU instant → deve INVIARE
    TG_CALLS.clear()
    psu_alert = {
        "id": "1", "client_id": "c1", "device_ip": "10.0.0.5",
        "device_name": "GALVANSRV", "device_type": "ilo",
        "severity": "critical", "source_type": "redfish_direct",
        "title": "Alimentatore critical",
        "message": "PSU 2 guasto", "instant": True,
    }
    res = await alert_engine.notify_alert_telegram(db, psu_alert)
    assert res is True, f"PSU instant deve inviare subito, invece: {res}"
    assert len(TG_CALLS) == 1, f"atteso 1 invio Telegram, trovato {len(TG_CALLS)}"
    print("[OK] PSU instant: Telegram inviato anche in quiet hours + manutenzione")

    # 2) Alert NON-instant in quiet hours (senza manutenzione) → ACCODATO (queued)
    TG_CALLS.clear()
    import maintenance_gate
    async def _no_maint(db, cid, ip):
        return False
    maintenance_gate.is_in_maintenance = _no_maint
    noise = dict(psu_alert); noise["instant"] = False; noise["source_type"] = "info"
    res2 = await alert_engine.notify_alert_telegram(db, noise)
    assert res2 == "queued", f"atteso queued in quiet hours, invece: {res2}"
    assert len(TG_CALLS) == 0
    print("[OK] Alert non-instant in quiet hours: accodato (nessun invio immediato)")

    # ripristina manutenzione sempre attiva per il test 3 (instant deve bypassarla)
    async def _in_maint(db, cid, ip):
        return True
    maintenance_gate.is_in_maintenance = _in_maint

    # 3) Percorso REALE redfish._check_alerts con PSU guasto → deve chiamare Telegram
    TG_CALLS.clear()
    poller = redfish.RedfishPoller(db)
    result = {
        "health_status": "ok",
        "temperatures": [],
        "fans": [],
        "power_supplies": [
            {"name": "PSU 2", "condition": "critical"},
        ],
        "storage_controllers": [],
        "memory_dimms": [],
        "network_adapters": [],
    }
    await poller._check_alerts("10.0.0.5", "GALVANSRV", result, client_id="c1")
    assert len(db.alerts.inserted) == 1, "alert PSU deve essere inserito"
    assert len(TG_CALLS) == 1, f"redfish _check_alerts deve inviare Telegram, trovato {len(TG_CALLS)}"
    assert "Alimentatore" in TG_CALLS[0].get("title", "")
    print("[OK] redfish._check_alerts(PSU critical) → Telegram inviato istantaneamente")

    print("\nTUTTI I TEST PASSATI")


if __name__ == "__main__":
    asyncio.run(run())
