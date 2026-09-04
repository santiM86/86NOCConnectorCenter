"""Porta switch giù verso device vitale / uplink — modello 1+1."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv("/app/backend/.env")

from database import db
import alert_engine
import port_link_alerts

CID = "__portlink_test__"
SW = "10.77.0.1"
VITAL_IP = "10.77.0.50"
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
    await db.alerts.delete_many({"client_id": CID})
    await db.mac_connections.delete_many({"client_id": CID})
    await db.managed_devices.delete_many({"client_id": CID})
    await db.clients.delete_many({"id": CID})


async def run():
    _patch()
    await _clean()
    await db.clients.insert_one({"id": CID, "name": "TEST"})
    await db.managed_devices.insert_one({"client_id": CID, "ip": VITAL_IP, "name": "SRV-CRITICO", "is_vital": True})
    await db.mac_connections.insert_one({"client_id": CID, "from_ip": SW, "from_port": 5, "to_ip": VITAL_IP, "source": "mac_table"})

    # idx5 = verso vitale ; idx24 = uplink ; idx1 = porta normale (client)
    prev = {5: {"oper": 1, "admin": 1}, 24: {"oper": 1, "admin": 1}, 1: {"oper": 1, "admin": 1}}
    down_ports = [
        {"idx": 5, "oper": 2, "admin": 1, "name": "GigabitEthernet0/5"},
        {"idx": 24, "oper": 2, "admin": 1, "name": "Uplink-Core", "descr": "trunk"},
        {"idx": 1, "oper": 2, "admin": 1, "name": "GigabitEthernet0/1"},
    ]
    try:
        # DOWN
        TG.clear()
        await port_link_alerts.evaluate_port_links(db, CID, SW, prev, down_ports)
        active = await db.alerts.find({"client_id": CID, "source_type": "port_link_down", "status": "active"}, {"_id": 0}).to_list(50)
        keys = {a["dedup_key"].split(":")[-1] for a in active}
        assert keys == {"5", "24"}, f"attese porte 5 (vitale) e 24 (uplink), trovate {keys}"
        assert len(TG) == 2, f"attesi 2 messaggi (vitale+uplink), trovati {len(TG)}"
        vital_alert = next(a for a in active if a["dedup_key"].endswith(":5"))
        assert "SRV-CRITICO" in vital_alert["message"] and vital_alert["severity"] == "critical"
        print("[OK] DOWN: porta vitale + uplink → 2 allarmi (porta normale idx1 IGNORATA), 2 msg Telegram")

        # Persistenza (stesso stato down) → nessun nuovo messaggio
        TG.clear()
        prev_down = {5: {"oper": 2, "admin": 1}, 24: {"oper": 2, "admin": 1}, 1: {"oper": 2, "admin": 1}}
        await port_link_alerts.evaluate_port_links(db, CID, SW, prev_down, down_ports)
        assert len(TG) == 0, f"persistenza non deve rinotificare, {len(TG)}"
        print("[OK] Persistenza down: 0 messaggi (no loop)")

        # RECOVERY (up)
        TG.clear()
        up_ports = [
            {"idx": 5, "oper": 1, "admin": 1, "name": "GigabitEthernet0/5"},
            {"idx": 24, "oper": 1, "admin": 1, "name": "Uplink-Core", "descr": "trunk"},
            {"idx": 1, "oper": 1, "admin": 1, "name": "GigabitEthernet0/1"},
        ]
        await port_link_alerts.evaluate_port_links(db, CID, SW, prev_down, up_ports)
        assert len(TG) == 2, f"attesi 2 messaggi di rientro, trovati {len(TG)}"
        assert all(t.get("severity") == "recovery" for t in TG)
        n_active = await db.alerts.count_documents({"client_id": CID, "source_type": "port_link_down", "status": "active"})
        assert n_active == 0, f"tutti gli allarmi porta devono essere risolti, attivi={n_active}"
        print("[OK] RECOVERY: 2 messaggi di rientro + allarmi risolti")

        print("\nTUTTI I TEST PASSATI")
    finally:
        await _clean()


if __name__ == "__main__":
    asyncio.run(run())
