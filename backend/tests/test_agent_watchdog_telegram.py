"""Verifica watchdog Agent v4 offline → alert 'AGENT OFFLINE' + Telegram (DB preview, con cleanup)."""
import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

from database import db
import alert_engine
import connector_watchdog
from connector_watchdog import ConnectorWatchdog

CID = "__test_agent_wd_client__"
TG_CALLS = []


async def fake_send_alert_telegram(db_, **kwargs):
    TG_CALLS.append(kwargs)
    return True


async def fake_get_config(db_):
    return {
        "channels": ["push", "telegram"], "telegram_enabled": True,
        "telegram_min_severity": "critical",
        "telegram_quiet_enabled": True, "telegram_quiet_start": "00:00",
        "telegram_quiet_end": "23:59", "telegram_chat_id": "1", "telegram_bot_token": "x",
    }


def _patch():
    import telegram_notifier
    telegram_notifier.send_alert_telegram = fake_send_alert_telegram
    alert_engine.get_config = fake_get_config
    import maintenance_gate
    async def _no_maint(db_, cid, ip):
        return False
    maintenance_gate.is_in_maintenance = _no_maint


async def _clean():
    await db.managed_agents.delete_many({"client_id": CID})
    await db.clients.delete_many({"id": CID})
    await db.alerts.delete_many({"client_id": CID})


async def run():
    _patch()
    await _clean()
    now = datetime.now(timezone.utc)
    await db.clients.insert_one({"id": CID, "name": "TEST-CLIENTE"})
    # Agent stale (heartbeat 10 min fa) e non disinstallato
    await db.managed_agents.insert_one({
        "agent_id": "ag-1", "client_id": CID, "hostname": "SRVDC",
        "role": "master", "last_heartbeat_at": (now - timedelta(minutes=10)).isoformat(),
    })
    try:
        wd = ConnectorWatchdog(db)

        TG_CALLS.clear()
        await wd.check_all_agents()
        alert = await db.alerts.find_one({"client_id": CID, "source_type": "agent_watchdog", "status": "active"})
        assert alert is not None, "atteso alert AGENT OFFLINE"
        assert "AGENT OFFLINE" in alert["title"]
        assert len(TG_CALLS) == 1, f"atteso 1 invio Telegram, trovato {len(TG_CALLS)}"
        print("[OK] Agent v4 stale → alert 'AGENT OFFLINE' creato + Telegram inviato")

        # Idempotenza: seconda run senza ripristino → nessun nuovo invio
        TG_CALLS.clear()
        await wd.check_all_agents()
        assert len(TG_CALLS) == 0
        n_active = await db.alerts.count_documents({"client_id": CID, "source_type": "agent_watchdog", "status": "active"})
        assert n_active == 1, f"atteso 1 alert attivo (no duplicati), trovato {n_active}"
        print("[OK] Idempotente: nessun alert/Telegram duplicato")

        # Ripristino heartbeat → auto-resolve + record recovery
        await db.managed_agents.update_one(
            {"agent_id": "ag-1"}, {"$set": {"last_heartbeat_at": datetime.now(timezone.utc).isoformat()}})
        await wd.check_all_agents()
        still_active = await db.alerts.find_one({"client_id": CID, "source_type": "agent_watchdog", "status": "active"})
        recovery = await db.alerts.find_one({"client_id": CID, "source_type": "agent_recovery"})
        assert still_active is None, "l'alert deve essere risolto al ripristino"
        assert recovery is not None, "atteso record di recovery"
        print("[OK] Ripristino heartbeat → alert risolto + record recovery")

        print("\nTUTTI I TEST PASSATI")
    finally:
        await _clean()


if __name__ == "__main__":
    asyncio.run(run())
