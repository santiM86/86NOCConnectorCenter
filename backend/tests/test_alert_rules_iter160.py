"""Test regole su metrica, dipendenze padre → figli e gruppi MAC condiviso (iter160)."""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import db  # noqa: E402
from alert_rules import run_metric_rules, nic_groups, suppressed_by_parent  # noqa: E402
from alert_filter import insert_alert_if_emit  # noqa: E402

CID = "test-alertrules-160"


async def main():
    ok = 0
    try:
        await db.alert_metric_rules.insert_one({"id": "r-pl", "name": "Perdita pacchetti", "metric": "packet_loss", "operator": ">", "threshold": 5,
                                                 "duration_min": 15, "severity": "high", "scope": "client", "client_id": CID, "enabled": True})
        await db.device_poll_status.insert_one({"client_id": CID, "device_ip": "10.60.0.1", "device_name": "FW", "ping_stats": {"packet_loss": 12}})
        t0 = datetime.now(timezone.utc)
        assert await run_metric_rules(t0) == 0  # inizio violazione
        assert await run_metric_rules(t0 + timedelta(minutes=10)) == 0  # non ancora 15 min
        assert await run_metric_rules(t0 + timedelta(minutes=16)) == 1
        al = await db.alerts.find_one({"client_id": CID, "source_type": "metric_rule"}, {"_id": 0})
        assert al and al["severity"] == "high" and al["status"] == "active", al
        assert await run_metric_rules(t0 + timedelta(minutes=20)) == 0  # dedup
        await db.device_poll_status.update_one({"client_id": CID, "device_ip": "10.60.0.1"}, {"$set": {"ping_stats": {"packet_loss": 0}}})
        await run_metric_rules(t0 + timedelta(minutes=21))
        assert (await db.alerts.find_one({"id": al["id"]}))["status"] == "resolved"
        ok += 1
        print("1. regola metrica: durata, alert HIGH, dedup, auto-chiusura OK")

        # scope: regola su altro cliente non si applica
        await db.alert_metric_rules.insert_one({"id": "r-cpu", "name": "CPU", "metric": "cpu", "operator": ">", "threshold": 50, "duration_min": 0,
                                                 "severity": "medium", "scope": "device", "client_id": CID, "device_ip": "10.60.0.9", "enabled": True})
        await db.device_poll_status.insert_one({"client_id": CID, "device_ip": "10.60.0.2", "cpu_usage": 99})
        await run_metric_rules()
        assert not await db.alerts.find_one({"client_id": CID, "rule_id": "r-cpu"})
        await db.device_poll_status.insert_one({"client_id": CID, "device_ip": "10.60.0.9", "cpu_usage": 99})
        await run_metric_rules()
        assert await db.alerts.find_one({"client_id": CID, "rule_id": "r-cpu", "device_ip": "10.60.0.9"})
        ok += 1
        print("2. scope dispositivo rispettato OK")

        # dipendenze
        await db.alert_dependencies.insert_one({"id": "d1", "client_id": CID, "parent_ip": "10.60.0.100", "child_ips": ["10.60.0.101", "10.60.0.102"]})
        child_alert = {"id": "c1", "client_id": CID, "device_ip": "10.60.0.101", "device_name": "VM1", "source_type": "corr_device_down", "status": "active"}
        assert await suppressed_by_parent(child_alert) is None  # padre su
        await db.alerts.insert_one({"id": "p1", "client_id": CID, "device_ip": "10.60.0.100", "device_name": "HOST", "source_type": "corr_server_down", "status": "active"})
        assert await insert_alert_if_emit(db, dict(child_alert)) is False
        p = await db.alerts.find_one({"id": "p1"}, {"_id": 0})
        assert p["impacted_devices"] == [{"name": "VM1", "ip": "10.60.0.101"}], p
        assert not await db.alerts.find_one({"id": "c1"})
        await db.alerts.update_one({"id": "p1"}, {"$set": {"status": "resolved"}})
        assert await insert_alert_if_emit(db, dict(child_alert)) is True  # padre tornato → figlio ancora giu' alerta
        ok += 1
        print("3. dipendenza padre giu' → figlio soppresso + impatto, padre su → figlio alerta OK")

        # gruppi MAC condiviso + proposta host
        M = "00:15:5d:10:20:30"
        await db.managed_devices.insert_many([
            {"id": "n1", "client_id": CID, "ip": "10.60.1.5", "mac": M, "name": "SRV-VM1", "virtualization": "hyperv"},
            {"id": "n2", "client_id": CID, "ip": "10.60.1.6", "mac": M, "name": "HOSTSRV", "virtualization": "physical"},
            {"id": "n3", "client_id": CID, "ip": "10.60.1.7", "mac": M.upper(), "name": "SRV-VM2", "virtualization": "hyperv"},
            {"id": "n4", "client_id": CID, "ip": "10.60.1.8", "mac": "00:15:5d:99:99:99", "name": "SOLO"},
        ])
        g = await nic_groups(CID)
        assert len(g) == 1 and g[0]["host_ip"] == "10.60.1.6" and not g[0]["host_manual"] and sorted(g[0]["child_ips"]) == ["10.60.1.5", "10.60.1.7"], g
        await db.nic_hosts.insert_one({"client_id": CID, "mac": M, "host_ip": "10.60.1.7"})
        g = await nic_groups(CID)
        assert g[0]["host_ip"] == "10.60.1.7" and g[0]["host_manual"], g
        ok += 1
        print("4. gruppi MAC condiviso: host proposto (fisico) e host manuale OK")
    finally:
        for c in ("alert_metric_rules", "device_poll_status", "alerts", "metric_rule_state", "alert_dependencies", "managed_devices", "nic_hosts"):
            await db[c].delete_many({"client_id": CID} if c not in ("alert_metric_rules",) else {"id": {"$in": ["r-pl", "r-cpu"]}})
        await db.metric_rule_state.delete_many({"rule_id": {"$in": ["r-pl", "r-cpu"]}})
    print(f"PASS {ok}/4")


asyncio.run(main())
