"""USB / fuori orario / origine nuova + scadenza certificati. cd /app/backend && set -a && . ./.env && set +a && python tests/test_anomalies_iter158.py"""
import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app/backend")
from database import db  # noqa: E402
import security_log as sl  # noqa: E402
from services import osint_poller as poller  # noqa: E402

CID = f"test-anom-{uuid.uuid4().hex[:6]}"
HOST = "SRV-ANOM"


def ev(rid, eid, data, log="Security", ts=None):
    return {"log": log, "record_id": rid, "event_id": eid, "ts": (ts or datetime.now(timezone.utc)).isoformat(), "data": data}


async def titles():
    return [a["title"] for a in await db.alerts.find({"client_id": CID}, {"_id": 0, "title": 1}).to_list(50)]


async def main():
    ok = 0
    try:
        # orario lavorativo stretto per rendere deterministico il test: 09:00-09:01 solo lunedì → ora corrente è "fuori orario"
        await db.security_log_settings.insert_one({"client_id": CID, "work_hours": {"start": "09:00", "end": "09:01", "days": [0], "tz": "Europe/Rome"}})
        st = await sl.get_settings(CID)
        assert st["work_hours"]["start"] == "09:00" and st["usb_alerts"] is True and st["retention_months"] == 12
        # 1. USB: Kernel-PnP 400 (log corretto) + 2003; 400 su log sbagliato ignorato
        r = await sl.ingest_security_events(CID, "a", HOST, [
            ev(1, 400, {"DeviceInstanceId": "USBSTOR\\DISK&VEN_KINGSTON&PROD_DATATRAVELER_3.0\\1234", "DriverDescription": "Disk drive"}, "Microsoft-Windows-Kernel-PnP/Configuration"),
            ev(2, 400, {"DeviceInstanceId": "x"}, "Security"),
            ev(3, 2003, {"InstanceId": "USB\\VID_0951&PID_1666\\0012"}, "Microsoft-Windows-DriverFrameworks-UserMode/Operational"),
            ev(4, 6416, {"DeviceDescription": "SanDisk Ultra USB Device", "SubjectUserName": "m.rossi", "ClassName": "DiskDrive"}),
        ])
        assert r["stored"] == 3 and r["skipped"] == 1, r
        usb = await db.security_events.find({"client_id": CID, "category": "usb_insert"}, {"_id": 0}).sort("seq", 1).to_list(10)
        assert len(usb) == 3 and usb[0]["device"] == "Disk drive" and any(u["user"] == "m.rossi" for u in usb), usb
        t = await titles()
        assert sum("USB inserito" in x for x in t) >= 1, t
        ok += 1
        print("1. USB: eventi normalizzati + alert OK")

        # 2. fuori orario (RDP type 10) → alert
        await sl.ingest_security_events(CID, "a", HOST, [ev(10, 4624, {"TargetUserName": "g.bianchi", "LogonType": "10", "IpAddress": "192.168.1.50", "WorkstationName": "PC-01"})])
        t = await titles()
        assert any("fuori orario" in x and "g.bianchi" in x for x in t), t
        ok += 1
        print("2. accesso fuori orario → alert OK")

        # 3. origine nuova: profilo appreso (first_seen > 24h fa) con origini note → IP pubblico nuovo = high
        await db.security_login_profiles.update_one({"client_id": CID, "user": "g.bianchi"},
                                                    {"$set": {"first_seen": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()}})
        await sl.ingest_security_events(CID, "a", HOST, [ev(11, 4624, {"TargetUserName": "g.bianchi", "LogonType": "10", "IpAddress": "185.220.101.9"})])
        a = await db.alerts.find_one({"client_id": CID, "source_type": "seclog_new_origin"}, {"_id": 0})
        assert a and a["severity"] == "high" and "185.220.101.9" in a["title"], a
        prof = await db.security_login_profiles.find_one({"client_id": CID, "user": "g.bianchi"}, {"_id": 0})
        assert set(prof["origins"]) == {"192.168.1.50", "185.220.101.9"}, prof
        # stessa origine di nuovo → nessun nuovo alert
        n0 = await db.alerts.count_documents({"client_id": CID, "source_type": "seclog_new_origin"})
        await sl.ingest_security_events(CID, "a", HOST, [ev(12, 4624, {"TargetUserName": "g.bianchi", "LogonType": "10", "IpAddress": "185.220.101.9"})])
        assert await db.alerts.count_documents({"client_id": CID, "source_type": "seclog_new_origin"}) == n0
        ok += 1
        print("3. origine mai vista (IP pubblico) → alert high, profilo aggiornato, no duplicati OK")

        # 4. toggle off → nessun alert USB
        await db.security_log_settings.update_one({"client_id": CID}, {"$set": {"usb_alerts": False, "after_hours_alerts": False}})
        await db.alerts.delete_many({"client_id": CID})
        await sl.ingest_security_events(CID, "a", HOST, [ev(20, 2003, {"InstanceId": "USB\\VID_1\\2"}, "Microsoft-Windows-DriverFrameworks-UserMode/Operational"),
                                                         ev(21, 4624, {"TargetUserName": "z.verdi", "LogonType": "2"})])
        assert await titles() == [], await titles()
        ok += 1
        print("4. toggle disattivati rispettati OK")

        # 5. certificati: mock _tls_cert_info → 20 gg (medium), 3 gg (high), poi rinnovato → resolved
        state = {"days": 20}

        async def fake(ip, port, sni=None):
            na = datetime.now(timezone.utc) + timedelta(days=state["days"])
            return {"port": port, "cn": "vpn.cliente.it", "issuer": "Let's Encrypt", "sans": [], "not_after": na.isoformat(), "days_left": state["days"], "self_signed": False}
        poller._tls_cert_info = fake  # type: ignore
        certs = await poller._check_certificates(CID, "8.8.4.4", "FW-TEST", [443, 8443, 22], ["vpn.cliente.it"])
        assert [c["port"] for c in certs] == [443, 8443]
        al = await db.alerts.find({"client_id": CID, "source_type": "osint_cert_expiry"}, {"_id": 0}).to_list(10)
        assert len(al) == 2 and all(a["severity"] == "medium" for a in al), al
        state["days"] = 3
        await poller._check_certificates(CID, "8.8.4.4", "FW-TEST", [443], [])
        a443 = await db.alerts.find_one({"client_id": CID, "source_type": "osint_cert_expiry", "title": {"$regex": ":443"}}, {"_id": 0})
        assert a443["severity"] == "high", a443
        state["days"] = 85
        await poller._check_certificates(CID, "8.8.4.4", "FW-TEST", [443], [])
        a443 = await db.alerts.find_one({"client_id": CID, "source_type": "osint_cert_expiry", "title": {"$regex": ":443"}}, {"_id": 0})
        assert a443["status"] == "resolved", a443
        ok += 1
        print("5. certificati: 30gg medium → 7gg high → rinnovo resolved OK")
    finally:
        for c in ("security_events", "security_chain_state", "security_log_settings", "security_login_profiles", "alerts"):
            await db[c].delete_many({"client_id": CID})
    print(f"PASS {ok}/5")


asyncio.run(main())
