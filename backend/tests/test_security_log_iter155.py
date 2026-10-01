"""Registro accessi AdS: ingest + catena hash + tamper + alert. cd /app/backend && set -a && . ./.env && set +a && python tests/test_security_log_iter155.py"""
import asyncio
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")
from database import db  # noqa: E402
from security_log import ingest_security_events, verify_chain  # noqa: E402

CID = f"test-seclog-{uuid.uuid4().hex[:6]}"
HOST = "SRV-TEST01"


def ev(rid, eid, data, log="Security"):
    return {"log": log, "record_id": rid, "event_id": eid, "ts": datetime.now(timezone.utc).isoformat(), "data": data}


async def main():
    ok = 0
    try:
        await db.security_admins.insert_one({"client_id": CID, "users": ["it-admin"]})
        batch = [
            ev(1, 4624, {"TargetUserName": "m.rossi", "TargetDomainName": "ACME", "LogonType": "10", "IpAddress": "10.0.0.5", "WorkstationName": "PC-ROSSI"}),
            ev(2, 4624, {"TargetUserName": "SRV-TEST01$", "LogonType": "3"}),  # rumore macchina
            ev(3, 4624, {"TargetUserName": "SYSTEM", "LogonType": "5"}),  # rumore
            ev(4, 4672, {"SubjectUserName": "it-admin", "SubjectDomainName": "ACME"}),
            ev(5, 4624, {"TargetUserName": "it-admin", "TargetDomainName": "ACME", "LogonType": "2"}),
            ev(6, 4720, {"TargetUserName": "backdoor", "SubjectUserName": "it-admin"}),
            ev(7, 4732, {"MemberName": "CN=backdoor", "TargetUserName": "Administrators", "SubjectUserName": "it-admin"}),
            ev(8, 1102, {"SubjectUserName": "it-admin"}),
            ev(50, 6005, {}, "System"),
            ev(9999, 9999, {}),  # id sconosciuto → ignorato
        ] + [ev(100 + i, 4625, {"TargetUserName": "administrator", "IpAddress": "203.0.113.9", "LogonType": "3"}) for i in range(12)]
        res = await ingest_security_events(CID, "agent-x", HOST, batch)
        assert res["stored"] == 19 and res["skipped"] == 3, res
        rows = await db.security_events.find({"client_id": CID}, {"_id": 0}).sort("seq", 1).to_list(100)
        assert [r["seq"] for r in rows] == list(range(1, 20))
        assert rows[0]["prev_hash"] == "GENESIS" and all(rows[i]["prev_hash"] == rows[i - 1]["hash"] for i in range(1, len(rows)))
        r1 = rows[0]
        assert r1["user"] == "m.rossi" and r1["logon_type"] == 10 and r1["logon_type_label"] == "RDP / Remoto" and r1["src_ip"] == "10.0.0.5" and r1["is_admin"] is False
        adm = [r for r in rows if r["is_admin"]]
        assert {r["event_id"] for r in adm} >= {4672, 4624, 4720, 1102}, [(r["event_id"], r["user"]) for r in adm]
        grp = next(r for r in rows if r["event_id"] == 4732)
        assert grp["group"] == "Administrators" and grp["target_user"] == "backdoor" and grp["user"] == "backdoor"
        assert all(isinstance(r.get("expire_at"), datetime) for r in rows)
        ok += 1
        print("1. ingest/normalizzazione/rumore/catena/is_admin OK")

        # dedup record_id
        res2 = await ingest_security_events(CID, "agent-x", HOST, batch[:2])
        assert res2["stored"] == 0, res2
        ok += 1
        print("2. dedup record_id OK")

        v = await verify_chain(CID)
        assert v["ok"] and v["checked"] == 19, v
        ok += 1
        print("3. verify_chain OK")

        # alert: log cleared (critical), account created (high), gruppo admin (high), brute force (high)
        titles = [a["title"] for a in await db.alerts.find({"client_id": CID}, {"_id": 0, "title": 1}).to_list(50)]
        assert any("REGISTRO EVENTI CANCELLATO" in t for t in titles), titles
        assert any("Nuovo account backdoor" in t for t in titles), titles
        assert any("gruppo amministrativo" in t for t in titles), titles
        assert any("Brute-force" in t and "administrator" in t for t in titles), titles
        ok += 1
        print(f"4. alert generati ({len(titles)}) OK")

        # tamper: modifico un utente → catena rotta al seq 5
        orig = (await db.security_events.find_one({"client_id": CID, "seq": 5}, {"_id": 0, "user": 1}))["user"]
        await db.security_events.update_one({"client_id": CID, "seq": 5}, {"$set": {"user": "hacker"}})
        v2 = await verify_chain(CID)
        assert not v2["ok"] and v2["broken_at_seq"] == 5, v2
        await db.security_events.update_one({"client_id": CID, "seq": 5}, {"$set": {"user": orig}})
        # rimozione evento → sequenza interrotta
        await db.security_events.delete_one({"client_id": CID, "seq": 7})
        v3 = await verify_chain(CID)
        assert not v3["ok"] and v3["broken_at_seq"] == 8 and "sequenza" in v3["reason"], v3
        ok += 1
        print("5. tamper detection (alterazione + rimozione) OK")
    finally:
        for c in ("security_events", "security_chain_state", "security_admins", "alerts"):
            await db[c].delete_many({"client_id": CID})
    print(f"PASS {ok}/5")


asyncio.run(main())
