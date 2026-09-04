"""Switch (hardware SNMP): 1 messaggio apertura + dedup + 1 messaggio di RIENTRO su Telegram."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

from database import db
import alert_engine
import hardware_alerts

DK = "ctest:198.51.100.9:fan_fault"
DK_HIGH = "ctest:198.51.100.9:cpu"
IP = "198.51.100.9"
TG = []


async def fake_send(db_, **kw):
    TG.append(kw)
    return True


async def fake_cfg(db_):
    return {"channels": ["push", "telegram"], "telegram_enabled": True,
            "telegram_min_severity": "critical", "telegram_quiet_enabled": False,
            "telegram_chat_id": "1", "telegram_bot_token": "x"}


def _patch():
    import telegram_notifier
    telegram_notifier.send_alert_telegram = fake_send
    alert_engine.get_config = fake_cfg
    import maintenance_gate
    async def _no(db_, c, i):
        return False
    maintenance_gate.is_in_maintenance = _no
    import webpush
    async def _noop(*a, **k):
        return None
    webpush.notify_new_alert = _noop


async def _clean():
    await db.alerts.delete_many({"device_ip": IP})


async def run():
    _patch()
    await _clean()
    cfg = await fake_cfg(db)
    try:
        # 1) Guasto ventola (critical) → 1 messaggio di apertura
        TG.clear()
        await hardware_alerts._emit_or_update(
            db, cfg, client_id="ctest", client_name="TEST", device_name="SWITCH1",
            device_ip=IP, device_type="switch", dedup_key=DK, severity="critical",
            title="Guasto ventola su SWITCH1", message="Ventola #2 anomala")
        assert len(TG) == 1, f"apertura: atteso 1 msg, {len(TG)}"
        act = await db.alerts.find_one({"dedup_key": DK, "status": "active"})
        assert act and act.get("telegram_notified") is True
        print("[OK] Switch guasto ventola: 1 messaggio apertura + telegram_notified")

        # 2) Stessa condizione → nessun nuovo messaggio (dedup, no loop)
        TG.clear()
        await hardware_alerts._emit_or_update(
            db, cfg, client_id="ctest", client_name="TEST", device_name="SWITCH1",
            device_ip=IP, device_type="switch", dedup_key=DK, severity="critical",
            title="Guasto ventola su SWITCH1", message="Ventola #2 anomala")
        assert len(TG) == 0, f"persistenza: NON deve reinviare, {len(TG)}"
        print("[OK] Switch condizione persistente: 0 messaggi (no loop)")

        # 3) Ventola rientrata → 1 messaggio di RIENTRO
        TG.clear()
        await hardware_alerts._resolve_alert(db, cfg, DK, "Ventole tornate normali su SWITCH1 (198.51.100.9).")
        assert len(TG) == 1, f"rientro: atteso 1 msg, {len(TG)}"
        assert TG[0].get("severity") == "recovery"
        assert "SWITCH1" in (TG[0].get("message") or "")
        assert await db.alerts.find_one({"dedup_key": DK, "status": "active"}) is None
        print("[OK] Switch ventola rientrata: 1 messaggio di RIENTRO + alert risolto")

        # 4) Allarme 'high' bloccato dalla soglia (non aperto su Telegram) →
        #    alla risoluzione NON deve partire un rientro spurio
        TG.clear()
        await hardware_alerts._emit_or_update(
            db, cfg, client_id="ctest", client_name="TEST", device_name="SWITCH1",
            device_ip=IP, device_type="switch", dedup_key=DK_HIGH, severity="high",
            title="CPU elevata su SWITCH1", message="CPU 85%")
        assert len(TG) == 0, "high sotto soglia critical: nessuna apertura su Telegram"
        act_h = await db.alerts.find_one({"dedup_key": DK_HIGH, "status": "active"})
        assert act_h and not act_h.get("telegram_notified")
        TG.clear()
        await hardware_alerts._resolve_alert(db, cfg, DK_HIGH, "CPU rientrata su SWITCH1.")
        assert len(TG) == 0, "nessun rientro se l'apertura non era su Telegram"
        print("[OK] Switch 'high' non notificato: nessun rientro spurio (coppia 1+1 rispettata)")

        print("\nTUTTI I TEST PASSATI")
    finally:
        await _clean()


if __name__ == "__main__":
    asyncio.run(run())
