"""Verifica: 1 messaggio Telegram all'apertura + 1 al RIENTRO (no flood), su iLO.
Usa il DB preview reale con device_ip fittizio e cleanup."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

from database import db
import alert_engine
import redfish

IP = "203.0.113.77"  # TEST-NET-3, non instradabile
TG = []


async def fake_send(db_, **kw):
    TG.append(kw)
    return True


async def fake_cfg(db_):
    return {"channels": ["push", "telegram"], "telegram_enabled": True,
            "telegram_min_severity": "critical", "telegram_quiet_enabled": True,
            "telegram_quiet_start": "00:00", "telegram_quiet_end": "23:59",
            "telegram_chat_id": "1", "telegram_bot_token": "x"}


def _patch():
    import telegram_notifier
    telegram_notifier.send_alert_telegram = fake_send
    alert_engine.get_config = fake_cfg
    import maintenance_gate
    async def _no(db_, c, i):
        return False
    maintenance_gate.is_in_maintenance = _no


async def _clean():
    await db.alerts.delete_many({"device_ip": IP})


def _res(psu_ok):
    return {"health_status": "ok", "temperatures": [], "fans": [],
            "storage_controllers": [], "memory_dimms": [], "network_adapters": [],
            "power_supplies": ([] if psu_ok else [{"name": "PSU 2", "condition": "critical"}])}


async def run():
    _patch()
    await _clean()
    try:
        poller = redfish.RedfishPoller(db)

        # Poll 1: PSU guasto → 1 messaggio di apertura
        TG.clear()
        await poller._check_alerts(IP, "TESTSRV", _res(psu_ok=False), client_id="ctest")
        assert len(TG) == 1, f"atteso 1 msg apertura, {len(TG)}"
        assert "RIENTRAT" not in TG[0]["title"].upper()
        act = await db.alerts.find_one({"device_ip": IP, "status": "active"})
        assert act and act.get("telegram_notified") is True, "alert attivo marcato telegram_notified"
        print("[OK] Poll 1 (PSU guasto): 1 messaggio di apertura + telegram_notified=True")

        # Poll 2: PSU ancora guasto → NESSUN nuovo messaggio (dedup, no loop)
        TG.clear()
        await poller._check_alerts(IP, "TESTSRV", _res(psu_ok=False), client_id="ctest")
        assert len(TG) == 0, f"persistendo il problema NON deve reinviare, {len(TG)}"
        n_active = await db.alerts.count_documents({"device_ip": IP, "status": "active"})
        assert n_active == 1, f"1 solo alert attivo, {n_active}"
        print("[OK] Poll 2 (PSU ancora guasto): 0 messaggi (nessun loop)")

        # Poll 3: PSU rientrato → 1 messaggio di RIENTRO + alert risolto
        TG.clear()
        await poller._check_alerts(IP, "TESTSRV", _res(psu_ok=True), client_id="ctest")
        assert len(TG) == 1, f"atteso 1 msg di rientro, {len(TG)}"
        assert TG[0].get("severity") == "recovery" and "RIENTRAT" in TG[0]["title"].upper()
        assert "Disservizio durato" in (TG[0].get("message") or ""), "il rientro deve riportare la durata"
        still = await db.alerts.find_one({"device_ip": IP, "status": "active"})
        assert still is None, "l'alert deve risultare risolto"
        print("[OK] Poll 3 (PSU rientrato): 1 messaggio di RIENTRO (con durata) + alert risolto")

        # Unit: formattazione durata SLA
        assert alert_engine._outage_duration_str("2026-06-01T10:00:00+00:00", "2026-06-01T10:42:00+00:00") == "42 min"
        assert alert_engine._outage_duration_str("2026-06-01T10:00:00+00:00", "2026-06-01T13:12:00+00:00") == "3 h 12 min"
        assert alert_engine._outage_duration_str("2026-06-01T10:00:00+00:00", "2026-06-03T14:00:00+00:00") == "2 g 4 h"
        print("[OK] _outage_duration_str: 42 min / 3 h 12 min / 2 g 4 h")

        # Poll 4: tutto ok → nessun messaggio
        TG.clear()
        await poller._check_alerts(IP, "TESTSRV", _res(psu_ok=True), client_id="ctest")
        assert len(TG) == 0, "nessun problema → nessun messaggio"
        print("[OK] Poll 4 (tutto ok): 0 messaggi")

        print("\nTUTTI I TEST PASSATI — 1 apertura + 1 rientro, nessun flood")
    finally:
        await _clean()


if __name__ == "__main__":
    asyncio.run(run())
