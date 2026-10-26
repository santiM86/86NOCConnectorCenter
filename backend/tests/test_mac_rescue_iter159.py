"""MAC rescue vitali. cd /app/backend && set -a && . ./.env && set +a && python tests/test_mac_rescue_iter159.py"""
import asyncio
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")
from database import db  # noqa: E402
import mac_rescue as mr  # noqa: E402

CID = f"test-rescue-{uuid.uuid4().hex[:6]}"
MAC = "00:1b:63:84:45:e6"


class FakeConn:
    agent_id = "agent-fake"
    sent = []

    async def send_command(self, name, args, timeout=8.0):
        self.sent.append((name, args))
        return {"accepted": True}


async def main():
    ok = 0
    try:
        md = {"id": f"{CID}-srv", "client_id": CID, "ip": "10.5.0.20", "ip_address": "10.5.0.20", "mac": MAC, "name": "SRV-VITALE", "is_vital": True}
        await db.managed_devices.insert_one(dict(md))
        await db.vital_offline_state.insert_one({"client_id": CID, "ip": "10.5.0.20", "level": 1, "alert_id": "a1", "first_offline_at": datetime.now(timezone.utc).isoformat()})
        await db.alerts.insert_one({"id": "a1", "client_id": CID, "device_ip": "10.5.0.20", "status": "active", "source_type": "corr_host_down", "title": "CRITICO: SRV-VITALE", "severity": "critical"})
        conn = FakeConn()
        sid = await mr.start_mac_rescue(conn, CID, md)
        assert sid and conn.sent[0][0] == "lan_scan" and conn.sent[0][1]["cidr"] == "10.5.0.0/24", conn.sent
        assert await mr.rescue_pending(CID, "10.5.0.20") is True
        assert await mr.start_mac_rescue(conn, CID, md) is None  # cooldown
        ok += 1
        print("1. start rescue (scan /24 inviato, pending, cooldown) OK")

        run = await db.lan_scan_runs.find_one({"scan_id": sid}, {"_id": 0})
        assert run["purpose"] == "mac_rescue"
        # risultato in streaming con il MAC su nuovo IP
        await mr.on_rescue_scan_event("lan_scan_result", run, {"ip": "10.5.0.77", "mac": "00-1B-63-84-45-E6"})
        d = await db.managed_devices.find_one({"id": md["id"]}, {"_id": 0})
        assert d["ip"] == "10.5.0.77" and d["ip_previous"] == "10.5.0.20", d
        assert await db.vital_offline_state.count_documents({"client_id": CID, "ip": "10.5.0.20"}) == 0
        a1 = await db.alerts.find_one({"id": "a1"}, {"_id": 0})
        assert a1["status"] == "resolved" and "cambiato IP" in a1["resolution_note"], a1
        chg = await db.alerts.find_one({"client_id": CID, "source_type": "mac_follow_ip_update"}, {"_id": 0})
        assert chg and chg["severity"] == "high" and chg["title"].startswith("VITALE IP cambiato") and chg["force_telegram"] is True, chg
        assert await mr.rescue_pending(CID, "10.5.0.20") is False
        ok += 1
        print("2. MAC trovato su nuovo IP → IP aggiornato, falso offline risolto, alert HIGH 'VITALE IP cambiato' OK")

        # device non trovato → done/found False e il watchdog procede
        md2 = {"id": f"{CID}-sw", "client_id": CID, "ip": "10.5.0.30", "mac": "00:1b:63:00:00:01", "name": "SW-CORE", "is_vital": True}
        await db.managed_devices.insert_one(dict(md2))
        sid2 = await mr.start_mac_rescue(conn, CID, md2)
        run2 = await db.lan_scan_runs.find_one({"scan_id": sid2}, {"_id": 0})
        await mr.on_rescue_scan_event("lan_scan_done", {**run2, "results": [{"ip": "10.5.0.5", "mac": "aa:aa:aa:aa:aa:aa"}]}, {})
        st = await db.mac_rescue_state.find_one({"client_id": CID, "ip": "10.5.0.30"}, {"_id": 0})
        assert st["done"] is True and st["found"] is False and await mr.rescue_pending(CID, "10.5.0.30") is False
        ok += 1
        print("3. MAC non trovato → stato chiuso, watchdog libero di alertare OK")
    finally:
        for c in ("managed_devices", "vital_offline_state", "alerts", "lan_scan_runs", "mac_rescue_state"):
            await db[c].delete_many({"client_id": CID})
    print(f"PASS {ok}/3")


asyncio.run(main())
