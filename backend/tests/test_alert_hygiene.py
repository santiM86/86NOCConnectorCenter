"""Igiene allarmi + riepilogo giornaliero Telegram."""
import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

from database import db
import alert_hygiene
import telegram_notifier

MARK = "__hygiene_test__"
SENT = []


async def fake_send_text(db_, text, chat_id=None, token=None, parse_mode="HTML"):
    SENT.append(text)
    return {"success": True}


async def _clean():
    await db.alerts.delete_many({"device_name": MARK})


async def run():
    telegram_notifier.send_telegram_text = fake_send_text
    await _clean()
    now = datetime.now(timezone.utc)
    old = (now - timedelta(hours=48)).isoformat()
    recent = (now - timedelta(hours=1)).isoformat()

    await db.alerts.insert_many([
        {"id": "h1", "device_name": MARK, "severity": "medium", "status": "active", "created_at": old},
        {"id": "h2", "device_name": MARK, "severity": "low", "status": "active", "created_at": old},
        {"id": "h3", "device_name": MARK, "severity": "medium", "status": "active", "created_at": recent},
        {"id": "h4", "device_name": MARK, "severity": "critical", "status": "active", "created_at": old},
        {"id": "h5", "device_name": MARK, "severity": "high", "status": "active", "created_at": old},
    ])
    try:
        await alert_hygiene.expire_stale_alerts(db)
        async def st(i):
            return (await db.alerts.find_one({"id": i}))["status"]
        assert await st("h1") == "resolved", "medium vecchio → risolto"
        assert await st("h2") == "resolved", "low vecchio → risolto"
        assert await st("h3") == "active", "medium recente → resta attivo"
        assert await st("h4") == "active", "critical → mai toccato"
        assert await st("h5") == "active", "high → mai toccato"
        h1 = await db.alerts.find_one({"id": "h1"})
        assert h1.get("auto_expired") is True and "igiene" in (h1.get("resolution_note") or "").lower()
        print("[OK] expire_stale_alerts: medium/low vecchi risolti; recente/critical/high intatti")

        # Riepilogo giornaliero (Telegram enabled?)
        cfg = await db.alert_engine_config.find_one({"_id": "global"}) or {}
        SENT.clear()
        ok = await alert_hygiene.send_daily_summary(db)
        if "telegram" in (cfg.get("channels") or []) and cfg.get("telegram_enabled"):
            assert ok and len(SENT) == 1, "riepilogo inviato"
            msg = SENT[0]
            assert "Riepilogo giornaliero" in msg
            assert "aperti oggi" in msg and "Rientrati oggi" in msg and "Durata media" in msg
            print("[OK] send_daily_summary: messaggio inviato con aperti/rientrati/durata media")
        else:
            assert ok is False
            print("[OK] send_daily_summary: Telegram disabilitato → nessun invio (corretto)")

        print("\nTUTTI I TEST PASSATI")
    finally:
        await _clean()


if __name__ == "__main__":
    asyncio.run(run())
